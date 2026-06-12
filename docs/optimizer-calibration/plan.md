# Optimizer Grid Calibration — Execution Plan

A self-contained, repeatable procedure to calibrate the full search space of the
BoTCoin optimizer (`POST /optimizer/jobs`). It is written to be executed by an AI
agent (or a human) **with no prior context**: every input is either discovered in
§1 or derived from the data volume. Do not assume anything about the host, the
configured pairs, the live config values, or how much OHLC history exists — the
plan tells you how to find out.

**Deliverable.** For each configured pair and each search dimension: a **range**,
a **step**, and a **search / fix / disable decision** — i.e. the validated
`search_space` JSON to use in production AUTO runs, plus the evidence trail behind
each choice. Record everything in `results.md` (same folder; it is a template —
copy it per campaign, e.g. `results-<campaign-id>.md`, or fill it in place for the
first campaign).

**Why calibration is needed.** Every search dimension is a request input
(`SearchSpace` / `RegimeSpace` of `GridSpec{start, end, step}`); there are no
built-in grids. A mis-designed grid fails in one of two opposite ways:

- **Over-coverage / overfitting** — range too wide or step too fine for the data
  volume: the space is huge, the TPE sampler exploits noise, seeds never agree on
  a config, `train_pnl ≫ test_pnl`.
- **Under-coverage / missing values** — range too narrow or step too coarse: the
  real optimum sits *outside* the grid (winner pinned at an edge) or *between*
  grid points (coarse step skips the basin).

---

## 1. Prerequisites and environment discovery

Complete every step in this section before launching any job, and record the
findings in the **Environment** block of `results.md`.

### 1.1 Services and access

- The optimizer runs inside the `botc` service (FastAPI on port **8000**; from
  another container on the same Docker network use `http://botc:8000`, from the
  host `http://localhost:8000`).
- All endpoints require the **`X-Api-Token`** header. The token is the
  `API_SECRET_TOKEN` env var of the `botc` service.
- The optimizer must be enabled: `MAX_CONCURRENT_JOBS ≥ 1` on the `botc` service.
  A submission returns `503` if disabled, `409` if all job slots are busy (wait
  for the running job to finish and resubmit — do not parallelize jobs of this
  plan; later jobs depend on earlier verdicts).
- PostgreSQL access (the `postgres` service) is needed only for the data-window
  query in §1.2; everything else goes through the API.

### 1.2 Discover the pairs and the data window

**Pairs:** the `PAIRS` env var of the `botc` service (comma-separated, e.g.
`XBTEUR,ETHEUR`). The API rejects unknown pairs with `400`. The whole plan is
executed **per pair** — pairs are calibrated independently and may legitimately
end with different grids and verdicts.

**Data window:** run against the project database:

```sql
SELECT pair,
       timeframe_minutes,
       COUNT(*)                  AS candles,
       to_timestamp(MIN(time))   AS from_ts,
       to_timestamp(MAX(time))   AS to_ts
FROM ohlc_data
GROUP BY pair, timeframe_minutes;
```

Define, per pair:

- **T0 / T1** — first / last candle date (`YYYY-MM-DD`; the optimizer `start` /
  `end` request fields take this format).
- **D** — days of history, `(T1 − T0)` in days.

Kraken's public OHLC API caps backfill at ~720 candles per timeframe (~7.5 days at
15m), so history only accumulates forward — **D is whatever the instance has
ingested**, and every threshold below is expressed in terms of D, never as a
calendar date.

### 1.3 Derived request parameters

Compute once per campaign and use in **every** job:

| Parameter | Value | Rationale |
|---|---|---|
| `fee_pct` | The account's real round-trip fee in percent (Kraken taker tier-0 = `0.4`) | PnL without fees is fiction |
| `min_ops` | `round(D / 3)` | Rejects degenerate candidates that barely trade; scales with the window |
| `min_test_ops` | `max(2, round(D / 15))` | Same, for the test slice — critical for regime configs that can filter out nearly all trading and post a flat ~0% that "beats" honest negative configs |
| `train_split` | `0.67` — **all jobs, always** (the API default is `0.8`, so set it explicitly in every request) | One standard value keeps full-window and Stage-D window results directly comparable, and the larger test slice reaches Gate 1 (≥20 test ops) at ~60 days instead of ~100 at the API default |

**Sanity check on D before starting:** with the strategy's historically observed
frequency of **~1 closed op/day**, a pair needs roughly `D ≥ 30` for the train
slice (`0.67 × D` ops) to hold the 20–30 ops that make OPTIMIZE results
meaningful at all. If `D < 30` for a pair, run only Block 0 and the §6 weekly probes for it, and revisit
when D grows. (Verify the actual ops/day from the Block-0 result: `train_ops +
test_ops` of the top candidate, divided by D — record it; it recalibrates all gate
expectations.)

### 1.4 How to run a job

Submit (returns `202` with a sequential `job_id`):

```bash
curl -s -X POST "$BASE/optimizer/jobs" \
  -H "X-Api-Token: $TOKEN" -H "Content-Type: application/json" \
  -d @request.json
```

Poll until `status` is `completed` or `failed` (jobs are asynchronous):

```bash
curl -s "$BASE/optimizer/jobs/<job_id>" -H "X-Api-Token: $TOKEN"
```

Observed wall times at ~3 000 candles (scale linearly with candle count):
CURRENT ≈ 1–2 min (poll every 30 s) · OPTIMIZE 400 trials ≈ 10–15 min, 800 ≈
20–30 min (poll every 60 s) · AUTO ≤ 90 min (poll every 2–3 min).

**Reading a result** (`result` field of the job status):

- `top_candidates` — ranked by `robust_pnl_pct = min(train_pnl_pct,
  test_pnl_pct)`. Each candidate carries its full config (`k_act`, `min_margin`,
  `stop_pcts`, the four regime fields) **and** its evidence: `train_pnl_pct`,
  `test_pnl_pct`, `robust_pnl_pct`, `train_ops`, `test_ops`, and
  `chop_transitions` (CHOP↔non-CHOP crossings of the candidate's classifier;
  `null` when the regime gate is off). `train_ops`/`test_ops` feed Gate 1 and
  `chop_transitions` feeds Gate 2 (§6) directly — no estimation needed.
- `suggested_env_lines` — the winner as deployable `.env` lines.
- `auto` (AUTO only) — `converged`, `n_seeds_agreed`, `seeds_used`.
- Every job stores its full request in `optimizer_jobs.request`, so runs are
  self-documenting and reproducible; the `results.md` log only needs the verdict
  trail.

### 1.5 Discover the live reference config (read, never assume)

This plan never hardcodes the live `.env` values. Obtain them from the Block-0
no-regime CURRENT job (§4, Block 0): the top candidate echoes the active
`stop_pcts`, `k_act` and `min_margin`. Those values are the **live reference**
used throughout the plan wherever a dimension must be held at a known-good point.
The four regime dimensions have **code defaults** (`er_window=32`,
`chop_enter_pct=0.33`, `chop_dead_band=0.07`, `trend_pct=0.66`) which serve as
their reference; a fresh install typically has no regime vars in `.env`, so the
request is the only source for them.

---

## 2. What is being calibrated

### 2.1 Dimension inventory

| Dimension | Branch | Domain | Reference point | Dims |
|---|---|---|---|---|
| `stop_pcts` (one grid, searched independently per volatility level LL/LV/MV/HV/HH) | both | [0, 1] | live reference (§1.5) | 5 |
| `k_act` | K_ACT only | ≥ 0 (`0` = immediate activation, a real value — not "unset") | live reference, if set | 1 |
| `min_margin` | MIN_MARGIN only | ≥ 0 (fraction of entry price) | live reference | 1 |
| `er_window` | both (if `regime` set) | int ≥ 2 (grid step ≥ 1) | code default 32 | 1 |
| `chop_enter_pct` | both (if `regime` set) | [0, 1] | code default 0.33 | 1 |
| `chop_dead_band` | both (if `regime` set) | [0, 1] (`chop_exit_pct = enter + band`, by construction — never searched directly, see Appendix A) | code default 0.07 | 1 |
| `trend_pct` | both (if `regime` set) | [0, 1] | code default 0.66 | 1 |

### 2.2 Structural facts that shape the plan

- **Two independent branches, budget split evenly.** Every search runs a `K_ACT`
  activation branch and a `MIN_MARGIN` branch as separate studies, merged and
  ranked together; `n_trials` is divided across the active branches. Setting
  `"k_act": null` or `"min_margin": null` disables that branch and gives the
  survivor the **whole** budget — use this when calibrating one activation family
  so trials aren't wasted on the other. At least one branch must be active.
- **`start == end` fixes a dimension** (1 value, still emitted in the config) —
  the tool for "don't search this, hold it constant".
- **`"regime": null` removes 4 dimensions at once.** Blocks 1–3 run regime-off so
  the activation/stop grids are calibrated on a smaller space first. Regime is
  enabled iff `search_space.regime` is set (OPTIMIZE/AUTO) or
  `current_params.regime` is set (CURRENT).
- **Grid validity (enforced by the API, `422` on violation):** `step > 0`,
  `start ≤ end`, and `(end − start)` an integer multiple of `step`. Percentage
  grids must lie in [0, 1]; `k_act`/`min_margin` grids ≥ 0; `er_window` start
  ≥ 2. Check every grid you compose against these rules before submitting.
- **CURRENT-mode pinning.** `current_params` accepts `stop_pcts` (all 5 keys
  required if given), `k_act`, `min_margin` and `regime`; each field set
  **replaces** the value read from the live `.env`, and each field left `null`
  **falls back to the live value**. For reproducible sensitivity runs (Stage B),
  set *every* field explicitly so the evaluation doesn't silently depend on the
  host's `.env`. Caveat: there is no way to *unset* a live `K_ACT` via
  `current_params` (`k_act: 0` means immediate activation, not "disabled") — if
  you need a margin-activation baseline on a host whose live config uses `K_ACT`,
  note the limitation in the log rather than faking it.

### 2.3 Combinatorics worksheet

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

Heuristic gates used throughout (rules of thumb, not theory):

- **Discovery runs:** 5–7 values per searched dim is enough to see the landscape.
- **AUTO convergence runs:** the branch space should be small enough that exact
  config agreement between seeds is *possible*, not a lottery — target ≲ a few
  thousand combinations per branch with `max_trials: 3000`. After Blocks 1–4,
  most dims must end up **fixed** or at 3–4 values.
- **Ops budget:** the train slice holds roughly `D × ops/day × train_split`
  closed ops. Searching 10+ dims against a two-digit op count is structurally
  overfit; the sensitivity stage (B) exists to cut the searched-dim count down
  before any AUTO run.

---

## 3. The calibration method (applied to every block)

Five stages, each a go/no-go gate. Stages A–C calibrate the grid; D–E validate
it. Record every job and verdict in the `results.md` Job Log as you go.

### Stage A — Range discovery (OPTIMIZE, wide + coarse)

One family searched at a time; all other dims fixed (`start == end` at their
reference point, §1.5) or disabled. Wide range, coarse step, 400–800 trials.

**Edge rule (fixes under-coverage by construction):** if the winner — or ≥2 of
the top-5 — sits at a grid boundary, extend the range 50% past that edge and
re-run. Repeat until the winner is interior, with two qualifications learned the
hard way:

- A dimension that keeps diverging toward an edge after two extensions is telling
  you something structural (e.g. `k_act → 0` means "immediate activation is just
  better"; a stop level pinned at the 0.0/1.0 **domain** boundary means the domain
  ends there, not that the grid is short); record it and fix the dim there.
- **Extension can land in an overfitting basin:** if the extended range produces
  a new winner whose `robust_pnl` is *worse* than the original interior winner,
  the extension found noise, not signal — revert to the pre-extension winner.

**Cluster read:** top-5 clustered in one zone → real basin, proceed. Scattered →
note it; the dimension may be noise-dominated at this data volume (Stage B will
confirm).

### Stage B — Sensitivity classification (CURRENT, cheap)

Perturb each dim of the Stage-A winner by ±1 step, one at a time, via CURRENT
jobs. Pin **all** companion values explicitly through `current_params`
(`stop_pcts` + activation + `regime`) at the Stage-A winner — never let
companions fall back to the live `.env`, or the gradients are measured around the
wrong point. Run the unperturbed winner first as the baseline.

- **Dead** (|Δ robust_pnl| < ~0.5% for both perturbations) → **fix it** at the
  winner value (`start == end`). Every fixed dim shrinks the space
  multiplicatively and is the single most effective anti-overfitting move
  available.
- **Live** (steep gradient) → keep searching it; it earns a place in the final
  grid.
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

At low data volumes (D ≲ 45), ties break toward coarse, always.

### Stage D — Stability cross-checks (OPTIMIZE, 400 trials each)

Run the calibrated family grid on:

- **Two overlapping temporal windows**, each covering two-thirds of the data
  (the standard `train_split: 0.67` applies here as everywhere):
  - Window AB: `start = T0`, `end = T0 + ceil(2D/3)` days
  - Window BC: `start = T1 − ceil(2D/3)` days, `end = T1`
  - If a window job fails for insufficient ops (low-frequency pair), lower
    `min_ops` proportionally to the window length and retry **once**; if it still
    fails, that pair cannot pass Stage D at this D — record it as a Gate-1
    blocker (§6) and fix the dim at its reference point.
- **Every configured pair.** Winning *zones* don't need to match across pairs —
  per-pair configs differ legitimately — but a grid that pins **all** pairs'
  winners at the same edge is a miscalibrated grid, not a coincidence.

Same-zone winners across windows → the range/step survive. Different zones →
the dimension has no temporally stable optimum yet; fix it at its reference
point and revisit once the §6 gates pass.

### Stage E — AUTO as the final exam *of the grid*

One AUTO run per pair with the fully calibrated `search_space` (all blocks
merged):

```json
"auto_settings": { "n_seeds": 4, "min_agree": 3, "trial_step": 500, "max_trials": 3000 }
```

(Set `max_trials` explicitly — the API default is much higher and wastes hours on
a grid this size. AUTO judges convergence on the **config**: seeds are grouped by
their top candidate's exact param signature, not by score.)

- Converges (`auto.converged: true`) → the grid is **AUTO-ready**; record
  `suggested_env_lines` as a deploy candidate (subject to the §6 gates).
- Doesn't converge → the searched space is still too large for the data. Two
  targeted retries before parking:
  1. If one branch never appears in `top_candidates` across seeds, **disable it**
     (`null`) and re-run — a branch that never wins only burns budget.
  2. Fix the weakest *live* dims (lowest Stage-B gradient) and re-run.
  If it still fails, park until the §6 gates pass. **Non-convergence here is a
  data-volume verdict, not a failed experiment** — write it down, and record the
  best candidate as "best available (not deploy-ready)".

---

## 4. Execution order (blocks)

Ordered so each block inherits fixed values from the previous one. Run blocks
sequentially, per pair. Every example below uses placeholders — substitute the
discovered pair, the §1.3 derived parameters, and the references from §1.5.
`"fee_pct"`, `"min_ops"`, `"min_test_ops"` and `"train_split": 0.67` (§1.3) go
in **every** request even where the examples omit them for brevity.

### Block 0 — Baselines (2 CURRENT jobs per pair)

Reference points for every later comparison — and the source of the live
reference config (§1.5). Per pair:

```json
// 0a: live config, no regime
{ "pair": "<PAIR>", "mode": "CURRENT", "fee_pct": <FEE> }

// 0b: live config + regime at code defaults
{ "pair": "<PAIR>", "mode": "CURRENT", "fee_pct": <FEE>,
  "current_params": { "regime": { "er_window": 32, "chop_enter_pct": 0.33,
                                  "chop_dead_band": 0.07, "trend_pct": 0.66 } } }
```

**Read and record:** the echoed live config (0a top candidate) → this is the
live reference. `train_ops + test_ops` → ops/day (recalibrates §1.3 and the §6
gates). Does `robust_pnl(0b) > robust_pnl(0a)`? If not, the regime defaults are
misconfigured for this pair — useful prior before Block 4. `test_ops` → Gate-1
status today.

### Block 1 — `stop_pcts` (regime off)

The 5 stop dims dominate the space (power of 5), so their step matters most.

```json
// 1a — discovery, K_ACT branch only (full budget on one branch);
//      k_act fixed at the live reference if set, else at 1.0
{ "pair": "<PAIR>", "mode": "OPTIMIZE", "n_trials": 600,
  "search_space": {
    "stop_pcts": {"start": 0.05, "end": 0.95, "step": 0.15},
    "k_act":     {"start": <K_REF>, "end": <K_REF>, "step": 0.5},
    "min_margin": null, "regime": null } }

// 1b — same but MIN_MARGIN branch only:
//      "k_act": null, "min_margin": {"start": <MM_REF>, "end": <MM_REF>, "step": 0.004}
```

Expect *live* and spread-out dims. Stage B here is 10 CURRENT jobs per branch
(5 levels × ±1 step) — worth it: any level classified *dead* (often the levels
with few sessions, LL/HH) gets fixed and takes a factor of ~7 out of the space.
Stage C: step 0.15 vs 0.075. Edge rule: extensions stop at the [0, 1] domain —
a winner at exactly 0.00 or 1.00 is a structural fix, not under-coverage.

**Expected outcome:** a per-level verdict — typically 2–3 live levels searched at
step 0.15–0.30 within [0.2, 0.95], the rest fixed.

### Block 2 — `k_act` (regime off, `"min_margin": null`)

```json
"stop_pcts": {"start": 0.30, "end": 0.90, "step": 0.30},   // coarse 3-value placeholder
"k_act":     {"start": 0.0,  "end": 3.0,  "step": 0.5},    // includes 0 = immediate
"min_margin": null, "regime": null
```

Note the trade-off: stops are *searched coarsely* (not fixed) so `k_act` is
evaluated against a tolerant stop landscape rather than one frozen point. Edge
rule applies at 3.0 (extend to 4.5 if pinned — and remember the
overfitting-basin caveat from Stage A: if the extended winner has worse robust
than the original, revert). If the live config has no `K_ACT` and Stage B shows
the whole branch underperforming the MIN_MARGIN baseline, `"k_act": null` is the
*calibration outcome* for this dataset.

### Block 3 — `min_margin` (regime off, `"k_act": null`)

```json
"stop_pcts": {"start": 0.30, "end": 0.90, "step": 0.30},
"k_act": null, "regime": null,
"min_margin": {"start": 0.000, "end": 0.020, "step": 0.004}   // 6 values
```

Make sure the live reference value lands **on** the grid (adjust start/step if
needed). Edge rule: 0.000 is the domain floor — a winner there is a fix
candidate, not under-coverage. If pinned at 0.020, extend to 0.032.

### Block 4 — Regime dims (4 dims)

Companions for every job in this block: the **calibrated stop/activation grids
from Blocks 1–3** (not wide placeholders), so the regime dims are calibrated
against realistic companions.

**Stage A — discovery (800 trials):**

```json
"regime": {
  "er_window":      {"start": 8,    "end": 96,   "step": 8},
  "chop_enter_pct": {"start": 0.10, "end": 0.50, "step": 0.10},
  "chop_dead_band": {"start": 0.03, "end": 0.18, "step": 0.03},
  "trend_pct":      {"start": 0.55, "end": 0.85, "step": 0.10}
}
```

Run Stage A **at least twice with different `seed` values** before trusting the
winner — regime dims are the most noise-prone family; params that hold across
seeds are the real signal, params that jump (commonly `trend_pct`) are
seed-noise and likely Stage-B *dead*. Edge rule applies per dim (`er_window`
pinned at 96 → extend to 144; `chop_enter_pct` pinned at 0.50 → extend to 0.70;
etc.). `chop_exit_pct` is **derived** (`enter + dead_band`) — never search it
(Appendix A).

**Read `chop_transitions` of the winner now (Gate 2, §6):** if the window holds
< ~6 CHOP↔non-CHOP transitions, the chop filter was never exercised and *no
result in this block can validate the regime dims* — record the block as
Gate-2-blocked and fix all four dims at their code defaults.

**Stage B — sensitivity (8 CURRENT jobs):** perturb each of the 4 winner params
±1 step with **everything** pinned via `current_params` (stops, activation, the
other three regime params) at the Stage-A winner.

**Stage C — step comparison (2 jobs, same n_trials):** coarse (3 values per
live dim) vs fine (5+ values per live dim), centered on the Stage-A winner zone.

**Stage D — temporal windows + cross-pair (per §3):** do the AB/BC winners share
the same `er_window` and `chop_enter_pct` zone? Consistent zone across windows →
evidence of a generalizable signal. A dim that is Stage-B *live* but Stage-D
*unstable* gets **fixed at its code default** — a steep gradient with no
temporally stable optimum is noise, not signal.

### Block 5 — Integrated AUTO (Stage E, 1–2 jobs per pair)

Merge every surviving grid into one `search_space` and run AUTO per pair (§3
Stage E settings and retry ladder). Before launching, recompute the branch space
with the §2.3 formula and sanity-check it against the convergence heuristic; if
it's still ≫ a few thousand combinations per branch, fix more dims first — don't
burn 90 minutes to confirm arithmetic.

---

## 5. Decision-rule reference

| Signal | Diagnosis | Action |
|---|---|---|
| Winner (or ≥2 of top-5) at grid edge | under-coverage | Extend range 50%, re-run Stage A |
| Winner at the **domain** boundary (0.0/1.0 for pcts, 0 for min_margin) | structural | Fix the dim there — the domain ends, the grid doesn't |
| Extended range finds new winner with *worse* robust_pnl | overfitting basin | Revert to the pre-extension winner |
| Steep CURRENT gradient at range boundary | under-coverage | Extend range |
| Fine grid relocates winner between coarse points, robust_pnl ≥, seed-stable | under-coverage (step) | Adopt finer step |
| `train_pnl − test_pnl` > 5 percentage points | overfitting | Coarsen/shrink; distrust the candidate |
| Top-5 scattered across zones | overfitting / noise | Stage B; likely fix the dim |
| Fine grid inflates robust_pnl, winner jumps zone | overfitting (step) | Keep coarse step |
| Stage-A winner params differ across seeds | noise-dominated | Trust only the seed-stable params; the rest are Stage-B candidates for *dead* |
| Temporal windows disagree on zone | no temporally stable optimum | Fix dim at its reference point, revisit when §6 gates pass |
| Stage-B *live* but Stage-D *unstable* | noise gradient | Fix at reference — stability outranks sensitivity |
| All pairs pinned at the same edge | grid miscalibration | Extend range (this one is on the grid, not the data) |
| One branch never appears in AUTO top candidates | dead branch | Disable it (`null`) and re-run |
| AUTO non-convergence on a trimmed grid | data volume | Park; re-run when §6 gates pass |
| Window job fails `min_ops` | data volume (window too short) | Lower `min_ops` proportionally, retry once; then record as Gate-1 blocker |
| Dim dead in Stage B (<0.5% Δ) | n/a | Fix it (`start == end`) — the default win |

---

## 6. Data-sufficiency gates — when conclusions can be trusted

Statistical verdicts from a thin window measure single-trade luck, not configs
(with a handful of test ops, one trade swings PnL by several percentage points
and `min(train, test)` is a coin flip). No fixed number of days has been proven
"enough"; sufficiency is measured by three gates. A conclusion is trustworthy
when the relevant gate passes — whatever D that takes.

**Gate 1 — test-slice op count.** The test slice must hold **≥ 20 closed ops**
(point-estimate noise shrinks ~1/√n). Read it directly from `test_ops` of any
CURRENT job's top candidate. The split lever is already pre-applied (the
standard `train_split: 0.67` maximizes the test slice without starving the train
side); the remaining lever is walk-forward, so every op is a test op once.

**Gate 2 — regime-episode count (Block 4 only).** The window must contain
**≥ ~6 CHOP↔non-CHOP transitions** under the candidate classifier — read the
`chop_transitions` field of the candidate. If the whole window is one trend, the
chop filter was never exercised and no op count can validate it; a window that
fails this gate cannot validate regime dims regardless of Gate 1.

**Gate 3 — verdict stability under growing data (the actual empirical test).**
Pin one CURRENT job (live config) and one OPTIMIZE job (fixed grid, fixed
`seed`) per pair and re-run them **weekly** as history accumulates. Data is
sufficient when the verdicts stop flipping across ~3 consecutive weeks:
`robust_pnl` keeps its sign and the OPTIMIZE winner stays in the same zone. This
converts "is it enough yet?" from an assumption into a measurement — and it is
the only gate that directly tests the thing we care about (conclusions that
survive new data).

Append one row per pair per week to the **Gate History** table in `results.md`
(format in the template). `G3 stable?` flips to **yes** after ~3 consecutive
rows with the same `robust_pnl` sign and winner zone. The first week where a
pair shows G1 ✓ **and** G3 ✓ (plus G2 ✓ if regime dims are in play) is the
trigger to re-run Stages C/D/E for that pair.

### Repetition map — what to re-run when the gates pass

| Stage | Repeat later? | Why |
|---|---|---|
| Block 0 (baselines) | **Yes** (trivial) | Re-anchors every comparison to the longer window |
| Stage A (ranges) | **Only if** a dim hit the edge rule, or new market regimes appear in the data | Ranges are mostly parameter geometry, not statistics — they should hold |
| Stage B (dead/live) | **Yes** (cheap) | A dim that looks dead on 30–60 ops may show a real gradient at 100+ ops |
| Stage C (step) | **Yes** | Step verdicts are pure data-volume calls; "ties break coarse" stops applying as the test window grows |
| Stage D (stability) | **Yes — upgraded** | With G1 passed use **3** windows (or proper walk-forward) instead of 2 overlapping ones |
| Stage E (AUTO) | **Yes** | The re-run that passes the gates is the one whose config ships to production |

In short: **ranges learned now persist; everything statistical gets re-run.**
The first pass is never wasted — it prunes dimensions (Stage-B fixes),
establishes ranges, and produces the negatives that tell you what *not* to
search.

---

## 7. Recording results

Log every job in the `results.md` Job Log **as it completes** (one row per job),
fill the per-block verdict tables when a block closes, and keep the Gate History
current. At campaign end, complete the Final Calibration Summary: the
per-dimension verdict table, the validated `search_space` JSON per pair, deploy
candidates (with their convergence evidence and gate status), and the parked
items with their re-run triggers. The template documents each section's format.

---

## Appendix A — Regime filter request reference

The regime filter gates trading on an Efficiency-Ratio chop/trend classifier.
Its four searchable dimensions are `er_window`, `chop_enter_pct`,
`chop_dead_band`, `trend_pct`.

**`chop_exit_pct` is derived, never searched.** Searching it directly would
require a constraint `exit > enter` that breaks TPE's fixed-space assumptions;
instead the search owns `chop_dead_band` (the hysteresis-gap width) and the
engine computes `chop_exit_pct = chop_enter_pct + dead_band` at evaluation time —
orthogonal dimensions, constraint guaranteed by construction. The emitted env
lines therefore include the *computed* exit:

```
<PAIR>_ER_WINDOW=32
<PAIR>_ER_CHOP_ENTER_PCT=0.33
<PAIR>_ER_CHOP_EXIT_PCT=0.40        ← computed: enter + dead_band
<PAIR>_ER_TREND_PCT=0.66
```

**Request formats per mode:**

CURRENT — evaluate a fixed config; `current_params` fields override the live
`.env` (omitted fields fall back to it, see §2.2); `regime` present = gate on,
absent = gate off:

```json
{ "pair": "<PAIR>", "mode": "CURRENT", "fee_pct": 0.4,
  "current_params": {
    "stop_pcts": {"LL": 0.60, "LV": 0.90, "MV": 0.60, "HV": 0.30, "HH": 0.30},
    "k_act": 2.5,
    "regime": { "er_window": 32, "chop_enter_pct": 0.33,
                "chop_dead_band": 0.07, "trend_pct": 0.66 } } }
```

OPTIMIZE — search regime dims via `search_space.regime` (`current_params` is
ignored for OPTIMIZE/AUTO):

```json
{ "pair": "<PAIR>", "mode": "OPTIMIZE", "fee_pct": 0.4, "n_trials": 800,
  "min_ops": 10, "min_test_ops": 2, "train_split": 0.67,
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

Window-sliced jobs add `"start"` / `"end"` (`YYYY-MM-DD`); `train_split` stays
at the standard `0.67`. A sliced job recomputes calibration from the slice.
