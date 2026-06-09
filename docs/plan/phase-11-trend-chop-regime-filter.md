# Phase 11 – Strategy Refinement: Trend/Chop Regime Filter (Efficiency Ratio)

## Context

- Branch: `feature/phase-11-trend-chop-regime-filter` (created from `main`).
- Prior phases delivered: Docker (1), APScheduler (2), pytest (3), PostgreSQL + Alembic (4), FastAPI + Telegram split (5), `ruff` (6), CI/CD (7), Grafana (8), docs/portfolio (9), Backtest + Optimizer as API endpoints (10, incl. 10.1 concurrent jobs).
- **What this phase adds.** The current ATR-based volatility ladder (LL→HH) measures move *magnitude* but not move *efficiency*: a low-vol trend and a low-vol chop get the same `K_STOP` and are traded identically. Trailing-stop strategies bleed in sideways markets — each false-reversal re-entry is clipped by fees + slippage. This phase adds an **Efficiency Ratio (ER)** regime classifier that labels each pair `TREND` / `MIXED` / `CHOP`, surfaces it (Stage A), and gates new entries during `CHOP` (Stage B). The trailing-stop exit logic is untouched.
- **Validation-first phasing (de-risk before building).** Stage A (observe) and Stage B (enforce) are separable, but the more important split is this: the cheap go/no-go experiment — *does gating CHOP actually improve `robust_pnl`?* — can be run with **only the pure ER math + the offline engine gate + the optimizer flag**, before any live wiring (scheduler, API, Telegram, enforcement). So the plan is split into **Part 1 (validation spike)** and **Part 2 (build-out)** with an explicit **go/no-go gate** between them: if Part 1 shows no better/more-stable result, the feature is discarded (or parked for more data) having touched only offline code and **zero live-trading paths**. Enforcement still ships **off by default** (`TRADE_ON_CHOP=false`) in Part 2. See [Build phases & execution order](#build-phases--execution-order-validation-first) and [Open decisions & risks](#open-decisions--risks).

### Why the Efficiency Ratio (and not the Choppiness Index)

The roadmap's own framing — *magnitude vs. efficiency* — points straight at Kaufman's Efficiency Ratio, which **is** the move-efficiency measure:

```
ER(N) = |close[t] − close[t−N]|  /  Σ |close[i] − close[i−1]|   for i in (t−N, t]
```

- Bounded in `[0, 1]`: `→1` = clean trend (net change ≈ path length), `→0` = pure chop (price thrashed and ended where it started).
- Volatility-normalized by construction (the same volatility appears in numerator and denominator and largely cancels), so it is **orthogonal to the ATR ladder** — exactly the new information we want next to LL→HH.
- One parameter (`N`), no magic constants, interpretable `[0,1]` output. The Choppiness Index gets at the same idea via a double-log transform of summed-TR-over-range with conventional Fibonacci thresholds — works, but harder to explain, test, and defend in a portfolio review. We pick ER for **legibility**; CI is recorded as the considered alternative (see CLAUDE.md Design choices, added in Step 8).

### Files to read before starting

- `ROADMAP.md` — Phase 11 scope (Stage A / Stage B / calibration & docs).
- `trading/market_analyzer.py` — the ATR pipeline; `analyze_structural_noise`, `get_current_atr`. ER helpers land here. Note: `get_volatility_level` lives in `parameters_manager.py`, not here.
- `trading/parameters_manager.py` — `calculate_trading_parameters` (calibration + cache dual-write at the end), `get_volatility_level`, `get_k_stop`. ER threshold calibration is dual-written here.
- `trading/engine.py` — pure leaf simulator. `EngineConfig`, `SidePolicy`, `PairCalibration`, `simulate_operations`, the `if not active:` activation block (lines ~210–240). The regime gate is added here.
- `trading/positions_manager.py` — `create_position` (line 11), `tick_position` (line 152), activation cross (lines ~177–182). Live enforcement is added here.
- `trading/optimizer/search.py` — `OptimizerRequest`, `Candidate`, `_suggest_kact` / `_suggest_minmargin`, `_build_engine_config`, `_evaluate`, `EvalContext`, `_candidate_from_env`, `_candidate_from_params`, `_format_env_lines`. The `regime_enabled` flag + regime search dims are added here.
- `core/runtime.py` — `_shared_data`, `update_pair_data` (already has a `volatility_level` slot), `get_pair_data`, `update_pair_calibration` / `get_pair_calibration`. The live regime label + ER thresholds live here. **Fix the stale line-19 comment** ("Phase 11 extends … window_days / window_sweep") — that referred to the *old* Phase 11 (auto-lookback, now the ROADMAP appendix).
- `core/scheduler.py` — `trading_session()` per-pair loop; the regime is computed here each tick (Stage A) and passed into `create_position` / `tick_position` (Stage B).
- `core/config.py` — how `PAIRS` / `TRADING_PARAMS` / `STOP_PERCENTILES` / `MARKET_ANALYZER` are built from env. New ER vars + per-pair `TRADE_ON_CHOP` are parsed here.
- `api/schemas.py`, `api/routes/market.py`, `api/routes/optimizer.py` — response models + market route.
- `services/telegram/` — the `/market` command handler (display the regime label).
- `docs/trading-strategy.md`, `docs/configuration.md` — the strategy + config references extended in Step 8.

### Architectural decisions

- **ER over CI** — legibility (see above).
- **Three labels, one load-bearing boundary.** ER is a continuous `[0,1]` value; `TREND` / `MIXED` / `CHOP` are buckets on top. Enforcement is `regime != CHOP`, so **only the CHOP boundary gates capital** and needs principled calibration. The TREND/MIXED split is display-only (a hard split at a single percentile); the CHOP boundary carries a hysteresis dead band. This keeps the number of calibration-critical thresholds at **one**.
- **Per-pair percentile calibration, not absolute thresholds.** ER's distribution shifts with `N`, asset, and timeframe, so a borrowed daily-bar absolute (e.g. "0.3 = chop") is meaningless on 15-min crypto. Thresholds are percentiles of each pair's own ER history (matching the `PAIR_STOP_PCT_*` style). Starting prior: terciles — CHOP enter at `P33`, CHOP exit at `P40` (dead band), TREND at `P66`. These drift as history grows and are tuned by the optimizer (Step 7).
- **Hysteresis on the CHOP boundary.** Enter CHOP when `ER < er_chop_enter` (value at `P33`); leave CHOP only when `ER > er_chop_exit` (value at `P40`). The dead band `P33→P40` prevents flicker at the boundary.
- **The CHOP gate blocks both creation and activation; active positions are untouched.** While `regime == CHOP`, `create_position` does not create and `tick_position` does not activate an inactive position. A position that is **already active** keeps trailing and exits only via its stop, across any number of regime flips — this preserves the invariant "the trailing stop is the only exit mechanism." The gate is **entry-side only** and is therefore *not* a panic kill switch.
- **Calibration is periodic + cached; the per-tick check is cheap.** Like `K_STOP`, the heavy work (computing the ER series over history and resolving the percentile thresholds to ER **values**) runs in `calculate_trading_parameters` every `PARAM_SESSIONS` and is dual-written to the calibration cache. The per-tick regime check just computes the *current* ER over the last `N+1` closes and compares to the cached threshold values with hysteresis state held in `core/runtime`.
- **The engine resolves thresholds from its own dataframe (recompute philosophy).** `RegimePolicy` carries **percentiles + window**, never resolved values. `simulate_operations` computes the ER series over its `df` and resolves the percentile thresholds against that distribution. This makes the optimizer sweep self-consistent per `N` (each candidate `N` gets thresholds from its own ER distribution) and mirrors the Phase-10 cache-vs-recompute split (live = cached values, engine = recompute from the working frame).
- **Validation = Optuna search + an `regime_enabled` flag (Option B+flag).** Regime parameters (`er_window`, `chop_enter_pct`) become **conditional** Optuna search dimensions, gated by a request-level `regime_enabled` flag. Run the optimizer twice — flag off, flag on — and compare `robust_pnl`: best-gated vs. best-ungated. This answers the *deploy-relevant* question ("is the best system I can build with a filter better than without?"). The one `regime_enabled` flag does **triple duty**: (1) toggles the regime search dims, (2) toggles the engine gate in `simulate_operations`, (3) is the simulation analog of the live per-pair `TRADE_ON_CHOP`. *Caveat:* best-vs-best mixes the filter's effect with re-tuned stops; it is not the marginal "all else equal" effect. The marginal single-point check is available cheaply via `mode=CURRENT` + the flag. See [Open decisions & risks](#open-decisions--risks).

## Target outcome

```
Calibration (periodic, every PARAM_SESSIONS — parameters_manager.calculate_trading_parameters)
   df(history) ─► efficiency_ratio(close, N) ─► ER series
                                                 ├─ resolve P33/P40/P66 ► er_chop_enter / er_chop_exit / er_trend (VALUES)
                                                 └─ runtime.update_pair_regime_calibration(...)   (cached)

Live tick (core/scheduler.trading_session, per pair — runs even when TRADING_ENABLED=false)
   last N+1 closes ─► current ER ─► classify_regime(er, cached thresholds, prev) ─► label
        ├─ runtime.update_pair_data(pair, trend_regime=label)        (Stage A: API + Telegram read this)
        ├─ log transition (info) when label changes
        └─ pass label into create_position / tick_position           (Stage B gate, regime != CHOP or TRADE_ON_CHOP)

Engine (trading/engine.simulate_operations — backtest + optimizer)
   df ─► ER series + thresholds (from RegimePolicy percentiles)
       └─ per bar: track regime (hysteresis); if enabled and CHOP → skip activation   (gated run)
          RegimePolicy.enabled=False ⇒ byte-identical to the pre-Phase-11 engine      (ungated run)

Optimizer (trading/optimizer/search.py)
   OptimizerRequest.regime_enabled ─► conditional search dims (er_window, chop_enter_pct)
       run flag=off ► best ungated robust_pnl
       run flag=on  ► best gated   robust_pnl     →  compare to decide go/no-go + thresholds
```

After this phase:

- `GET /market` and the Telegram `/market` command show a per-pair `trend_regime` label (and current ER).
- Regime transitions are logged (info), smoothed by the CHOP dead band (no flicker within `P33→P40`).
- With `TRADE_ON_CHOP=false` (default) for a pair, no new position is created or activated while that pair is `CHOP`; already-active positions tick and exit unchanged across regime flips.
- `POST /optimizer/jobs` accepts `regime_enabled`; running it off vs. on yields the best-ungated and best-gated configs for a head-to-head `robust_pnl` comparison, with regime lines included in `suggested_env_lines` when tuned.
- With `regime_enabled=false` everywhere (the default), **live trading behavior and every existing backtest/optimizer result are byte-for-byte unchanged**.

---

## Step 0 — Dependencies

**None.** ER is `numpy` arithmetic over the `close` column already present in `ohlc_data`; the hysteresis classifier is pure Python. No new pinned dependency, no image rebuild required for deps. (Confirm `requirements.txt` is untouched in the PR.)

---

## Step 1 — ER computation + regime classification

> **Steps below are numbered by subsystem, not by execution order.** The actual build order is in [Build phases & execution order](#build-phases--execution-order-validation-first): Part 1 = Steps 1 + 5 + 7 (offline spike), then the go/no-go gate, then Part 2 = Steps 2, 3, 4, 6, 8.

The canonical implementation of the three pure helpers lives in **`trading/engine.py`** (a leaf module — no `core.config` import, so it is safe for the engine to own them). `trading/market_analyzer.py` re-exports/delegates to them in **Part 2** when the live path needs them; for the Part 1 spike, only the engine copy is required. They read no globals and make no DB/Kraken calls — unit-testable in isolation.

### 1.1 `efficiency_ratio`

```python
def efficiency_ratio(close: np.ndarray, window: int) -> np.ndarray:
    """Kaufman Efficiency Ratio over a rolling window.

    ER[i] = |close[i] - close[i-N]| / sum(|close[j] - close[j-1]|, j in (i-N, i]).
    Returns an array aligned to `close`; the first `window` entries are NaN
    (insufficient lookback). Bars where the denominator is 0 (flat window) are
    NaN — treated as non-CHOP (no gating) by the classifier.
    """
    close = np.asarray(close, dtype=float)
    n = close.size
    er = np.full(n, np.nan, dtype=float)
    if window < 1 or n <= window:
        return er
    abs_steps = np.abs(np.diff(close))                  # path length per bar
    for i in range(window, n):
        net = abs(close[i] - close[i - window])
        path = float(abs_steps[i - window:i].sum())
        er[i] = (net / path) if path > 0 else np.nan
    return er
```

(A vectorized cumulative-sum form is fine too; the loop is shown for clarity and is plenty fast at our row counts. Keep whichever the equivalence test confirms.)

### 1.2 `resolve_er_thresholds`

```python
REGIME_TREND = "TREND"
REGIME_MIXED = "MIXED"
REGIME_CHOP = "CHOP"

def resolve_er_thresholds(
    er: np.ndarray, chop_enter_pct: float, chop_exit_pct: float, trend_pct: float
) -> tuple[float, float, float]:
    """Resolve percentile cut-points to ER *values* over the ER distribution.
    Returns (er_chop_enter, er_chop_exit, er_trend). chop_exit_pct >= chop_enter_pct
    so the exit value sits above the enter value (the hysteresis dead band)."""
    valid = er[~np.isnan(er)]
    if valid.size == 0:
        return (0.0, 0.0, 1.0)  # degenerate: never CHOP, never TREND
    enter = float(np.percentile(valid, chop_enter_pct * 100))
    exit_ = float(np.percentile(valid, chop_exit_pct * 100))
    trend = float(np.percentile(valid, trend_pct * 100))
    return enter, exit_, trend
```

### 1.3 `classify_regime` (hysteresis)

```python
def classify_regime(
    er_value: float | None,
    er_chop_enter: float,
    er_chop_exit: float,
    er_trend: float,
    prev_regime: str | None,
) -> str:
    """Map a single ER value to TREND/MIXED/CHOP with hysteresis on the CHOP
    boundary. While in CHOP, stay until ER rises above er_chop_exit (dead band).
    The TREND boundary is a hard split (display-only, not load-bearing)."""
    if er_value is None or np.isnan(er_value):
        return prev_regime or REGIME_MIXED        # insufficient data: hold/neutral
    if prev_regime == REGIME_CHOP:
        if er_value <= er_chop_exit:
            return REGIME_CHOP                     # still choppy (within dead band)
    elif er_value < er_chop_enter:
        return REGIME_CHOP                         # entering chop
    if er_value >= er_trend:
        return REGIME_TREND
    return REGIME_MIXED
```

### 1.4 Tests — `tests/unit/trading/test_efficiency_ratio.py`

- `test_efficiency_ratio_perfect_trend` — monotonically rising closes ⇒ ER ≈ 1.0.
- `test_efficiency_ratio_pure_chop` — `[100,102,101,103,100]`, `window=4` ⇒ net 0 ⇒ ER 0.0.
- `test_efficiency_ratio_nan_warmup` — first `window` entries are NaN; flat window ⇒ NaN.
- `test_resolve_thresholds_ordering` — enter ≤ exit ≤ trend for terciles on a known distribution.
- `test_classify_enter_and_hold_chop` — ER below enter ⇒ CHOP; next bar between enter and exit ⇒ **stays** CHOP (dead band); above exit ⇒ leaves CHOP.
- `test_classify_no_flicker` — an ER series oscillating inside `[enter, exit]` yields a single CHOP→…→ stable label (no per-bar flip).
- `test_classify_trend_mixed_split` — ER above trend ⇒ TREND; between exit and trend ⇒ MIXED.
- `test_classify_nan_holds_prev` — `None`/NaN ER returns `prev_regime` (or MIXED when prev is None).

**Commit:** `feat(market-analyzer): efficiency ratio + hysteresis regime classifier`.

---

## Step 2 — Config + ER threshold calibration (`core/config.py`, `parameters_manager.py`, `core/runtime.py`)

### 2.1 Config vars (`core/config.py`)

Add ER parameters (global defaults, per-pair override optional, following the existing pattern) and the per-pair enforcement flag:

| Env var | Default | Meaning |
|---|---|---|
| `ER_WINDOW` | `32` | ER lookback in candles (≈8h on 15-min). |
| `ER_CHOP_ENTER_PCT` | `0.33` | Percentile of ER below which a pair enters CHOP. |
| `ER_CHOP_EXIT_PCT` | `0.40` | Percentile above which a pair leaves CHOP (≥ enter; the dead band). |
| `ER_TREND_PCT` | `0.66` | Percentile above which a pair is TREND (display-only). |
| `PAIR_TRADE_ON_CHOP` | `false` | Per pair: when `true`, the CHOP gate is disabled for that pair (entries allowed during chop). Parsed into `TRADING_PARAMS[pair]` like the other per-pair flags. |

Validate `0 ≤ ER_CHOP_ENTER_PCT ≤ ER_CHOP_EXIT_PCT ≤ ER_TREND_PCT ≤ 1` and `ER_WINDOW ≥ 2` at load (fail fast, matching how other config invariants are checked).

> **No master `regime_enabled` live switch.** Per the "entry-side only, default off" stance, the live gate is controlled **per pair** by `TRADE_ON_CHOP` (default `false` = gate active once thresholds exist). The optimizer's `regime_enabled` is a *request* field, not an env var. Stage A (observation/labelling) always runs; only the Stage-B gate is per-pair-toggleable.

### 2.2 Extend the calibration cache (`core/runtime.py`)

Add ER threshold fields to the existing `pair_calibration` entry (one cache, one `computed_at`). Two clean options — pick the one that reads best against the current code:

- **(a)** add optional kwargs to `update_pair_calibration` (`er_window`, `er_chop_enter`, `er_chop_exit`, `er_trend`), or
- **(b)** add a sibling setter `update_pair_regime_calibration(pair, er_window, er_chop_enter, er_chop_exit, er_trend)` that merges into the same dict.

Either way `get_pair_calibration` returns the ER threshold values alongside the ATR/event data. **Delete the stale line-19 comment** about `window_days` / `window_sweep` and replace it with the ER fields actually stored.

### 2.3 Dual-write ER thresholds from `calculate_trading_parameters`

`calculate_trading_parameters` already loads `df`, computes ATR percentiles + events, and dual-writes the calibration cache at the end (`parameters_manager.py:82-91`). Add — purely additively, no change to the existing K_STOP logic — the ER threshold computation and include it in the cache write:

```python
from core.config import ER_WINDOW, ER_CHOP_ENTER_PCT, ER_CHOP_EXIT_PCT, ER_TREND_PCT
from trading.market_analyzer import efficiency_ratio, resolve_er_thresholds

# after the existing K_STOP block, before/with the runtime.update_pair_calibration call:
er = efficiency_ratio(df["close"].to_numpy(dtype=float), ER_WINDOW)
er_chop_enter, er_chop_exit, er_trend = resolve_er_thresholds(
    er, ER_CHOP_ENTER_PCT, ER_CHOP_EXIT_PCT, ER_TREND_PCT
)
# ... pass er_window=ER_WINDOW + the three values into the cache write (Step 2.2).
```

Live behavior is unchanged: this only *adds* cached values; nothing reads them until Step 3 wires the scheduler and Step 6 wires enforcement.

### 2.4 Tests — `tests/unit/trading/test_parameters_manager_regime.py`

- `test_calc_params_populates_er_thresholds` — monkeypatch `db.load_ohlc_data` to a synthetic frame; call `calculate_trading_parameters`; assert the cache has `er_window` + three ordered thresholds.
- `test_calc_params_er_thresholds_ordered` — enter ≤ exit ≤ trend.
- `test_config_rejects_bad_er_pcts` — out-of-order percentiles or `ER_WINDOW < 2` raise at config load.

**Commit:** `feat(config,runtime): ER regime thresholds in config + calibration cache`.

---

## Step 3 — Live regime tracking (`core/runtime.py`, `core/scheduler.py`) — Stage A core

### 3.1 Runtime regime slot

`update_pair_data` already carries a `volatility_level` slot; add a `trend_regime` field the same way (None-guarded optional kwarg), so `get_pair_data(pair)` returns `{"last_price", "atr", "volatility_level", "trend_regime"}`. The **previous** regime needed for hysteresis is just the currently-stored `trend_regime` (read it before writing the new one).

### 3.2 Compute the regime each tick (scheduler)

In the per-pair loop of `trading_session()`, after market data + params are refreshed and the calibration cache is available, compute the regime:

```python
cal = runtime.get_pair_calibration(pair)
prev = runtime.get_pair_data(pair).get("trend_regime")
regime = prev  # default: hold previous if thresholds not yet calibrated
if cal and "er_chop_enter" in cal:
    closes = db.load_ohlc_data(pair, CANDLE_TIMEFRAME, limit=cal["er_window"] + 1)["close"].to_numpy(float)
    er_series = efficiency_ratio(closes[::-1], cal["er_window"])  # oldest→newest
    er_now = float(er_series[-1]) if er_series.size and not np.isnan(er_series[-1]) else None
    regime = classify_regime(er_now, cal["er_chop_enter"], cal["er_chop_exit"], cal["er_trend"], prev)
    runtime.update_pair_data(pair, trend_regime=regime)
    if regime != prev:
        logging.info(f"[{pair}] 🧭 Regime {prev or '—'} → {regime} (ER={er_now:.3f})")
```

- This block runs **regardless of `TRADING_ENABLED`** (it sits with the always-on market-data/calibration updates, before the position block), so a non-trading replica still observes and logs regimes. Mirrors the existing "ingest OHLC even when disabled" behavior.
- Confirm the load-order: `db.load_ohlc_data(..., limit=N+1)` must return the most recent `N+1` candles; reverse to oldest→newest for `efficiency_ratio` (which walks forward). Match the column/ordering convention already used in `market_analyzer.get_current_atr` / `_latest_db_atr`.

### 3.3 Tests — `tests/unit/core/test_scheduler_regime.py`

- `test_scheduler_sets_regime` — stub calibration cache + OHLC loader; assert `runtime.get_pair_data(pair)["trend_regime"]` is set after a session.
- `test_scheduler_logs_transition_once` — drive two sessions across a CHOP→TREND change; assert the transition is logged on the change tick and not when the label is stable.
- `test_scheduler_holds_regime_without_calibration` — empty cache ⇒ regime stays `prev` (or None), no crash.

**Commit:** `feat(scheduler): compute and publish per-pair trend regime each tick`.

---

## Step 4 — API + Telegram surface (Stage A)

### 4.1 `GET /market` (`api/schemas.py`, `api/routes/market.py`)

Add `trend_regime: str | None` (and optionally `efficiency_ratio: float | None`) to the per-pair market response model, populated from `runtime.get_pair_data(pair)`. Keep it optional/nullable so a cold start (no regime computed yet) serializes cleanly.

### 4.2 Telegram `/market` command (`services/telegram/`)

The Telegram service reads the API; add the regime label to the `/market` formatting (e.g. `XBTEUR  MV  🧭 TREND`). No new endpoint — it consumes the field added in 4.1.

### 4.3 Tests

- `tests/unit/api/test_market_route.py` — extend: assert the response includes `trend_regime` when runtime has it, and `None` when it doesn't.
- Telegram formatting test (if the handler has formatting unit coverage) — assert the regime label appears.

**Commit:** `feat(api,telegram): expose per-pair trend regime in /market`.

---

## Step 5 — Engine regime gate (`trading/engine.py`) — Stage B core / optimizer fuel

### 5.1 `RegimePolicy` + `EngineConfig` field

```python
@dataclass(frozen=True)
class RegimePolicy:
    enabled: bool = False
    er_window: int = 32
    chop_enter_pct: float = 0.33
    chop_exit_pct: float = 0.40
    trend_pct: float = 0.66

@dataclass(frozen=True)
class EngineConfig:
    pair: str
    calibration: PairCalibration
    buy: SidePolicy
    sell: SidePolicy
    atr_desv_limit: float
    regime: RegimePolicy = RegimePolicy()   # default: disabled ⇒ no behavior change
```

The default `RegimePolicy()` has `enabled=False`, so **every existing call site that doesn't pass `regime` keeps the exact current behavior**. `engine.py` stays a leaf module — ER math is inlined here (or imported from `market_analyzer`? No: keep the leaf-purity invariant — `market_analyzer` imports `core.config`, so the engine must **not** import it). Add a private `_efficiency_ratio` + `_resolve_thresholds` in `engine.py` mirroring Step 1, or factor the two pure functions into a tiny dependency-free helper module both import. **Recommended:** put the pure ER math in `engine.py` (it's leaf-safe) and have `market_analyzer.efficiency_ratio` re-export/delegate, so there is a single implementation and the leaf invariant holds. Confirm direction during implementation; the equivalence test (5.4) guards correctness either way.

### 5.2 Gate inside `simulate_operations`

When `cfg.regime.enabled`, precompute once (before the main loop), aligned to `df` rows:

```python
regime_arr = None
if cfg.regime.enabled:
    closes = df["close"].to_numpy(dtype=float)   # engine df always has close in practice
    er = _efficiency_ratio(closes, cfg.regime.er_window)
    enter, exit_, trend = _resolve_thresholds(er, cfg.regime.chop_enter_pct,
                                              cfg.regime.chop_exit_pct, cfg.regime.trend_pct)
    regime_arr = []
    prev = None
    for v in er:
        prev = _classify(v, enter, exit_, trend, prev)
        regime_arr.append(prev)
```

Then enumerate the main loop (`for i, (_, row) in enumerate(df.iterrows())`) and, **in the `if not active:` block, after the re-anchor and before the activation cross check**, add the gate:

```python
if cfg.regime.enabled and regime_arr[i] == "CHOP":
    continue   # CHOP: do not activate (and nothing is committed while inactive)
```

- This is the engine analog of "block creation **and** activation during CHOP": while inactive, the engine commits no capital, so skipping the activation cross is the meaningful gate. The activation target still tracks (re-anchor/recalibration above the gate keeps running) but never *fires* during CHOP.
- The **bootstrap BUY** (first valid close, `engine.py:167`) is a price-reference anchor, not a trade entry — leave it unmodified. The gate applies only to activations.
- **Active positions are untouched:** the `if not active:` block is skipped once `active` is `True`, so an open position trails and exits across any regime value exactly as today.

### 5.3 Leaf invariant + purity

`simulate_operations` stays pure and globals-free; `RegimePolicy` is config-as-argument like everything else.

### 5.4 Tests — `tests/unit/trading/test_engine_regime.py`

- **`test_disabled_is_identical`** *(critical regression)* — run `simulate_operations` on a fixture with `RegimePolicy()` (disabled) and assert the returned `list[Operation]` is **byte-identical** to the same run before this step / with no `regime` field. This guarantees "no behavior change when off." Reuse/extend the Phase-10 golden-output approach.
- `test_chop_blocks_activation` — a fixture with a clearly choppy span where, ungated, a position would activate and trade; assert that with `enabled=True` no activation occurs during the CHOP span and ops are fewer.
- `test_active_position_unaffected_by_chop` — a position that activates in TREND then the regime flips to CHOP mid-trail; assert it still trails and exits via the stop (the gate never touches it).
- `test_engine_hysteresis` — ER oscillating inside the dead band yields a stable CHOP label across the span (no per-bar re-entry flicker).

**Commit:** `feat(engine): optional ER regime gate (RegimePolicy) in simulate_operations`.

---

## Step 6 — Live enforcement (`trading/positions_manager.py`, `core/scheduler.py`) — Stage B

### 6.1 Thread the regime into the position functions

Pass the per-tick regime label (from Step 3) into the position functions as an explicit argument (mirrors how `atr_val` / `current_price` are passed — keeps `positions_manager` decoupled from `runtime`):

- `create_position(..., regime: str | None = None)`
- `tick_position(..., regime: str | None = None)`

### 6.2 Gate creation

In `create_position`, before building the position dict:

```python
if regime == "CHOP" and not _trade_on_chop(pair):
    logging.info(f"[{pair}] ⏸️ CHOP regime — skipping new {side.upper()} position.")
    return None
```

`_trade_on_chop(pair)` reads the per-pair `TRADE_ON_CHOP` flag from `TRADING_PARAMS`. The scheduler's "no active position → create_position" branch then simply creates nothing this tick.

### 6.3 Gate activation

In `tick_position`, at the activation cross (`positions_manager.py:177-182`), do not activate while CHOP:

```python
if (cross condition) and not (regime == "CHOP" and not _trade_on_chop(pair)):
    # activate as today
```

The recalibration + re-anchor above the cross keep running (the inactive position's target tracks), but it does not activate until the regime leaves CHOP. Already-active positions (`trailing_active is True`, line 162) never reach this branch — untouched.

### 6.4 Scheduler wiring

Pass `regime=runtime.get_pair_data(pair).get("trend_regime")` into the `create_position` / `tick_position` calls in `trading_session()`. (The block already runs only when `TRADING_ENABLED`.)

### 6.5 Tests — `tests/unit/trading/test_positions_manager_regime.py`

- `test_create_blocked_in_chop` — `regime="CHOP"`, `TRADE_ON_CHOP` false ⇒ `create_position` returns None / creates nothing.
- `test_create_allowed_in_trend_mixed` — `regime` in {TREND, MIXED} ⇒ creates normally.
- `test_trade_on_chop_bypass` — `regime="CHOP"`, `TRADE_ON_CHOP` true ⇒ creates normally.
- `test_activation_blocked_in_chop` — inactive position + cross + CHOP ⇒ does not activate; same setup in MIXED ⇒ activates.
- `test_active_position_ticks_through_chop` — already-active position + CHOP ⇒ trailing/stop logic runs and can exit (gate not applied).

**Commit:** `feat(positions): gate creation + activation on CHOP regime (TRADE_ON_CHOP per pair)`.

---

## Step 7 — Optimizer integration (`trading/optimizer/search.py`, `api/schemas.py`) — Option B + flag

### 7.1 Request + Candidate fields

`OptimizerRequest` (dataclass in `search.py` **and** the Pydantic model in `api/schemas.py`): add

```python
regime_enabled: bool = False
# regime search bounds (used only when regime_enabled and mode != CURRENT):
er_window_choices: tuple[int, ...] = (16, 24, 32, 48, 64, 96)   # categorical
chop_enter_choices: tuple[float, ...] = (0.25, 0.30, 0.33, 0.40, 0.50)
```

`Candidate` gains `er_window: int | None = None` and `chop_enter_pct: float | None = None` (both `None` ⇒ regime disabled for that candidate). `chop_exit_pct` is derived from `chop_enter_pct` by a fixed dead band (e.g. enter + one step) and `trend_pct` is fixed at the config default — keeping the search at **two** added dimensions, not four.

### 7.2 Suggest + build

Thread `regime_enabled` through `_build_objective` into the suggest functions:

```python
def _suggest_kact(trial, regime_enabled):
    stop_pcts = {lvl: trial.suggest_float(f"stop_pct_{lvl}", 0.20, 0.95, step=0.05) for lvl in LEVELS}
    er_window = chop_enter = None
    if regime_enabled:
        er_window = trial.suggest_categorical("er_window", list(req.er_window_choices))
        chop_enter = trial.suggest_categorical("chop_enter_pct", list(req.chop_enter_choices))
    return Candidate(k_act=trial.suggest_float("k_act", 0.0, 4.0, step=0.5),
                     min_margin=None, stop_pcts=stop_pcts,
                     er_window=er_window, chop_enter_pct=chop_enter)
```

`_build_engine_config` sets `RegimePolicy(enabled=cand.er_window is not None, er_window=..., chop_enter_pct=..., chop_exit_pct=enter+deadband, trend_pct=ER_TREND_PCT)` and passes it into `EngineConfig`. When `regime_enabled=False`, no regime params are suggested, `RegimePolicy` stays disabled, and **the search is identical to today's** (guarded by a test).

`_candidate_from_params` / `_candidate_from_env` / `_candidate_to_dict` / `_format_env_lines` learn the two new optional fields. `_format_env_lines` appends `{pair}_ER_WINDOW=…` and a `{pair}_TRADE_ON_CHOP=true` line only when the winning candidate has regime enabled.

### 7.3 CURRENT baseline & AUTO

`mode=CURRENT` with `regime_enabled=False` evaluates the live `.env` config with the gate off — the true ungated baseline AUTO compares against. The go/no-go workflow is **two AUTO jobs**: one `regime_enabled=False`, one `regime_enabled=True`; compare the winners' `robust_pnl_pct`. (Document this in Step 8; it is the operational meaning of "best gated vs. best ungated".) No change to the convergence/escalation machinery — the flag only widens the per-trial search space.

### 7.4 DB / schema

`regime_enabled` and the regime choices live inside the existing `optimizer_jobs.request` JSONB column — **no migration, no new mode**. The `ck_opt_jobs_mode_valid` constraint (`OPTIMIZE`/`CURRENT`/`AUTO`) is unchanged.

### 7.5 Tests — `tests/unit/trading/test_optimizer_regime.py`

- `test_regime_disabled_matches_baseline` — `regime_enabled=False` reproduces the current search space (no `er_window`/`chop_enter_pct` params suggested); `RegimePolicy` disabled in the built config.
- `test_regime_enabled_expands_search` — small fixture, `n_trials` small, `regime_enabled=True`; assert trials carry `er_window` + `chop_enter_pct` params and no global mutation.
- `test_regime_env_lines` — a regime-enabled winner emits `ER_WINDOW` + `TRADE_ON_CHOP` lines in `suggested_env_lines`.
- `test_current_mode_with_regime` — `mode=CURRENT`, `regime_enabled=True`, fixed `er_window`/`chop_enter_pct` ⇒ one gated evaluation, `n_trials_run == 1`.

**Commit:** `feat(optimizer): regime_enabled flag with conditional ER search dimensions`.

---

## Step 8 — Documentation

- **`docs/trading-strategy.md`** — new section: ER definition + intuition, the three regimes, the single load-bearing CHOP boundary, hysteresis dead band, percentile calibration (and that thresholds drift until frozen), the entry-side gate semantics (active positions untouched), and the **validation workflow** (two AUTO jobs, flag off vs on, compare `robust_pnl`). Record the chosen `N` / percentiles once the optimizer comparison is run, with the derivation.
- **`docs/configuration.md`** — document `ER_WINDOW`, `ER_CHOP_ENTER_PCT`, `ER_CHOP_EXIT_PCT`, `ER_TREND_PCT`, and per-pair `PAIR_TRADE_ON_CHOP` (default, effect).
- **`.env.example`** — add the new vars with defaults and a one-line comment each.
- **`README.md`** — one line in the strategy/architecture section noting the regime filter; the `/optimizer/jobs` doc mentions the `regime_enabled` flag.
- **`ROADMAP.md`** — tick the Phase 11 Stage A / Stage B / calibration boxes; add a short status note that both stages shipped with enforcement off-by-default pending the optimizer comparison.
- **`CLAUDE.md`** — extend the *Volatility classification* / strategy section with the regime filter; add a **Design choices** entry: *"ER over the Choppiness Index (legibility); three labels but a single load-bearing CHOP boundary with hysteresis; the gate is entry-side only and never touches active positions (preserves the trailing-stop-only-exit invariant); validation via `regime_enabled` flag (best-gated vs best-ungated), not a marginal sweep."* Update the *Configuration* section with the new vars and the optimizer section with `regime_enabled`.
- **`CHANGELOG.md`** — an `Added` entry under the V2 milestone.

**Commit:** `docs: document ER trend/chop regime filter (strategy, config, roadmap, CLAUDE)`.

---

## Step 9 — Final verification

Inside Docker:

```
docker compose -f docker-compose.test.yml run --rm test ruff check .
docker compose -f docker-compose.test.yml run --rm test ruff format --check .
docker compose -f docker-compose.test.yml run --rm test pytest tests/unit
docker compose -f docker-compose.test.yml run --rm test pytest tests/integration   # if DB creds present
```

End-to-end smoke against a running stack:

```
docker compose up -d
sleep 90   # let the scheduler run calculate_trading_parameters at least once

# Stage A: regime label is published.
curl -s http://localhost:8000/market -H "X-Api-Token: $API_SECRET_TOKEN" | jq '.[].trend_regime'

# Validation: best ungated vs best gated (run sequentially or on separate pairs).
curl -s -X POST http://localhost:8000/optimizer/jobs -H "X-Api-Token: $API_SECRET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pair":"XBTEUR","mode":"AUTO","regime_enabled":false}' | jq .job_id
curl -s -X POST http://localhost:8000/optimizer/jobs -H "X-Api-Token: $API_SECRET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pair":"XBTEUR","mode":"AUTO","regime_enabled":true}'  | jq .job_id
# Compare robust_pnl_pct of the two winners once both complete.

docker compose down
```

Equivalence guard: confirm `test_disabled_is_identical` (Step 5.4) passes — with `regime_enabled=false` everywhere, live trading, backtests, and prior optimizer results are byte-for-byte unchanged.

---

## Build phases & execution order (validation-first)

The work is split into two parts with a **go/no-go gate** between them. Each bullet is one focused commit; after each, run `pytest tests/unit` and `ruff check .` inside Docker. (The "Step N" references point at the detailed specs above, which are numbered by subsystem, not by this order.)

### Part 1 — Validation spike (offline only; decides go/no-go)

The minimal path to running the gated-vs-ungated experiment. Touches **only** the pure ER math, the offline engine, and the optimizer — no scheduler, no API, no live-trading code. The engine owns the pure ER/threshold/classify functions (leaf module); `market_analyzer` delegation is deferred to Part 2.

1. `feat(engine): pure efficiency ratio + hysteresis classifier (leaf helpers)` — Step 1's three functions, in `engine.py` (+ Step 1.4 tests).
2. `feat(engine): optional ER regime gate (RegimePolicy) in simulate_operations` — Step 5, **including the byte-identical `disabled` equivalence test** (the guard that keeps the default-off path inert).
3. `feat(optimizer): regime_enabled flag with conditional ER search dimensions` — Step 7.

**▶ GO/NO-GO GATE** — run the experiment (Step 9 smoke: two AUTO jobs per pair, `regime_enabled` off vs on; compare `robust_pnl_pct`).
- **No-go** (no improvement, or not more stable across seeds): **stop**. Discard the branch — or park it for the ~60-day data window. Cost spent: 3 offline commits, zero live risk.
- **Go** (gated robustly beats ungated): proceed to Part 2.

### Part 2 — Live integration (only if Part 1 says go)

4. `feat(config,runtime): ER regime thresholds in config + calibration cache` — Step 2.
5. `feat(market-analyzer): re-export ER helpers + live threshold calibration` — Step 1's `market_analyzer` surface delegating to the engine, wired into `calculate_trading_parameters`.
6. `feat(scheduler): compute and publish per-pair trend regime each tick` — Step 3 (Stage A).
7. `feat(api,telegram): expose per-pair trend regime in /market` — Step 4 (Stage A).
8. `feat(positions): gate creation + activation on CHOP regime (TRADE_ON_CHOP per pair)` — Step 6 (Stage B).
9. `docs: document ER trend/chop regime filter (strategy, config, roadmap, CLAUDE)` — Step 8.

Part 1 is releasable on its own as an offline analysis capability even if Part 2 never ships. Within Part 2, Stage A (commits 6–7) is independently releasable before Stage B (commit 8).

---

## Acceptance checklist

**Part 1 (validation spike) — the go/no-go gate.** Before deciding to proceed:
- [ ] `efficiency_ratio` / `resolve_er_thresholds` / `classify_regime` live in `engine.py`, are pure, and pass the Step 1.4 unit tests (NaN warmup, pure-chop = 0, hysteresis no-flicker).
- [ ] `EngineConfig.regime` defaults to a **disabled** `RegimePolicy`; `simulate_operations` with the default is **byte-identical** to the pre-Phase-11 engine (`test_disabled_is_identical` passes).
- [ ] `OptimizerRequest.regime_enabled=False` reproduces the current search exactly; `True` adds the `er_window` + `chop_enter_pct` dimensions with no global mutation.
- [ ] The experiment has been run (two AUTO jobs per pair, off vs on) and the `robust_pnl_pct` comparison recorded — this is the input to the go/no-go decision.

**Part 2 (live integration) — full feature.** Run before opening the build-out PR:

- [ ] `requirements.txt` is unchanged (no new dependency).
- [ ] `trading/market_analyzer.py` exposes `efficiency_ratio`, `resolve_er_thresholds`, `classify_regime`; all pure, no DB/Kraken/global access.
- [ ] `efficiency_ratio` returns NaN for the first `window` bars and for flat (zero-path) windows; `classify_regime` holds the previous label on NaN.
- [ ] CHOP hysteresis works: enter at `<P33`, leave only at `>P40`; an ER series oscillating inside the band produces no label flicker (unit-tested).
- [ ] `core/config.py` parses `ER_WINDOW`, `ER_CHOP_ENTER_PCT`, `ER_CHOP_EXIT_PCT`, `ER_TREND_PCT`, per-pair `TRADE_ON_CHOP`; rejects out-of-order percentiles and `ER_WINDOW < 2`.
- [ ] `calculate_trading_parameters` dual-writes ER thresholds to the calibration cache; its existing K_STOP/ATR logic is unchanged. `core/runtime.py`'s stale line-19 comment is fixed.
- [ ] The scheduler computes + publishes `trend_regime` every tick (even when `TRADING_ENABLED=false`) and logs transitions once per change.
- [ ] `GET /market` and the Telegram `/market` command show the per-pair regime (nullable on cold start).
- [ ] `EngineConfig.regime` defaults to a **disabled** `RegimePolicy`; `simulate_operations` with the default is **byte-identical** to the pre-Phase-11 engine (`test_disabled_is_identical` passes). `engine.py` remains a leaf module (no `core.config` / `market_analyzer` import that would break leaf purity).
- [ ] With the gate enabled, no activation occurs during CHOP; an already-active position trails and exits unchanged across regime flips.
- [ ] `create_position` and `tick_position` accept a `regime` argument; creation **and** activation are blocked during CHOP unless `TRADE_ON_CHOP` is set for the pair; active positions are never gated.
- [ ] `OptimizerRequest` accepts `regime_enabled`; `False` reproduces the current search space exactly (no regime params suggested, `RegimePolicy` disabled); `True` adds `er_window` + `chop_enter_pct` dimensions with no global mutation; regime winners emit `ER_WINDOW` + `TRADE_ON_CHOP` env lines. No DB migration (request JSONB only).
- [ ] `pytest tests/unit` passes at the 80% coverage gate; `ruff check .` and `ruff format --check .` clean.

---

## Non-goals for this phase

Explicitly out of scope — do not add any of these:

- **Any change to the exit logic.** The trailing stop remains the sole exit. The gate is entry-side only.
- **Per-regime stop sizing / different `K_STOP` in CHOP vs TREND.** The regime gates *entries*, it does not re-tune the stop ladder. (Possible future work; record, don't build.)
- **Gating on the ATR volatility level.** Regime (efficiency) and volatility (magnitude) stay orthogonal, separate signals.
- **The Choppiness Index, ADX, or any second regime indicator.** ER only; CI is the documented considered-and-rejected alternative.
- **A live master "regime enforcement" kill switch.** Enforcement is per-pair via `TRADE_ON_CHOP`; there is no global runtime override (that would resemble the forbidden panic switch). `regime_enabled` is an *optimizer request* field, not a live control.
- **Auto-application of optimizer regime results.** The result returns suggested env lines; the operator copies them and redeploys, as with all other tuned params.
- **Co-optimizing regime with stops in a single muddy run as the *only* path.** The `regime_enabled` flag exists precisely so off-vs-on is a clean head-to-head. (Co-optimization still happens *within* the flag-on run; that is intended.)
- **Auto-lookback window for K_STOP calibration.** Still deferred (ROADMAP appendix); unrelated to ER.
- **Freezing the ER thresholds to absolute values.** Thresholds stay percentile-derived and drifting this phase; freezing is a later decision once enough history accrues.

---

## Open decisions & risks

- **Data sufficiency (the deliberate bet).** Stage B is shipping now rather than after a long live-observation window. With limited OHLC history, (a) ER percentile thresholds are not yet stable, and (b) the best-gated-vs-best-ungated optimizer comparison is noisier (two independently-optimized configs). Mitigations: thresholds are percentile-derived and **drift** with history; `robust_pnl = min(train, test)` + AUTO multi-seed convergence reduce overfit; and **`TRADE_ON_CHOP` defaults to `false`** so nothing enforces in production until a deliberate per-pair flip backed by the comparison. Re-run the comparison and revisit chosen thresholds once ~60+ days of OHLC are available (ties into the parked optimizer-robustness work).
- **Best-vs-best, not marginal.** The `regime_enabled` flag answers "is my best gated system better than my best ungated system" — the deploy-relevant question — but it attributes the delta to *filter + re-tuned stops together*, not the filter alone. If a clean marginal read is wanted, run `mode=CURRENT` with the flag on vs off (single point), or sweep `CURRENT`+flag over a small `(N, chop_pct)` grid from the client.
- **Engine ER implementation location.** Step 5 must keep `engine.py` a leaf module. Confirm during implementation whether the pure ER/threshold/classify functions live in `engine.py` (with `market_analyzer` delegating) or in a new dependency-free helper both import. The `test_disabled_is_identical` + classifier unit tests guard correctness regardless.
- **`load_ohlc_data` ordering in the live regime tick.** Verify the `limit=N+1` slice returns the most recent candles and reverse to oldest→newest before `efficiency_ratio`; match the convention in `market_analyzer.get_current_atr`.
