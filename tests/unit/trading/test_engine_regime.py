"""Tests for the optional ER regime gate in simulate_operations.

The most important test here is test_disabled_is_identical: with the default
(disabled) RegimePolicy the engine must behave exactly as it did before the
feature existed, so live trading and every prior backtest/optimizer result are
unchanged when the filter is off.
"""

import numpy as np
import pandas as pd

import trading.engine as engine
from trading.engine import REGIME_CHOP


def _df_from_close(close: list[float], atr: float = 1.0) -> pd.DataFrame:
    """OHLC frame where high/low straddle close by a fixed band, so activation
    crosses are reachable. ATR constant."""
    return pd.DataFrame(
        {
            "dtime": [f"t{i}" for i in range(len(close))],
            "high": [c + 1.0 for c in close],
            "low": [c - 1.0 for c in close],
            "close": close,
            "atr": [atr] * len(close),
        }
    )


_LEVELS = ("LL", "LV", "MV", "HV", "HH")


def _cfg(regime: engine.RegimePolicy | None = None) -> engine.EngineConfig:
    kwargs = {} if regime is None else {"regime": regime}
    return engine.EngineConfig(
        pair="T",
        calibration=engine.PairCalibration(
            atr_p20=1.0,
            atr_p50=3.0,
            atr_p80=5.0,
            atr_p95=7.0,
            k_stop_buy=dict.fromkeys(_LEVELS, 1.0),
            k_stop_sell=dict.fromkeys(_LEVELS, 1.0),
        ),
        buy=engine.SidePolicy(k_act=0.0, min_margin=0.0),
        sell=engine.SidePolicy(k_act=0.0, min_margin=0.0),
        atr_desv_limit=0.2,
        **kwargs,
    )


def _trending_close(n: int = 60) -> list[float]:
    # Smoothly rising then falling => clear directional moves (low ER == not chop
    # only where it reverses); enough structure to open/close positions.
    up = [100.0 + i for i in range(n // 2)]
    down = [up[-1] - i for i in range(1, n // 2 + 1)]
    return up + down


def test_disabled_is_identical() -> None:
    """Default (disabled) RegimePolicy => byte-identical operations to a config
    built with no regime argument at all."""
    close = _trending_close()
    df = _df_from_close(close)

    ops_no_arg = engine.simulate_operations(df, _cfg(), fee_rate=0.001)
    ops_explicit_disabled = engine.simulate_operations(df, _cfg(engine.RegimePolicy(enabled=False)), fee_rate=0.001)

    assert ops_no_arg == ops_explicit_disabled
    assert len(ops_no_arg) > 1  # the fixture actually trades, so the test has teeth


def _trend_then_chop_close() -> list[float]:
    """An efficient (trending) span followed by an inefficient (noisy) span, so
    the ER distribution spans a real range and the percentile cut separates the
    two — unlike a uniform oscillation, where every ER is equal and nothing falls
    below its own percentile."""
    rng = np.random.default_rng(0)
    trend = 100.0 + np.cumsum(rng.normal(1.2, 0.4, 45))  # strong drift => high ER
    chop = trend[-1] + np.cumsum(rng.normal(0.0, 1.5, 45))  # zero drift => low ER
    return [float(x) for x in np.concatenate([trend, chop])]


def test_chop_blocks_activation() -> None:
    """A choppy span gates activation: the gated run produces strictly fewer
    operations than the same data ungated."""
    df = _df_from_close(_trend_then_chop_close())

    ungated = engine.simulate_operations(df, _cfg(), fee_rate=0.0)
    gated = engine.simulate_operations(
        df,
        _cfg(engine.RegimePolicy(enabled=True, er_window=8, chop_enter_pct=0.4, chop_exit_pct=0.5, trend_pct=0.9)),
        fee_rate=0.0,
    )

    assert len(ungated) > 1  # the fixture actually trades ungated
    assert len(gated) < len(ungated)  # the chop span suppresses some trades


def test_active_position_unaffected_by_regime() -> None:
    """Once a position is active it trails/exits regardless of regime: forcing
    'always CHOP' must not stop an already-open position from exiting."""
    df = _df_from_close(_trending_close())

    # chop_enter_pct=1.0 => every bar with a finite ER below the max is CHOP.
    always_chop = engine.RegimePolicy(enabled=True, er_window=4, chop_enter_pct=1.0, chop_exit_pct=1.0, trend_pct=1.0)
    ops = engine.simulate_operations(df, _cfg(always_chop), fee_rate=0.0)

    # The bootstrap BUY is never gated; with k_act=0 a position activates during
    # the NaN warmup (before any CHOP label applies) and then trails to an exit,
    # proving the gate never touches an already-active position.
    assert len(ops) > 1
    assert ops[0].side == "buy"
    assert any(op.pnl_abs is not None and op.idx > 1 for op in ops)  # at least one exit happened


def test_no_close_column_skips_gate() -> None:
    """If the frame has no close column, the gate is inert (treated as ungated)
    rather than raising."""
    df = pd.DataFrame(
        {
            "dtime": ["t0", "t1", "t2"],
            "high": [101.0, 111.0, 121.0],
            "low": [99.0, 109.0, 119.0],
            "atr": [1.0, 1.0, 1.0],
        }
    )
    cfg = _cfg(engine.RegimePolicy(enabled=True))
    ops = engine.simulate_operations(df, cfg, fee_rate=0.0)
    assert isinstance(ops, list)


def test_regime_arr_alignment_with_skipped_atr_rows() -> None:
    """Rows with non-positive/NaN ATR are skipped in the loop but still occupy a
    df position; the regime lookup must stay aligned (no IndexError, sane label)."""
    close = _trending_close(40)
    df = _df_from_close(close)
    df.loc[5, "atr"] = 0.0  # a skipped row mid-series
    df.loc[10, "atr"] = np.nan
    cfg = _cfg(engine.RegimePolicy(enabled=True, er_window=4))
    ops = engine.simulate_operations(df, cfg, fee_rate=0.0)
    assert isinstance(ops, list)  # alignment held, no IndexError


def test_regime_constants_exported() -> None:
    assert REGIME_CHOP == "CHOP"
