"""Tests for the Phase 11 regime filter in the optimizer search.

These exercise the off-vs-on contract: with no regime in the search space the
results are exactly as before; with a RegimeSpace provided, all four regime
dimensions (er_window, chop_enter_pct, chop_dead_band, trend_pct) become extra
search dimensions and surface in the result and env lines.
"""

import copy

import numpy as np
import pandas as pd

import core.config as config
import trading.optimizer.search as optimizer
from trading.optimizer.search import (
    CurrentParams,
    GridSpec,
    OptimizerRequest,
    RegimeParams,
    RegimeSpace,
    SearchSpace,
    run_optimize,
)

_PAIR = "XBTEUR"
_LEVELS = ("LL", "LV", "MV", "HV", "HH")

_REGIME = RegimeSpace(
    er_window=GridSpec(start=16, end=32, step=16),
    chop_enter_pct=GridSpec(start=0.25, end=0.50, step=0.25),
    chop_dead_band=GridSpec(start=0.05, end=0.10, step=0.05),
    trend_pct=GridSpec(start=0.60, end=0.70, step=0.10),
)

_SPACE = SearchSpace(
    stop_pcts=GridSpec(start=0.3, end=0.9, step=0.3),
    k_act=GridSpec(start=0.5, end=2.0, step=0.5),
    min_margin=None,
)

_SPACE_WITH_REGIME = SearchSpace(
    stop_pcts=GridSpec(start=0.3, end=0.9, step=0.3),
    k_act=GridSpec(start=0.5, end=2.0, step=0.5),
    min_margin=None,
    regime=_REGIME,
)


def _make_df(n: int = 200) -> pd.DataFrame:
    i = np.arange(n)
    price = 100.0 + 25.0 * np.sin(i / 8.0)
    atr = 2.0 + 1.0 * np.abs(np.sin(i / 11.0))
    dtime = pd.date_range("2026-01-01", periods=n, freq="15min").strftime("%Y-%m-%d %H:%M").tolist()
    return pd.DataFrame(
        {
            "time": (np.arange(n) * 900 + 1_767_225_600).tolist(),
            "dtime": dtime,
            "high": price + 2.0,
            "low": price - 2.0,
            "close": price,
            "open": price,
            "atr": atr,
        }
    )


def test_regime_disabled_matches_baseline(monkeypatch) -> None:
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())

    result = run_optimize(
        OptimizerRequest(pair=_PAIR, mode="OPTIMIZE", n_trials=10, search_space=_SPACE), calibration=None
    )

    # No regime dimensions are searched; every candidate has them unset.
    for cand in result.top_candidates:
        assert cand["er_window"] is None
        assert cand["chop_enter_pct"] is None
        assert cand["chop_dead_band"] is None
        assert cand["trend_pct"] is None
    # ...and no ER lines leak into the suggested env.
    assert not any("ER_WINDOW" in line for line in result.suggested_env_lines)


def test_regime_enabled_expands_search(monkeypatch) -> None:
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())

    result = run_optimize(
        OptimizerRequest(pair=_PAIR, mode="OPTIMIZE", n_trials=12, search_space=_SPACE_WITH_REGIME),
        calibration=None,
    )

    best = result.top_candidates[0]
    assert best["er_window"] in (16, 32)
    assert best["chop_enter_pct"] in (0.25, 0.50)
    assert best["chop_dead_band"] in (0.05, 0.10)
    assert best["trend_pct"] in (0.60, 0.70)


def test_regime_enabled_no_global_mutation(monkeypatch) -> None:
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())
    monkeypatch.setitem(
        config.TRADING_PARAMS,
        _PAIR,
        {"buy": {"K_ACT": "1.0", "MIN_MARGIN": "0.005"}, "sell": {"K_ACT": "1.0", "MIN_MARGIN": "0.005"}},
    )
    monkeypatch.setitem(config.PAIRS, _PAIR, {"atr_20pct": 1.0, "atr_50pct": 2.0})
    before_tp = copy.deepcopy(config.TRADING_PARAMS[_PAIR])
    before_pairs = copy.deepcopy(config.PAIRS[_PAIR])

    run_optimize(
        OptimizerRequest(pair=_PAIR, mode="OPTIMIZE", n_trials=6, search_space=_SPACE_WITH_REGIME), calibration=None
    )

    assert config.TRADING_PARAMS[_PAIR] == before_tp
    assert config.PAIRS[_PAIR] == before_pairs


def test_regime_env_lines_emitted(monkeypatch) -> None:
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())

    result = run_optimize(
        OptimizerRequest(pair=_PAIR, mode="OPTIMIZE", n_trials=12, search_space=_SPACE_WITH_REGIME),
        calibration=None,
    )

    assert any(line.startswith(f"{_PAIR}_ER_WINDOW=") for line in result.suggested_env_lines)
    assert any(line.startswith(f"{_PAIR}_ER_CHOP_ENTER_PCT=") for line in result.suggested_env_lines)
    assert any(line.startswith(f"{_PAIR}_ER_CHOP_EXIT_PCT=") for line in result.suggested_env_lines)
    assert any(line.startswith(f"{_PAIR}_ER_TREND_PCT=") for line in result.suggested_env_lines)


def test_regime_chop_exit_gt_enter(monkeypatch) -> None:
    """chop_exit_pct must always be > chop_enter_pct (dead band guarantee)."""
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())

    result = run_optimize(
        OptimizerRequest(pair=_PAIR, mode="OPTIMIZE", n_trials=12, search_space=_SPACE_WITH_REGIME),
        calibration=None,
    )

    for line in result.suggested_env_lines:
        if line.startswith(f"{_PAIR}_ER_CHOP_ENTER_PCT="):
            enter = float(line.split("=")[1])
        if line.startswith(f"{_PAIR}_ER_CHOP_EXIT_PCT="):
            exit_ = float(line.split("=")[1])
    assert exit_ >= enter


def test_current_mode_with_regime(monkeypatch) -> None:
    monkeypatch.setattr(optimizer.db, "load_ohlc_data", lambda _p, _tf: _make_df())
    monkeypatch.setattr(
        optimizer,
        "TRADING_PARAMS",
        {_PAIR: {"buy": {"K_ACT": None, "MIN_MARGIN": 0.005}, "sell": {"K_ACT": None, "MIN_MARGIN": 0.005}}},
    )
    monkeypatch.setattr(optimizer, "STOP_PERCENTILES", {_PAIR: dict.fromkeys(_LEVELS, 0.9)})

    result = run_optimize(
        OptimizerRequest(
            pair=_PAIR,
            mode="CURRENT",
            current_params=CurrentParams(
                regime=RegimeParams(er_window=24, chop_enter_pct=0.30, chop_dead_band=0.10, trend_pct=0.70)
            ),
        ),
        calibration=None,
    )

    assert result.n_trials_run == 1
    best = result.top_candidates[0]
    assert best["er_window"] == 24
    assert best["chop_enter_pct"] == 0.30
    assert best["chop_dead_band"] == 0.10
    assert best["trend_pct"] == 0.70
