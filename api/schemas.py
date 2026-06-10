from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MarketItem(BaseModel):
    pair: str
    base_asset: str | None = None
    last_price: float | None = None
    atr: float | None = None
    volatility_level: str | None = None


class PositionDetail(BaseModel):
    side: str
    volume: float
    entry_price: float
    activation_atr: float
    activation_price: float
    created_at: datetime
    activated_at: datetime | None = None
    trailing_price: float | None = None
    stop_price: float | None = None
    stop_atr: float | None = None
    closing_order_id: str | None = None
    closing_price: float | None = None
    closing_requested_at: datetime | None = None


class PositionResponse(BaseModel):
    pair: str
    position: PositionDetail | None = None


class BalanceResponse(BaseModel):
    balance: dict[str, float]


class StatusResponse(BaseModel):
    paused: bool
    last_run_at: datetime | None = None


class ControlRequest(BaseModel):
    updated_by: str | None = None


class ControlResponse(BaseModel):
    paused: bool
    updated_by: str | None = None


class BacktestRequest(BaseModel):
    pair: str
    fee_pct: float = 0.0
    start: str | None = None
    end: str | None = None
    max_ops: int | None = None
    use_live_config: bool = False


class OperationDTO(BaseModel):
    idx: int
    time: str
    side: str
    price: float
    vol: str
    k_stop: float
    fee_abs: float
    pnl_abs: float | None
    pnl_pct: float | None
    cum_pnl: float | None


class BacktestResponse(BaseModel):
    pair: str
    fee_pct: float
    summary: dict
    operations: list[OperationDTO]


class GridSpec(BaseModel):
    """A uniform numeric search grid expressed as ``start``/``end``/``step`` (kept
    this way, rather than an arbitrary list, so the optimizer can keep using
    ``suggest_float``/``suggest_int`` and preserve TPE's ordinal structure)."""

    start: float
    end: float
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate(self) -> GridSpec:
        if self.start > self.end:
            raise ValueError("start must be <= end")
        n = (self.end - self.start) / self.step
        if abs(round(n) - n) > 1e-9:
            raise ValueError("(end - start) must be an integer multiple of step")
        return self


class SearchSpace(BaseModel):
    """Search grids for an OPTIMIZE/AUTO run. All three grids must be informed
    (no defaults). A ``null`` activation grid disables that whole branch — ``k_act``
    null runs only the min_margin branch and vice versa; at least one must be set.
    To *fix* (rather than disable) a dimension, pass ``start == end``."""

    stop_pcts: GridSpec
    k_act: GridSpec | None
    min_margin: GridSpec | None

    @model_validator(mode="after")
    def _validate(self) -> SearchSpace:
        if self.k_act is None and self.min_margin is None:
            raise ValueError("at least one of k_act / min_margin must be provided")
        if self.stop_pcts.start < 0.0 or self.stop_pcts.end > 1.0:
            raise ValueError("stop_pcts grid must lie within [0, 1]")
        if self.k_act is not None and self.k_act.start < 0.0:
            raise ValueError("k_act grid must be >= 0")
        if self.min_margin is not None and self.min_margin.start < 0.0:
            raise ValueError("min_margin grid must be >= 0")
        return self


class OptimizerRequest(BaseModel):
    pair: str
    mode: Literal["OPTIMIZE", "CURRENT", "AUTO"]
    fee_pct: float = 0.0
    start: str | None = None
    end: str | None = None
    train_split: float = Field(default=0.8, ge=0.5, le=1.0)
    min_ops: int = 0
    min_test_ops: int = 0
    n_trials: int = Field(default=1_000, ge=1, le=10_000)
    seed: int = 42
    # AUTO mode params (ignored for OPTIMIZE/CURRENT)
    n_seeds: int = Field(default=4, ge=2, le=8)
    min_agree: int = Field(default=3, ge=2, le=8)
    trial_step: int = Field(default=500, ge=100, le=2_000)
    max_trials: int = Field(default=9_000, ge=500, le=20_000)
    # Search grids. Required for OPTIMIZE/AUTO (the search dimensions); ignored by
    # CURRENT, which evaluates the live .env config and searches nothing.
    search_space: SearchSpace | None = None

    @model_validator(mode="after")
    def _require_search_space(self) -> OptimizerRequest:
        if self.mode in ("OPTIMIZE", "AUTO") and self.search_space is None:
            raise ValueError("search_space is required for OPTIMIZE and AUTO modes")
        return self


class OptimizerJobAcceptedResponse(BaseModel):
    job_id: int
    status: Literal["running"] = "running"


class OptimizerJobStatusResponse(BaseModel):
    job_id: int
    pair: str
    mode: str
    split_method: str
    status: Literal["running", "completed", "failed"]
    request: dict
    result: dict | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
