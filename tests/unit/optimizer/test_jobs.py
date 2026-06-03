"""Unit tests for optimizer.jobs.JobStore."""

import asyncio
import contextlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

import core.database as db
from optimizer.jobs import JobStore, OptimizerBusyError, _ActiveJob


@dataclass
class _FakeReq:
    pair: str = "XBTEUR"
    mode: str = "AGGRESSIVE"
    split_method: str = "RESET"
    start: str | None = None
    end: str | None = None

    @property
    def __dict__(self):
        return {
            "pair": self.pair,
            "mode": self.mode,
            "split_method": self.split_method,
            "start": self.start,
            "end": self.end,
        }


def _fake_process(alive: bool = True) -> MagicMock:
    p = MagicMock()
    p.is_alive.return_value = alive
    p.exitcode = 0
    return p


def test_try_start_inserts_row_and_returns_id(monkeypatch) -> None:
    store = JobStore()
    created_ids = []

    def _fake_create(pair, mode, split_method, request):
        job_id = "test-job-uuid"
        created_ids.append({"pair": pair, "mode": mode})
        return job_id

    monkeypatch.setattr(db, "create_optimizer_job", _fake_create)

    process = _fake_process()
    with patch("optimizer.jobs._CTX") as mock_ctx:
        mock_ctx.Queue.return_value = MagicMock()
        mock_ctx.Process.return_value = process

        job_id = store.try_start(_FakeReq())

    assert job_id == "test-job-uuid"
    assert created_ids[0]["pair"] == "XBTEUR"
    assert created_ids[0]["mode"] == "AGGRESSIVE"
    process.start.assert_called_once()


def test_try_start_busy_raises(monkeypatch) -> None:
    store = JobStore()
    alive_process = _fake_process(alive=True)
    store._active = _ActiveJob(
        job_id="existing-job",
        process=alive_process,
        queue=MagicMock(),
        pair="XBTEUR",
    )

    with pytest.raises(OptimizerBusyError, match="existing-job"):
        store.try_start(_FakeReq())


def test_finalize_completes_job(monkeypatch) -> None:
    store = JobStore()
    completed = {}

    monkeypatch.setattr(
        db, "complete_optimizer_job", lambda job_id, result: completed.update({"job_id": job_id, "result": result})
    )

    active = _ActiveJob(
        job_id="job-1",
        process=_fake_process(),
        queue=MagicMock(),
        pair="XBTEUR",
    )
    store._active = active

    store._finalize(active, "ok", {"scores": {"robust_pnl_pct": 3.5}})

    assert completed["job_id"] == "job-1"
    assert completed["result"]["scores"]["robust_pnl_pct"] == 3.5
    assert store._active is None


def test_finalize_failed_job(monkeypatch) -> None:
    store = JobStore()
    failed = {}

    monkeypatch.setattr(
        db, "fail_optimizer_job", lambda job_id, error: failed.update({"job_id": job_id, "error": error})
    )

    active = _ActiveJob(
        job_id="job-2",
        process=_fake_process(),
        queue=MagicMock(),
        pair="XBTEUR",
    )
    store._active = active

    store._finalize(active, "error", "boom")

    assert failed["job_id"] == "job-2"
    assert "boom" in failed["error"]
    assert store._active is None


def test_supervise_ok(monkeypatch) -> None:
    """supervise() calls _finalize with the result when the worker succeeds."""
    store = JobStore()
    completed = {}
    done = asyncio.Event()

    def _fake_complete(job_id, result):
        completed["job_id"] = job_id
        done.set()

    monkeypatch.setattr(db, "complete_optimizer_job", _fake_complete)

    queue = MagicMock()
    queue.get.return_value = ("ok", {"scores": {"robust_pnl_pct": 2.0}})

    active = _ActiveJob(job_id="job-ok", process=_fake_process(), queue=queue, pair="XBTEUR")
    store._active = active

    async def _run():
        task = asyncio.create_task(store.supervise())
        await asyncio.wait_for(done.wait(), timeout=2.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert completed["job_id"] == "job-ok"
    assert store._active is None
    queue.get.assert_called_once()


def test_supervise_error(monkeypatch) -> None:
    """supervise() calls _finalize with error when the worker fails."""
    store = JobStore()
    failed = {}
    done = asyncio.Event()

    def _fake_fail(job_id, error):
        failed["job_id"] = job_id
        failed["error"] = error
        done.set()

    monkeypatch.setattr(db, "fail_optimizer_job", _fake_fail)

    queue = MagicMock()
    queue.get.return_value = ("error", "boom")

    active = _ActiveJob(job_id="job-err", process=_fake_process(), queue=queue, pair="XBTEUR")
    store._active = active

    async def _run():
        task = asyncio.create_task(store.supervise())
        await asyncio.wait_for(done.wait(), timeout=2.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert failed["job_id"] == "job-err"
    assert "boom" in failed["error"]
    assert store._active is None
    queue.get.assert_called_once()
