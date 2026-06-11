# Phase 11 – Full Search-Grid Calibration Plan

**Branch:** `feature/phase-11-trend-chop-regime-filter`
**Created:** 2026-06-11

---

## 1. Goal

Every search dimension is now a request input (`SearchSpace` / `RegimeSpace` of
`GridSpec{start, end, step}`). That makes grid design an *experiment input* — and a
mis-designed grid fails in one of two opposite ways:

- **Over-coverage / overfitting** — range too wide or step too fine for the data
  volume: the space is huge, TPE exploits noise, seeds never agree on a config,
  `train_pnl ≫ test_pnl`.
- **Under-coverage / missing values** — range too narrow or step too coarse: the
  real optimum sits *outside* the grid (winner pinned at an edge) or *between*
  grid points (coarse step skips the basin).

The deliverable of this plan is, for each dimension: a **range**, a **step**, and a
**search/fix/disable decision** — i.e. the validated `search_space` JSON to use in
production AUTO runs, plus the evidence trail behind each choice.

### Data context (2026-06-11)

```
Pair    Candles  From          To            Days
XBTEUR  ~2970    2026-05-11    2026-06-11    ~31
ETHEUR  ~2970    2026-05-11    2026-06-11    ~31
```

Kraken's public OHLC API caps at ~720 candles per timeframe (~7.5 days at 15m), so
there is no backfill — history only accumulates forward. With 31 days and an 80/20
split the test window is ~6 days (~4–6 closed ops). This drives the whole plan:
ranges and dead/live classification can be established now; step sizes and a
deployable AUTO config cannot (see §7 for the measurable sufficiency gates).

---

## 2. Dimension inventory

| Dimension | Branch | Domain | Prod reference (2026-06-07) | Dims |
|---|---|---|---|---|
| `stop_pcts` (one grid, searched independently per level LL/LV/MV/HV/HH) | both | [0, 1] | XBT: .95/.65/.60/.70/.35 · ETH: .25/.35/.50/.65/.80 | 5 |
| `k_act` | K_ACT only | ≥ 0 (0 = immediate activation) | unset in prod (margin-based activation) | 1 |
| `min_margin` | MIN_MARGIN only | ≥ 0 (fraction of entry) | XBT: 0.000 · ETH: 0.010 | 1 |
| `er_window` | both (if regime set) | int ≥ 2 | default 32 | 1 |
| `chop_enter_pct` | both (if regime set) | [0, 1] | default 0.33 | 1 |
| `chop_dead_band` | both (if regime set) | [0, 1] (exit = enter + band, by construction) | default 0.07 | 1 |
| `trend_pct` | both (if regime set) | [0, 1] | default 0.66 | 1 |

Structural facts that shape the plan:

- **Two branches, budget split evenly.** `n_trials` is divided across the active
  branches (`_split_budget`). Setting `k_act: null` or `min_margin: null` gives the
  surviving branch the **whole** budget — use this when calibrating one activation
  family so trials aren't wasted on the other.
- **`start == end` fixes a dimension** (1 value, still emitted in the config) —
  the tool for "don't search this, hold it constant".
- **`regime: null` removes 4 dimensions at once.** Blocks 1–3 run regime-off so
  the activation/stop grids are calibrated on a smaller space first.
- **Grid validity:** `(end − start)` must be an integer multiple of `step`.
  Every grid below has been checked against this.

### Combinatorics worksheet

`values(g) = (end − start)/step + 1`; branch space = product over its dims.

Worked example with the wide discovery grids from §4 (regime off):

```
stop_pcts  {0.05, 0.95, 0.15} → 7 values → 7^5 = 16 807
k_act      {0.0, 3.0, 0.5}    → 7 values
K_ACT branch space = 16 807 × 7 ≈ 118k
```

Add the wide regime grids (12 × 5 × 6 × 4 = 1 440) and it explodes to ~169M —
which is why **everything-at-once discovery is hopeless** and the plan works in
blocks: calibrate each family on a small space, then combine only the survivors.

Rules of thumb used as gates below (heuristics, not theory):

- **Discovery runs:** 5–7 values per searched dim is enough to see the landscape.
- **AUTO convergence runs:** the branch space should be small enough that exact
  config agreement between seeds is *possible*, not a lottery. Target ≲ a few
  thousand combinations per branch with `max_trials=3000` — i.e. after Blocks
  1–4, most dims must end up **fixed** or at 3–4 values.
- **Ops budget:** ~31 days ≈ 30–60 closed ops in train. Searching 10+ dims
  against that op count is structurally overfit; the sensitivity stage (B) exists
  to cut the searched-dim count down before any AUTO run.

### Standing request settings (all jobs)

```json
"fee_pct": 0.26, "min_ops": 10, "min_test_ops": 2
```

`min_ops`/`min_test_ops` matter more now than before: a regime config that filters
out nearly all trading can post a flat ~0% PnL that "beats" honest negative configs.
The floor rejects those degenerate candidates. Revisit the values when the window
grows (scale roughly with days/3).

---

## 3. The calibration method (applied to every block)

Five stages, each a go/no-go gate. Stages A–C calibrate the grid; D–E validate it.

### Stage A — Range discovery (OPTIMIZE, wide + coarse)

One family searched at a time; all other dims fixed (`start == end` at the prod
reference) or disabled. Wide range, coarse step, 400–800 trials.

**Edge rule (fixes under-coverage by construction):** if the winner — or ≥2 of the
top-5 — sits at a grid boundary, extend the range 50% past that edge and re-run.
Repeat until the winner is interior. A dimension that keeps diverging toward an
edge after two extensions is telling you something structural (e.g. `k_act → 0`
means "immediate activation is just better"); record it and fix the dim there.

**Cluster read:** top-5 clustered in one zone → real basin, proceed. Scattered →
note it; the dimension may be noise-dominated at this data volume (Stage B will
confirm).

### Stage B — Sensitivity classification (CURRENT, cheap, ~2 min/job)

Perturb each dim of the Stage-A winner by ±1 step, one at a time, via CURRENT jobs.

- **Dead** (|Δ robust_pnl| < ~0.5% for both perturbations) → **fix it** at the
  winner value (`start == end`). Every fixed dim shrinks the space multiplicatively
  and is the single most effective anti-overfitting move available.
- **Live** (steep gradient) → keep searching it; it earns a place in the final grid.
- **Live at the boundary** (gradient still steep at the range edge) → back to
  Stage A with an extended range.

### Stage C — Step refinement (OPTIMIZE ×2, same n_trials)

Only for dims classified *live*. Run the same search with the step halved and
compare against the coarse run:

| Outcome | Verdict |
|---|---|
| Same winning zone, similar robust_pnl | Keep the **coarse** step (cheaper space, easier seed agreement) |
| Fine grid posts notably higher robust_pnl, winner jumps zone | Noise exploitation — keep **coarse** |
| Fine grid relocates the winner *between* coarse points, robust_pnl equal-or-better, and the new point is stable under a seed change | Real resolution gain — keep **fine** |

With ~31 days of data, ties break toward coarse, always.

### Stage D — Stability cross-checks (OPTIMIZE ×4)

Run the calibrated family grid on:

- **Two overlapping temporal windows** (21 days each, `train_split: 0.67`):
  - Window AB: `"start": "2026-05-11", "end": "2026-06-01"`
  - Window BC: `"start": "2026-05-21", "end": "2026-06-11"`
- **Both pairs** (XBTEUR, ETHEUR). Winning *zones* don't need to match across
  pairs — prod configs differ legitimately — but a grid that pins **both** pairs'
  winners at the same edge is a miscalibrated grid, not two coincidences.

Same-zone winners across windows → the range/step survive. Different zones →
the dimension has no temporally stable optimum yet; fix it at the prod reference
and revisit once the §7 gates pass.

### Stage E — AUTO as the final exam *of the grid*

One AUTO run with the fully calibrated `search_space` (all blocks merged):

```json
"auto_settings": { "n_seeds": 4, "min_agree": 3, "trial_step": 500, "max_trials": 3000 }
```

- Converges → the grid is **AUTO-ready**; record the winning config as a deploy
  candidate (subject to the §7 caveat).
- Doesn't converge → the searched space is still too large for the data. Fix the
  weakest *live* dims (lowest Stage-B gradient) and retry once; if it still fails,
  park until the §7 gates pass. **Non-convergence here is a data-volume verdict,
  not a failed experiment** — write it down.

---

## 4. Execution order (blocks)

Ordered so each block inherits fixed values from the previous one. Estimated wall
times based on observed runs (CURRENT ≈ 2 min; OPTIMIZE 400 trials ≈ 10–15 min;
800 ≈ 20–30 min; AUTO ≤ 90 min).

### Block 0 — Baselines (4 CURRENT jobs, ~10 min)

Reference points for every later comparison. Per pair:

```json
// 0a: no regime
{ "pair": "XBTEUR", "mode": "CURRENT", "fee_pct": 0.26 }

// 0b: regime with current default values
{ "pair": "XBTEUR", "mode": "CURRENT", "fee_pct": 0.26,
  "regime_enabled": true, "er_window": 32, "chop_enter_pct": 0.33,
  "chop_dead_band": 0.07, "trend_pct": 0.66 }
```

**Read:** does `robust_pnl(0b) > robust_pnl(0a)`? If not, the regime defaults are
misconfigured — still useful info before searching.

### Block 1 — `stop_pcts` (regime off)

The 5 stop dims dominate the space (power of 5), so their step matters most.

```json
// 1a — discovery, K_ACT branch only (full budget on one branch)
{ "pair": "XBTEUR", "mode": "OPTIMIZE", "n_trials": 600,
  "search_space": {
    "stop_pcts": {"start": 0.05, "end": 0.95, "step": 0.15},
    "k_act":     {"start": 1.0,  "end": 1.0,  "step": 0.5},
    "min_margin": null, "regime": null } }

// 1b — same but MIN_MARGIN branch only, min_margin fixed at 0.010
```

Prod stop values span 0.25–0.95, so expect *live* and spread-out dims. Stage B here
is 10 CURRENT jobs (5 levels × ±1 step) — worth it: any level classified *dead*
(likely the levels with few sessions, LL/HH) gets fixed and takes a factor of ~7
out of the space. Stage C: step 0.15 vs 0.075.

**Expected outcome:** a per-level verdict — probably 2–3 live levels searched at
step 0.15–0.20 within [0.2, 0.95], the rest fixed.

### Block 2 — `k_act` (regime off, `min_margin: null`)

```json
"stop_pcts": {"start": 0.30, "end": 0.90, "step": 0.30},   // coarse 3-value placeholder
"k_act":     {"start": 0.0,  "end": 3.0,  "step": 0.5},    // includes 0 = immediate
"min_margin": null, "regime": null
```

Note the trade-off: stops are *searched coarsely* (not fixed) so `k_act` is
evaluated against a tolerant stop landscape rather than one frozen point. Edge
rule applies at 3.0 (extend to 4.5 if pinned). Prod has no `K_ACT` at all — if
Stage B shows the whole branch underperforming the MIN_MARGIN branch baseline,
consider `k_act: null` as the *calibration outcome* for this dataset.

### Block 3 — `min_margin` (regime off, `k_act: null`)

```json
"stop_pcts": {"start": 0.30, "end": 0.90, "step": 0.30},
"k_act": null, "regime": null,
"min_margin": {"start": 0.000, "end": 0.020, "step": 0.004}   // 6 values; prod 0.000 and 0.010 on-grid
```

Edge rule: XBT prod sits at exactly 0.000 (the domain floor) — if the winner stays
at 0.000 that is *not* under-coverage, the domain ends there; record it as a fix
candidate. If pinned at 0.020, extend to 0.032.

### Block 4 — Regime dims (4 dims)

Companions for every job in this block: the **calibrated stop/activation grids from
Blocks 1–3** (not wide placeholders), so the regime dims are calibrated against
realistic companions.

**Stage A — discovery (1 job, 800 trials, ~20–30 min):**

```json
"regime": {
  "er_window":      {"start": 8,    "end": 96,   "step": 8},
  "chop_enter_pct": {"start": 0.10, "end": 0.50, "step": 0.10},
  "chop_dead_band": {"start": 0.03, "end": 0.18, "step": 0.03},
  "trend_pct":      {"start": 0.55, "end": 0.85, "step": 0.10}
}
```

Edge rule applies per dim (`er_window` pinned at 8 or 96 → extend; `chop_enter_pct`
pinned at 0.50 → extend to 0.70; etc.). Remember `chop_exit_pct` is **derived**
(`enter + dead_band`) — never search it directly (see Appendix A).

**Stage B — sensitivity (8 CURRENT jobs, ~2 min each):** perturb each of the 4
winner params ±1 step, e.g. winner `er_window=32` → run 24 and 40 with the other
three held. Expect at least one dim (often `trend_pct` or `dead_band`) to come out
*dead* — fix it.

**Stage C — step comparison (2 jobs, same n_trials):**

```json
// coarse (3 values per dim)
"regime": {
  "er_window":      {"start": 16,   "end": 64,   "step": 24},
  "chop_enter_pct": {"start": 0.20, "end": 0.40, "step": 0.10},
  "chop_dead_band": {"start": 0.05, "end": 0.10, "step": 0.05},
  "trend_pct":      {"start": 0.60, "end": 0.80, "step": 0.10}
}

// fine (5+ values per dim), same n_trials
"regime": {
  "er_window":      {"start": 16,   "end": 64,   "step": 8},
  "chop_enter_pct": {"start": 0.20, "end": 0.40, "step": 0.05},
  "chop_dead_band": {"start": 0.05, "end": 0.10, "step": 0.025},
  "trend_pct":      {"start": 0.60, "end": 0.80, "step": 0.05}
}
```

(Center these on the Stage-A winner zone, not necessarily the values above.)

**Stage D — temporal windows + cross-pair (4 jobs, 400 trials each):** windows AB
and BC from §3, for both pairs. Do 2a/2b winners share the same `er_window` and
`chop_enter_pct` zone? Consistent zone across windows → evidence of a
generalizable signal.

**Extra regime-only check:** count regime *episodes* in the window (how many
chop↔trend transitions the winning classifier actually produces). A config whose
edge comes from a single long episode is untested, however good its PnL — see
Gate 2 in §7.

### Block 5 — Integrated AUTO (Stage E, 1–2 jobs)

Merge every surviving grid into one `search_space` and run AUTO per pair. Before
launching, recompute the branch space with the §2 formula and sanity-check it
against the convergence heuristic; if it's still ≫ a few thousand combinations,
fix more dims first — don't burn 90 minutes to confirm arithmetic.

---

## 5. Decision-rule reference

| Signal | Direction | Action |
|---|---|---|
| Winner (or ≥2 of top-5) at grid edge | under-coverage | Extend range 50%, re-run Stage A |
| Steep CURRENT gradient at range boundary | under-coverage | Extend range |
| Fine grid relocates winner between coarse points, robust_pnl ≥, seed-stable | under-coverage (step) | Adopt finer step |
| `train_pnl − test_pnl` > 5% | overfitting | Coarsen/shrink; distrust the candidate |
| Top-5 scattered across zones | overfitting / noise | Stage B; likely fix the dim |
| Fine grid inflates robust_pnl, winner jumps zone | overfitting (step) | Keep coarse step |
| Temporal windows disagree on zone | overfitting / no signal | Fix dim at prod reference, revisit when §7 gates pass |
| Both pairs pinned at the same edge | grid miscalibration | Extend range (this one is on the grid, not the data) |
| AUTO non-convergence on a trimmed grid | data volume | Park; re-run when §7 gates pass |
| Dim dead in Stage B (<0.5% Δ) | n/a | Fix it (`start == end`) — the default win |

---

## 6. Results log

Track every job in `docs/plan/phase-11-grid-calibration-results.md` (create on first
run), one row per job:

```
| job | block/stage | pair | window | grid (changed dims) | n_trials | winner | train | test | robust | edge? | verdict |
```

Every job already stores its full request in `optimizer_jobs.request`, so the log
only needs the verdict trail, not full reproducibility.

The same file also hosts the weekly **Gate history** table (format in §7.3) at the
top, so sufficiency tracking and job verdicts live in one place.

---

## 7. What to repeat with more data — and when "more" is enough

### 7.1 Repetition map

| Stage | Repeat later? | Why |
|---|---|---|
| Block 0 (baselines) | **Yes** (trivial, 4 CURRENT jobs) | Re-anchors every comparison to the longer window |
| Stage A (ranges) | **Only if** a dim hit the edge rule, or new market regimes appear in the data | Ranges are mostly parameter geometry, not statistics — they should hold |
| Stage B (dead/live) | **Yes** (cheap) | A dim that looks dead on 30–60 ops may show a real gradient at 100+ ops; the classification is the most data-sensitive *cheap* result |
| Stage C (step) | **Yes** | Step verdicts are pure data-volume calls; "ties break coarse" stops applying as the test window grows |
| Stage D (stability) | **Yes — upgraded** | With ≥60 days use **3** windows (or proper walk-forward, the deferred option (1) from the robustness discussion) instead of 2 overlapping ones |
| Stage E (AUTO) | **Yes** | The re-run that passes the gates below is the one whose config ships to prod |

In short: **ranges learned now persist; everything statistical gets re-run.** The
first pass is not wasted — it prunes dimensions (Stage B fixes), establishes ranges,
and produces the negatives that tell you what *not* to search.

### 7.2 Is 60 days "enough"? — honest answer: nobody has proven that

The ~60-day / mid-July figure has **no empirical backing**. It came from the
2026-06-08 false-alarm postmortem (the −5.83% `robust_pnl` scare): with ~27 days
and an 80/20 split the test slice held **4–5 trades**, where a single trade swings
PnL by ±4 percentage points — so `min(train, test)` was measuring one trade's
luck, not the config. "Double the data" was an arithmetic patch, not a derived
threshold. Note the arithmetic doesn't even fully close the hole: at the observed
~1 op/day, 60 days × 20% test ≈ **10–12 test ops** — better, still thin.

So this plan replaces the date with **three measurable gates**. Data is
"sufficient" for a given conclusion when the relevant gate passes — whenever
that happens, be it day 55 or day 90:

**Gate 1 — test-slice op count.** The test slice must hold **≥ 20 closed ops**
(point-estimate noise shrinks ~1/√n; at 20 ops one trade moves the mean ~5× less
than at 4 ops). Levers if the calendar alone doesn't get there: lower
`train_split` to 0.70–0.75, or adopt walk-forward so every op is a test op once.
Check it empirically: run a CURRENT job and read the test op count — no
estimation needed.

**Gate 2 — regime-episode count (Block 4 only).** The window must contain
**≥ ~6 chop↔trend transitions** under the candidate classifier. If the whole
window is one trend, the chop filter was never exercised and no op count can
validate it. Count episodes from the winning candidate's simulation; a window
that fails this gate cannot validate regime dims regardless of Gate 1.

**Gate 3 — verdict stability under growing data (the actual empirical test).**
Pin one CURRENT job (prod config) and one OPTIMIZE job (fixed grid, fixed seed)
and re-run them **weekly** as history accumulates. Data is sufficient when the
verdicts stop flipping across ~3 consecutive weeks: `robust_pnl` keeps its sign
and the OPTIMIZE winner stays in the same zone. This converts "is it enough yet?"
from an assumption into a measurement — and it is the only gate that directly
tests the thing we care about (conclusions that survive new data).

### 7.3 Gate history (weekly log)

Each week, after running the Gate-3 probe pair (1 pinned CURRENT + 1 pinned
OPTIMIZE per pair), append one row per pair to a **Gate history** table at the top
of `phase-11-grid-calibration-results.md`:

```
| date | pair | days | test_ops (G1 ≥20) | episodes (G2 ≥6) | robust_pnl sign | winner zone | G3 stable? | gates passed |
```

- `test_ops` comes straight from the CURRENT result; `episodes` from the winning
  candidate's simulation; `winner zone` is the OPTIMIZE winner's params (rounded
  to grid points) — "same zone as last week?" is the G3 check.
- `G3 stable?` flips to **yes** after ~3 consecutive rows with the same
  `robust_pnl` sign and winner zone.
- The table is the single place to answer "are we there yet?": the first week
  where a pair shows G1 ✓ **and** G3 ✓ (plus G2 ✓ if regime dims are in play) is
  the trigger to re-run Stages C/D/E for that pair.

This also builds the empirical record for the portfolio write-up: it documents
*when* and *why* the data became sufficient, instead of asserting a date.

Practical schedule: run Blocks 0–4 Stages A/B now (ranges + pruning); start the
Gate-3 weekly probe and its gate-history log immediately (2 jobs/week per pair,
~15 min); re-run Stages C/D/E when Gates 1 and 3 pass — *expected* around
mid-July at current trade frequency, but the gates, not the calendar, make the
call.

---

## Appendix A — Regime search-space implementation record (2026-06-10)

The four hardcoded regime constants (`_ER_WINDOW_CHOICES`, `_CHOP_ENTER_CHOICES`,
`_REGIME_CHOP_DEAD_BAND`, `_REGIME_TREND_PCT`) were removed and replaced by a fully
parametric search space matching the existing `GridSpec`/`SearchSpace` pattern.

**Key design decision — `chop_exit_pct` is derived, not searched.** Searching
`chop_exit_pct` directly would require a constraint `exit > enter` that breaks
TPE's fixed-space assumptions. Instead we search a `chop_dead_band` (the width of
the hysteresis gap) and compute `chop_exit_pct = chop_enter_pct + dead_band` at
evaluation time — orthogonal dimensions, constraint guaranteed by construction.

**Files changed:** `api/schemas.py` (new `RegimeSpace` model; `SearchSpace.regime`;
CURRENT-mode fields `chop_dead_band`/`trend_pct`; `CandidateResult` exposes the 4
fields), `trading/optimizer/search.py` (`RegimeSpace` dataclass, `_suggest_regime`
over `suggest_float` for ordinal TPE, `_format_env_lines` emits the computed
`ER_CHOP_EXIT_PCT`, `_candidate_signature` includes the new fields), plus rewritten
tests in `tests/unit/optimizer/test_search_regime.py` and
`tests/unit/optimizer/test_search_space.py`.

**Env lines emitted with regime enabled:**

```
XBTEUR_ER_WINDOW=32
XBTEUR_ER_CHOP_ENTER_PCT=0.33
XBTEUR_ER_CHOP_EXIT_PCT=0.40        ← computed: enter + dead_band
XBTEUR_ER_TREND_PCT=0.66
```

**Request formats per mode (verified working on jobs 35/36/37):**

CURRENT — evaluate live config with fixed regime params:

```json
{ "pair": "XBTEUR", "mode": "CURRENT", "fee_pct": 0.26,
  "regime_enabled": true,
  "er_window": 32, "chop_enter_pct": 0.33,
  "chop_dead_band": 0.07, "trend_pct": 0.66 }
```

OPTIMIZE — search regime dims via `search_space.regime` (`regime_enabled` is
**ignored** for OPTIMIZE/AUTO; regime is enabled iff `search_space.regime` is set):

```json
{ "pair": "XBTEUR", "mode": "OPTIMIZE", "fee_pct": 0.26, "n_trials": 800,
  "search_space": {
    "stop_pcts": {"start": 0.3, "end": 0.9, "step": 0.3},
    "k_act": {"start": 0.5, "end": 2.0, "step": 0.5},
    "min_margin": null,
    "regime": {
      "er_window":      {"start": 8,    "end": 96,   "step": 8},
      "chop_enter_pct": {"start": 0.10, "end": 0.50, "step": 0.10},
      "chop_dead_band": {"start": 0.03, "end": 0.18, "step": 0.03},
      "trend_pct":      {"start": 0.55, "end": 0.85, "step": 0.10}
    } } }
```

AUTO — same `search_space`, plus:

```json
"auto_settings": { "n_seeds": 4, "min_agree": 3, "trial_step": 500, "max_trials": 3000 }
```
