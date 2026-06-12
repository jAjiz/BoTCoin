# Optimizer Grid Calibration — Results

> Template for one calibration campaign of [plan.md](plan.md). Fill the
> Environment block before launching any job; log every job as it completes;
> close each block with its verdict table; finish with the Final Calibration
> Summary. Em-dash placeholder rows show the expected format — replace them.

**Campaign started:** —
**Executed by:** —

---

## Environment (plan §1)

| Field | Value |
|---|---|
| API base URL | — |
| Pairs (`PAIRS`) | — |
| Data window T0 → T1 | — |
| D (days of history) | — |
| Candles per pair / timeframe | — |
| `fee_pct` (account round-trip fee; Kraken taker tier-0 = `0.4`) | 0.4 |
| `min_ops` (= round(D/3)) | — |
| `min_test_ops` (= max(2, round(D/15))) | — |
| `train_split` (standard `0.67`, all jobs) | 0.67 |
| Window AB (start–end) | — |
| Window BC (start–end) | — |
| Observed ops/day (from Block 0) | — |
| Live reference config per pair (from Block 0a) | — |

---

## Gate History (weekly, plan §6)

One row per pair per week, from the pinned Gate-3 probe pair (1 CURRENT + 1
OPTIMIZE, fixed grid, fixed seed). `test_ops` and `episodes` (`chop_transitions`)
come straight from the CURRENT result; `winner zone` is the OPTIMIZE winner's
params rounded to grid points. `G3 stable?` → **yes** after ~3 consecutive rows
with same `robust_pnl` sign and winner zone.

| date | pair | days | test_ops (G1 ≥20) | episodes (G2 ≥6) | robust_pnl sign | winner zone | G3 stable? | gates passed |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — |

**Pinned probe requests:** *(record both request JSONs — or their job ids —
here once, so the weekly re-run is byte-identical)*

---

## Job Log

One row per job, appended as each completes. `grid (changed dims)` lists only
what differs from the block's template; the full request is stored in
`optimizer_jobs.request`. `edge?` names any dim pinned at a grid boundary.

| job | block/stage | pair | window | grid (changed dims) | n_trials | winner | train | test | robust | edge? | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — | — | — | — |

---

## Block verdicts

Close each block with a per-dimension table (one table per pair where verdicts
differ). `final decision` is one of: **search [start,end,step]** · **fix at X**
· **disable (null)**.

### Block 1 — stop_pcts — `<PAIR>`

| level | Stage A | Stage B | Stage C/D | final decision |
|---|---|---|---|---|
| LL | — | — | — | — |
| LV | — | — | — | — |
| MV | — | — | — | — |
| HV | — | — | — | — |
| HH | — | — | — | — |

### Block 2 — k_act — `<PAIR>`

| Stage A | Stage B | Stage D | final decision |
|---|---|---|---|
| — | — | — | — |

### Block 3 — min_margin — `<PAIR>`

| Stage A | Stage B | Stage D | final decision |
|---|---|---|---|
| — | — | — | — |

### Block 4 — regime dims — `<PAIR>`

| dim | Stage A (seed-stable?) | Stage B | Stage D | final decision |
|---|---|---|---|---|
| er_window | — | — | — | — |
| chop_enter_pct | — | — | — | — |
| chop_dead_band | — | — | — | — |
| trend_pct | — | — | — | — |

Gate-2 check (`chop_transitions` of the Stage-A winner): —

---

## Block 5 — AUTO results

One subsection per pair.

### `<PAIR>`

- **Converged:** — (`n_seeds_agreed`/`n_seeds`, trials used)
- **Retries applied:** — (branch disabled? dims fixed?)
- **Winner / best available:** —
- **Gate status at time of run:** G1 — · G2 — · G3 —

---

## Final Calibration Summary

### Dimension verdicts

| dim | `<PAIR_1>` decision | `<PAIR_2>` decision |
|---|---|---|
| stop_pcts | — | — |
| k_act | — | — |
| min_margin | — | — |
| er_window | — | — |
| chop_enter_pct | — | — |
| chop_dead_band | — | — |
| trend_pct | — | — |

### Validated `search_space` per pair

The deliverable: paste the final JSON to use in production AUTO runs.

```json
// <PAIR_1>
{ "stop_pcts": ..., "k_act": ..., "min_margin": ..., "regime": ... }
```

### Deploy candidates

Only configs from a **converged** AUTO run qualify; gate caveats stay attached.

```
# <PAIR> — converged ?/?, subject to gates: G1 — · G2 — · G3 —
<suggested_env_lines>
```

### Parked items / re-run triggers

| item | blocked by | re-run trigger | pinned search space (job id) |
|---|---|---|---|
| — | — | — | — |
