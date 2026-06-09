"""Unit tests for the pure Efficiency Ratio regime helpers in trading.engine.

These functions are leaf-pure (no globals, no I/O): the canonical implementation
lives in engine.py and trading.market_analyzer re-exports it (Part 2).
"""

import numpy as np

import trading.engine as engine
from trading.engine import REGIME_CHOP, REGIME_MIXED, REGIME_TREND

# --- efficiency_ratio ------------------------------------------------------


def test_efficiency_ratio_perfect_trend() -> None:
    # Monotonic rise: net change equals total path => ER == 1.0 for every full window.
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    er = engine.efficiency_ratio(close, window=4)
    assert np.isnan(er[:4]).all()
    assert er[4] == 1.0


def test_efficiency_ratio_pure_chop() -> None:
    # Ends where it started after wandering => net 0 => ER 0.0.
    close = np.array([100.0, 102.0, 101.0, 103.0, 100.0])
    er = engine.efficiency_ratio(close, window=4)
    # path = 2 + 1 + 2 + 3 = 8, net = 0 => ER 0.0
    assert er[4] == 0.0


def test_efficiency_ratio_partial_efficiency() -> None:
    close = np.array([100.0, 101.0, 100.0, 101.0, 102.0])
    er = engine.efficiency_ratio(close, window=4)
    # net = |102 - 100| = 2 ; path = 1 + 1 + 1 + 1 = 4 => 0.5
    assert er[4] == 0.5


def test_efficiency_ratio_nan_warmup_and_flat_window() -> None:
    close = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    er = engine.efficiency_ratio(close, window=4)
    assert np.isnan(er[:4]).all()
    # flat window => zero path => NaN (not a divide-by-zero)
    assert np.isnan(er[4])


def test_efficiency_ratio_window_too_large() -> None:
    close = np.array([100.0, 101.0, 102.0])
    er = engine.efficiency_ratio(close, window=5)
    assert er.size == 3
    assert np.isnan(er).all()


# --- resolve_er_thresholds -------------------------------------------------


def test_resolve_thresholds_ordering() -> None:
    er = np.array([np.nan, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    enter, exit_, trend = engine.resolve_er_thresholds(er, 0.33, 0.40, 0.66)
    assert enter <= exit_ <= trend


def test_resolve_thresholds_all_nan_is_degenerate() -> None:
    er = np.full(5, np.nan)
    enter, exit_, trend = engine.resolve_er_thresholds(er, 0.33, 0.40, 0.66)
    assert (enter, exit_, trend) == (0.0, 0.0, 1.0)


# --- classify_regime (hysteresis) ------------------------------------------

# Fixed thresholds for the classifier tests: enter=0.30, exit=0.40, trend=0.66.
_ENTER, _EXIT, _TREND = 0.30, 0.40, 0.66


def _classify(er: float, prev: str | None) -> str:
    return engine.classify_regime(er, _ENTER, _EXIT, _TREND, prev)


def test_classify_enters_chop_below_enter() -> None:
    assert _classify(0.20, prev=REGIME_MIXED) == REGIME_CHOP


def test_classify_holds_chop_within_dead_band() -> None:
    # Between enter (0.30) and exit (0.40): if already CHOP, stays CHOP.
    assert _classify(0.35, prev=REGIME_CHOP) == REGIME_CHOP
    # ...but a non-CHOP prev does NOT enter CHOP in the dead band.
    assert _classify(0.35, prev=REGIME_MIXED) == REGIME_MIXED


def test_classify_leaves_chop_above_exit() -> None:
    assert _classify(0.45, prev=REGIME_CHOP) == REGIME_MIXED
    assert _classify(0.70, prev=REGIME_CHOP) == REGIME_TREND


def test_classify_no_flicker_inside_dead_band() -> None:
    # An ER series oscillating inside [enter, exit] keeps a single stable label.
    prev = REGIME_MIXED
    labels = []
    for er in (0.20, 0.35, 0.32, 0.38, 0.31):  # first dips below enter, then stays in band
        prev = _classify(er, prev)
        labels.append(prev)
    # Enters CHOP on the first bar and never flickers out within the band.
    assert labels == [REGIME_CHOP] * 5


def test_classify_trend_and_mixed_split() -> None:
    assert _classify(0.80, prev=REGIME_MIXED) == REGIME_TREND
    assert _classify(0.50, prev=REGIME_MIXED) == REGIME_MIXED


def test_classify_nan_or_none_holds_prev() -> None:
    assert _classify(float("nan"), prev=REGIME_TREND) == REGIME_TREND
    assert engine.classify_regime(None, _ENTER, _EXIT, _TREND, None) == REGIME_MIXED
