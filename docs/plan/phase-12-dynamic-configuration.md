# Phase 12 – Dynamic Pair Configuration: Runtime Overrides via DB, API & Telegram

> **Status:** Planned. This phase makes the per-pair trading parameters (`TARGET_PCT`, `HODL_PCT`, `K_ACT`, `MIN_MARGIN`, and the `STOP_PCT_<level>` volatility stops) editable at runtime — through the REST API and Telegram — with changes taking effect automatically, no restart and no redeploy. Overrides live in the existing `bot_control` table and are materialised into the in-memory config dicts the trading loop already reads.

## Context

- Branch: `feature/phase-12-dynamic-configuration` (to be created from `main`).
- **Current state.** All per-pair settings are read from `.env` by `core/config.py` at import time into three module-level dicts — `TRADING_PARAMS`, `ASSET_ALLOCATION`, `STOP_PERCENTILES` — and normalised in place from raw strings to typed floats by `core/validation.py:validate_pair_params` during startup. Every consumer reads them by plain dict access:
  - `trading/positions_manager.py:48,56` → `TRADING_PARAMS[pair][side]["K_ACT" | "MIN_MARGIN"]`
  - `trading/inventory_manager.py:61,67` → `ASSET_ALLOCATION[pair]["TARGET_PCT" | "HODL_PCT"]`
  - `trading/parameters_manager.py:37` → `STOP_PERCENTILES[pair][level]` (feeds the periodic `K_STOP` recompute)
  - `trading/backtest.py:132–137` → `TRADING_PARAMS[pair][side]` (advisory; runs in the API threadpool)
  Changing any of these today requires editing `.env` and restarting the `botc` container.
- **Core objective.** Allow operational re-tuning of an active pair without a restart, while keeping the trading code's read path exactly as it is today.
- **Key insight that shapes the design.** The three config dicts are *already* mutable and are *already* mutated at runtime by a single thread: the scheduler writes the recomputed `K_STOP` into `TRADING_PARAMS` every `PARAM_SESSIONS`. So the cleanest place to apply a DB override is the same dicts, on the same thread, at the top of each session. The trading loop keeps reading plain dicts; "dynamic" is achieved by *re-materialising* those dicts each tick rather than by introducing an accessor layer.
- **Files to read before starting:**
  - `core/config.py` — the three dicts, `PAIRS`, `VOLATILITY_LEVELS`, `STOP_PCT_DEFAULT`, the `_build_*` loaders.
  - `core/validation.py` — `validate_pair_params` (the normalisation + range rules to reuse) and `_parse_float`.
  - `core/database.py:242–263,649–676` — the `BotControl` model and `get_control_value` / `set_control_value`.
  - `core/scheduler.py:48–94` — `trading_session()`; where the per-session override apply is wired.
  - `trading/positions_manager.py`, `trading/inventory_manager.py`, `trading/parameters_manager.py` — the consumers (read-only; **not modified** in this phase).
  - `api/app.py`, `api/routes/control.py`, `api/schemas.py` — router/auth conventions.
  - `services/telegram/polling.py`, `services/telegram/client.py` — command handler + REST client conventions.

### Architectural decisions

- **No new module, no new service, no new table, no accessor layer.** Overrides reuse `bot_control` (key/value, currently with no production callers — this is its first use). The merge logic is a handful of pure functions added to `core/config.py`; the DB reads are DAL helpers in `core/database.py`; the wiring is one call in the scheduler and one new router. The previous draft of this plan introduced `runtime` accessor functions (`get_k_act`, `get_min_margin`, …) and required rewriting every consumer and ~12 test files; that is rejected here in favour of keeping the dict read path untouched.
- **The live config dicts remain the single source of truth the trading loop reads.** `K_ACT`, `MIN_MARGIN`, `TARGET_PCT`, `HODL_PCT`, `STOP_PCT_<level>` are written *into* the existing dicts; consumers are byte-for-byte unchanged.
- **Single writer → no locks.** All mutation of the config dicts happens on the scheduler thread: the existing `K_STOP` write and the new override apply, both inside `trading_session()`. The trading reads happen on that same thread. No lock is added to the read path, preserving the "simplest possible consumption" goal. (The only cross-thread readers are the advisory `GET /config` route and `run_backtest` — see *Technical constraints* for why that is safe.)
- **Apply by selective overlay, never a blanket reset.** `apply_config_overrides` sets *only* the overridable keys to `override-if-present-else-baseline`. It must not replace whole sub-dicts, because `TRADING_PARAMS[pair][side]["K_STOP"]` is a *computed* value (written by `calculate_trading_parameters`) and must survive every apply.
- **A startup baseline snapshot enables revert.** Right after `validate_config()` normalises the dicts, `config.snapshot_baseline()` deep-copies the overridable values. Deleting an override restores its baseline value without re-reading `.env` or recomputing anything.
- **Overrides are pair-wide.** A `K_ACT` / `MIN_MARGIN` override applies to *both* sides, mirroring the pair-wide `{pair}_K_ACT` env form. When no override exists, each side keeps its own `.env` baseline (per-side env like `XBTEUR_SELL_K_ACT` is preserved). Key space stays flat: `config:XBTEUR:K_ACT`.
- **`GET /config` reports effective = baseline ⊕ DB overrides, computed from the DB.** It does not read the live trading dicts, so it is both thread-safe and immediate (it reflects a write before the next session materialises it). The internal ≤ one-session materialisation lag never shows up in the API answer.
- **All overrides propagate within one session (≤ `SLEEPING_INTERVAL`, ~60 s).** `K_ACT`, `MIN_MARGIN`, `TARGET_PCT`, and `HODL_PCT` are consumed directly from the dicts each tick so they land immediately on the next session. `STOP_PCT_<level>` is indirect — it lives in `STOP_PERCENTILES` and must feed `K_STOP` in `TRADING_PARAMS` to have any effect — but `K_STOP` is recomputed *immediately* when a `STOP_PCT` override is active, using the cached calibration events from `runtime`, without waiting for the `PARAM_SESSIONS` gate. A `STOP_PCT` override that takes 12 hours to take effect is not a useful feature; all overrides must propagate at session cadence.
- **The optimizer is unaffected, for free.** `CURRENT` mode is built by `trading/optimizer/search.py:_candidate_from_env`, which runs inside the `spawn`ed worker process. That process re-imports `core.config` fresh (pure `.env`, no scheduler, no override apply), so `CURRENT` keeps evaluating the static `.env` baseline regardless of active overrides — exactly the existing contract, achieved with zero new code. The live `botc` process's dicts hold the effective config; the worker's do not.

## Target outcome

```
Write path (REST / Telegram)                Read path (live trading loop)
┌──────────────────────────────┐            trading_session()  every SLEEPING_INTERVAL
│ PUT  /config/{pair}/{param}   │              ├─ overrides, stop_pairs = db.get_config_overrides()
│ DELETE /config/{pair}/{param} │   bot_control ─┤  (one SELECT … LIKE 'config:%')
│ PUT  /config        (bulk)    │──────────────► ├─ config.apply_config_overrides(overrides)
│ GET  /config[/{pair}]         │   (config:*) │  │   writes K_ACT/MIN_MARGIN/TARGET_PCT/
└──────────────┬───────────────┘            │  │   HODL_PCT/STOP_PCT_* into the existing
               │ validate + persist         │  │   dicts (baseline where no override)
               ▼                            │  ├─ per-pair: if pair in stop_pairs →
        config.effective_config()           │  │   calculate_k_stops(pair, calibration.events)
        = baseline ⊕ DB overrides           │  │   immediately rewrites K_STOP (no PARAM_SESSIONS
        (GET answers from here)             │  │   gate — uses already-cached events, cheap)
                                            │  └─ per-pair loop reads the dicts unchanged
                                            └─ calculate_trading_parameters() every
                                               PARAM_SESSIONS still runs normally (ATR
                                               percentiles, full structural re-detection)
Telegram: /config, /set, /reset  ── via services/telegram/client → the same REST endpoints
```

After this phase:

- `PUT /config/XBTEUR/K_ACT {"value": 1.5}` persists an override; the next session materialises it and the live bot trades on it — no restart.
- `DELETE /config/XBTEUR/K_ACT` reverts that one parameter to its `.env` baseline.
- `PUT /config` atomically replaces the entire override set (wipe + insert) after validating the whole candidate config.
- `GET /config` returns the effective per-pair configuration and flags which parameters are currently overridden.
- `/config`, `/set` and `/reset` give Telegram parity for the common operations.
- Every consumer in `trading/` is unchanged; no existing test is rewritten.

---

## Step 1 — Override registry, baseline snapshot & apply logic (`core/config.py`)

`core/config.py` must stay DB-free (it is imported everywhere; importing `core.database` would be circular). So Step 1 adds only **pure** functions that operate on already-fetched override data.

### 1.1 Overridable-parameter registry

A single declarative source of truth for *which* parameters are overridable, their bounds, and where each lives in the dicts. Used by validation, by the apply/effective functions, and by the API to reject unknown params.

```python
# core/config.py
# param name -> (min, max) bounds for validation. None bound = unbounded on that side.
OVERRIDABLE_PARAMS: dict[str, tuple[float | None, float | None]] = {
    "TARGET_PCT": (0.0, 100.0),
    "HODL_PCT": (0.0, 100.0),
    "K_ACT": (0.0, None),
    "MIN_MARGIN": (0.0, None),
    **{f"STOP_PCT_{lvl}": (0.0, 1.0) for lvl in VOLATILITY_LEVELS},
}
```

### 1.2 Baseline snapshot

```python
_BASELINE: dict[str, Any] | None = None  # captured once, read-only thereafter

def snapshot_baseline() -> None:
    """Deep-copy the overridable values *after* validation has normalised them.
    Called once from the FastAPI lifespan, right after validate_config()."""
```

The snapshot stores, per pair: `TARGET_PCT`, `HODL_PCT`, both sides' `K_ACT` and `MIN_MARGIN`, and the five `STOP_PCT` levels. It deliberately does **not** store `K_STOP` (computed, never overridable).

### 1.3 `apply_config_overrides` (selective overlay)

```python
def apply_config_overrides(overrides: dict[str, dict[str, float]]) -> set[str]:
    """Materialise effective config into the live dicts. overrides is
    {pair: {param: typed_value}}; values already validated. Sets each
    overridable key to its override if present, else its baseline. Touches
    only overridable keys — K_STOP and every other computed value survive.
    Returns the set of pairs where at least one STOP_PCT_* value actually
    changed this call (compare-before-write), so the caller can force a
    K_STOP recompute only when the percentiles moved."""
```

Logic, per pair in `PAIRS` (skips pairs absent from the snapshot):

- `K_ACT` / `MIN_MARGIN`: pair-wide override → write to **both** `sell` and `buy`; absent → restore each side's baseline.
- `TARGET_PCT` / `HODL_PCT`: write to `ASSET_ALLOCATION[pair]` (override or baseline).
- `STOP_PCT_<level>`: compute `new_val = override if present else baseline`. Compare against the current `STOP_PERCENTILES[pair][level]` **before** writing; if the value differs, write and add `pair` to `changed_stop_pct_pairs`. This avoids inter-session state — `STOP_PERCENTILES` is only ever written here (at runtime), so "current value ≠ new value" is equivalent to "something changed since last session."

Idempotent for unchanged overrides: re-applying the same override set leaves all dicts unchanged and returns `set()`. Calling it with an empty dict restores the full `.env` baseline (and returns the pairs whose STOP_PCT values were previously overridden).

### 1.4 `effective_config` (pure, for `GET`)

```python
def effective_config(
    overrides: dict[str, dict[str, float]], pair: str | None = None
) -> dict[str, dict[str, Any]]:
    """Return {pair: {TARGET_PCT, HODL_PCT, K_ACT:{sell,buy}, MIN_MARGIN:{sell,buy},
    STOP_PCT:{LL..HH}, overridden:[param,...]}} from baseline ⊕ overrides, without
    touching the live dicts. The route fetches `overrides` from the DB and calls this."""
```

`overridden` lists the params with an active DB override, so a reader can see baseline-vs-override at a glance.

### 1.5 Tests

`tests/unit/core/test_config_overrides.py`:

- `test_apply_overlays_override_over_baseline` — snapshot a fixture baseline, apply `{XBTEUR: {K_ACT: 2.0}}`, assert both sides' `K_ACT == 2.0` and other keys untouched.
- `test_apply_empty_restores_baseline` — apply an override, then apply `{}`, assert the dicts equal the baseline.
- `test_apply_preserves_k_stop` — set `TRADING_PARAMS[...]["K_STOP"]` to a sentinel, apply overrides, assert the sentinel survives.
- `test_apply_returns_stop_pairs_only_on_change` — apply `{XBTEUR: {STOP_PCT_MV: 0.8}}` (differs from baseline), assert return is `{"XBTEUR"}`; apply the **same** dict again, assert return is `set()` (no change, no recompute needed); apply a non-STOP_PCT override, assert return is `set()`.
- `test_apply_returns_stop_pairs_on_revert` — apply a STOP_PCT override, then apply `{}`, assert return includes `"XBTEUR"` (revert to baseline also triggers recompute).
- `test_effective_config_flags_overridden` — assert `overridden` contains exactly the overridden params and values match.

**Commit:** `feat(config): overridable-param registry, baseline snapshot, and pure apply/effective helpers`.

---

## Step 2 — DAL helpers (`core/database.py`)

Add four helpers next to `get_control_value` / `set_control_value`, all using key prefix `config:{pair}:{param}`. Mutating writes propagate errors (`raise`); reads return `{}` on error, consistent with the existing DAL.

```python
_CONFIG_PREFIX = "config:"

def get_config_overrides() -> dict[str, dict[str, float]]:
    """SELECT every bot_control row WHERE control_key LIKE 'config:%', parse the
    key as config:{pair}:{param}, coerce the value to float, and return
    {pair: {param: value}}. Rows for unknown pairs/params or unparseable values
    are skipped with a warning (defensive — the API validates on write)."""

def set_config_override(pair: str, param: str, value: str, updated_by: str | None = None) -> None:
    """Upsert one override via set_control_value(f'config:{pair}:{param}', value, ...)."""

def delete_config_override(pair: str, param: str) -> None:
    """DELETE the single config:{pair}:{param} row (no-op if absent)."""

def replace_config_overrides(overrides: dict[str, dict[str, str]], updated_by: str | None = None) -> None:
    """Atomic bulk replace: in one session, DELETE all config:% rows, then INSERT
    the provided set. Either the whole new set lands or none does."""
```

`get_config_override` for a single key isn't needed — the API reads the whole set and slices.

`tests/integration/test_config_overrides_dal.py` (gated by `RUN_DB_INTEGRATION`): set → read-back → delete; bulk replace wipes prior rows; unparseable/unknown rows are skipped by `get_config_overrides`.

**Commit:** `feat(database): config override DAL on bot_control (get/set/delete/replace)`.

---

## Step 3 — Wire the apply into the scheduler & baseline into startup

### 3.1 Capture the baseline at startup

In `api/app.py` lifespan, immediately after the `validate_config()` success check (so the snapshot captures normalised floats):

```python
from core import config
...
if not validate_config():
    raise RuntimeError(...)
config.snapshot_baseline()
```

### 3.2 Apply overrides at the top of every session

In `core/scheduler.py:trading_session()`, after the bot-paused check and before the per-pair loop (so a paused or `TRADING_ENABLED=false` replica still keeps its effective config coherent for the API and optimizer):

```python
stop_pct_pairs = config.apply_config_overrides(db.get_config_overrides())
```

One `SELECT … LIKE 'config:%'` per session (negligible alongside the existing per-session DB work). Runs on the scheduler thread — the single writer — so no lock is needed.

Then, inside the per-pair loop (after loading `calibration` from `runtime.get_pair_calibration(pair)`), for any pair in `stop_pct_pairs`:

```python
if pair in stop_pct_pairs and calibration is not None:
    calculate_k_stops(pair, calibration.events)
```

This rewrites `TRADING_PARAMS[pair][side]["K_STOP"]` from the freshly-overlaid `STOP_PERCENTILES`, bypassing the `PARAM_SESSIONS` gate. It fires only when `apply_config_overrides` detected an actual change (compare-before-write), so subsequent sessions with an unchanged override return an empty `stop_pct_pairs` and no recompute runs — no redundant work. It uses structural events already cached in the runtime — no OHLC scan — so the cost is a percentile lookup over in-memory data. The normal `calculate_trading_parameters` gate continues to run on its own cadence and will also rewrite `K_STOP` at the next recalibration (using the same up-to-date `STOP_PERCENTILES`). If `calibration` is `None` (pair not yet warm), the recompute is skipped silently — `K_STOP` will be set once calibration completes.

This is the sole propagation path into the live trading dicts; the API does **not** mutate the dicts directly (it persists to the DB and lets the next session materialise, while `GET` answers from `effective_config`).

### 3.3 Tests

In `tests/unit/core/test_scheduler.py` (or a focused new module):
- Monkeypatch `db.get_config_overrides` to return `{XBTEUR: {K_ACT: 3.0}}`, run one `trading_session`, assert `TRADING_PARAMS["XBTEUR"]["buy"]["K_ACT"] == 3.0`.
- Monkeypatch to return `{XBTEUR: {STOP_PCT_MV: 0.9}}` (first session), stub `runtime.get_pair_calibration` with cached events, run one session, assert `calculate_k_stops` was called and `TRADING_PARAMS["XBTEUR"]["buy"]["K_STOP"]` reflects the new percentile — same session, not the next `PARAM_SESSIONS` cycle. Run a second session with the same override, assert `calculate_k_stops` was **not** called again (no change detected).
- A test with `{}` asserts the baseline is restored.

**Commit:** `feat(scheduler): materialise config overrides each session; snapshot baseline at startup`.

---

## Step 4 — Management API (`api/routes/configuration.py`)

New router, registered in `api/app.py`'s `include_router` loop with the shared `_auth` dependency (every endpoint requires `X-Api-Token`, like the rest).

### 4.1 Schemas (`api/schemas.py`)

```python
class ConfigValueRequest(BaseModel):
    value: float                       # the new override value

class PairConfig(BaseModel):
    target_pct: float
    hodl_pct: float
    k_act: dict[str, float | None]     # {"sell": ..., "buy": ...}
    min_margin: dict[str, float | None]
    stop_pct: dict[str, float]         # {"LL": ..., ... "HH": ...}
    overridden: list[str]              # params with an active DB override

class ConfigResponse(BaseModel):
    config: dict[str, PairConfig]      # keyed by pair

class BulkConfigRequest(BaseModel):
    config: dict[str, dict[str, float]]  # {pair: {param: value}} — the full desired override set
```

### 4.2 Endpoints

1. **`GET /config`** and **`GET /config/{pair}`** — return `ConfigResponse` from `config.effective_config(db.get_config_overrides(), pair)`. Unknown `{pair}` → `404`.
2. **`PUT /config/{pair}/{param}`** — upsert one override (create or update). Validate `pair ∈ PAIRS`, `param ∈ OVERRIDABLE_PARAMS`, and `value` within the registry bounds (reuse `validation._parse_float` with those bounds). For `TARGET_PCT`, also reject if the resulting cross-pair sum would exceed 100 (compute from current effective config). On success `db.set_config_override(...)`; return the updated `PairConfig`. Invalid → `422`.
3. **`DELETE /config/{pair}/{param}`** — `db.delete_config_override(...)`, reverting that param to its `.env` baseline; return the updated `PairConfig`. Idempotent (`200` even if no override existed).
4. **`PUT /config`** — bulk replace. Validate the **entire** candidate set up front (every value's bounds via the registry, plus the cross-pair `TARGET_PCT` sum ≤ 100, reusing the same range logic as `validate_pair_params`); reject the whole payload on any error (`422`). On success `db.replace_config_overrides(...)` atomically. Return the new effective `ConfigResponse`.

All write endpoints accept an optional `updated_by` (defaulting to `"api"`) threaded into `set_control_value`'s audit column. Writes are immediately visible to `GET` (it reads the DB); they reach the live trading dicts at the next session.

### 4.3 Tests

`tests/unit/api/test_configuration_routes.py` (async route tests, monkeypatching the DAL):

- `GET /config` returns effective values and correct `overridden` lists.
- `PUT` with an out-of-range value → `422`; valid value → `200` + DAL called.
- `PUT /config/XBTEUR/TARGET_PCT` that pushes the sum over 100 → `422`.
- `DELETE` removes the override and is idempotent.
- `PUT /config` bulk: a payload with one bad value rejects the whole set (no DAL replace call); a valid payload calls `replace_config_overrides` once.
- Unknown pair/param → `404` / `422`.

**Commit:** `feat(api): configuration router — query, upsert, delete, and bulk-replace pair overrides`.

---

## Step 5 — Telegram interface (`services/telegram/polling.py`)

Add three handlers mirroring the existing command style (`_check_auth`, `client.<verb>`, friendly errors), wired in `build_tg_app`. They call the same REST endpoints, so there is no second copy of any logic.

- **`/config [pair]`** — `GET /config` (or `/config/{pair}`); format the effective params per pair, marking overridden ones (e.g. a `*` suffix). Mirrors the `/market` formatting style.
- **`/set <pair> <param> <value>`** — `PUT /config/{pair}/{param}` with `{"value": <float>, "updated_by": "telegram"}`; reply with the new effective value or the API's `422` detail. Validate arg count and that `param ∈ OVERRIDABLE_PARAMS` before the call for a friendly message.
- **`/reset <pair> <param>`** — `DELETE /config/{pair}/{param}`; reply confirming revert to the `.env` baseline.

Extend `/help` to list the three commands and an example (`/set XBTEUR K_ACT 1.5`).

`tests/unit/services/telegram/test_config_commands.py`: monkeypatch `client` to assert each handler hits the right endpoint with the right payload and renders the reply; unknown pair/param and bad arg counts produce the friendly error without an HTTP call.

**Commit:** `feat(telegram): /config, /set and /reset commands for runtime pair configuration`.

---

## Technical constraints & safety

- **No circular imports.** `core/config.py` gains only pure functions over passed-in data (no `core.database` import). DB reads live in `core/database.py`; the scheduler and the API router are the only callers of `get_config_overrides`. Dependency flow stays `api`/`scheduler` → `core.config` + `core.database`, and `trading/` → `core.config` (unchanged).
- **Single-writer thread-safety.** The config dicts are mutated only on the scheduler thread (existing `K_STOP` write + new override apply). The two cross-thread *readers* — `GET /config` and `run_backtest` — never read the live dicts and the live dicts respectively in a way that can corrupt live trading: `GET` reads `effective_config(db…)` instead of the dicts; `run_backtest` reads the dicts but is advisory, and the worst case is a single simulation reflecting a half-applied multi-key update for one pair during the ~microsecond apply window. No lock is added to the trading read path.
- **Baseline integrity.** `apply_config_overrides` overlays only the registry keys; `K_STOP` and any other computed/derived state in `TRADING_PARAMS` are never reset. The baseline snapshot is taken once, after normalisation, and is read-only thereafter.
- **Validation parity.** Single-value writes and the bulk replace reuse the same bounds (the `OVERRIDABLE_PARAMS` registry) and the same range/sum rules as `validate_pair_params`, so a value rejected at startup is rejected at runtime too. `get_config_overrides` is additionally defensive: it skips unknown or unparseable rows so a hand-edited bad DB row can never crash a session.
- **Propagation:** all overrides land next session (≤ `SLEEPING_INTERVAL`). For non-stop params (`K_ACT`, `MIN_MARGIN`, `TARGET_PCT`, `HODL_PCT`) the applied dict value is consumed directly each tick. For `STOP_PCT_*`, `apply_config_overrides` returns the pair in `stop_pct_pairs` and the scheduler calls `calculate_k_stops(pair, calibration.events)` immediately within the same session, so `K_STOP` is up to date before the position block runs. `GET /config` always reflects the desired (effective) config immediately regardless of materialisation.
- **Optimizer isolation.** The `spawn`ed optimizer worker re-imports `core.config` fresh and never runs the scheduler apply, so `CURRENT` mode continues to evaluate the static `.env` baseline. Overrides do not leak into optimizer comparisons.

## Design choices (to add to CLAUDE.md on merge)

- **Runtime config overrides materialise into the existing config dicts; the trading loop's read path is unchanged.** Rather than introduce accessor functions and refactor every consumer, the scheduler — already the single thread that mutates `TRADING_PARAMS` (it writes `K_STOP`) — overlays DB overrides onto the same dicts at the top of each session. Trading code keeps reading plain dicts, no lock, no new module. For `STOP_PCT_*` overrides, `apply_config_overrides` uses a compare-before-write: it checks the incoming value against the current `STOP_PERCENTILES` entry before writing, and returns only the pairs where the value actually changed. The scheduler calls `calculate_k_stops(pair, calibration.events)` for those pairs — no OHLC scan, just a percentile lookup on cached events — so the K_STOP recompute runs once on the session where the override changes, and not again until the next change. All overrides therefore propagate within one `SLEEPING_INTERVAL`, with no inter-session state and no redundant work. `GET /config` hides the materialisation window by answering from `baseline ⊕ DB` directly rather than reading the live dicts.
- **Overrides reuse `bot_control` (key `config:{pair}:{param}`).** No new table or migration; the previously-unused key/value table gets its first production caller. Values are stored as strings exactly like `.env`, so the override set is trivially inspectable (`SELECT * FROM bot_control WHERE control_key LIKE 'config:%'`) and revertible per-key.
- **A startup baseline snapshot, not a re-read of `.env`, backs revert.** Deleting an override restores the normalised baseline value captured after `validate_config()`, so revert is a pure in-memory operation and never recomputes or re-parses anything.

## Testing requirements (acceptance)

1. **Overlay & revert** — `apply_config_overrides` overlays an override and restores baseline on delete; `K_STOP` survives every apply.
2. **Propagation** — DB override → next `trading_session` → consumer reads the new value from the dict.
3. **Stop-override immediate propagation** — a `STOP_PCT` override causes `calculate_k_stops` to be called in the *same* session; `K_STOP` in `TRADING_PARAMS` reflects the new percentile before the per-pair position block runs. It does not wait for the next `calculate_trading_parameters` gate.
4. **API** — query returns effective config + `overridden` flags; single upsert/delete and bulk replace validate (bounds + `TARGET_PCT` sum) and persist; bad input is rejected atomically.
5. **Telegram parity** — `/config`, `/set`, `/reset` hit the matching endpoints and render results/errors.
6. **Optimizer isolation** — `CURRENT` mode is unaffected by active overrides (worker reads `.env` baseline).

**Commit convention (per step above).** Final integration commit: `feat(config): dynamic per-pair configuration via DB-backed runtime overrides (API + Telegram)`.
