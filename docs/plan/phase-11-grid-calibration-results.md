# Phase 11 – Grid Calibration Results

**Branch:** `feature/phase-11-trend-chop-regime-filter`
**Started:** 2026-06-11

---

## Gate History

| date | pair | days | test_ops (G1 ≥20) | episodes (G2 ≥6) | robust_pnl sign | winner zone | G3 stable? | gates passed |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — |

*(`train_ops` / `test_ops` and `chop_transitions` are exposed per candidate in the
optimizer result as of 2026-06-12 — read G1 and G2 directly from any CURRENT job)*

---

## Job Log

| job | block/stage | pair | window | grid (changed dims) | n_trials | winner | train | test | robust | edge? | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 38 | B0/baseline | XBTEUR | full 31d | no-regime CURRENT | 1 | stops: LL=0.95/LV=0.65/MV=0.60/HV=0.70/HH=0.35, min_margin=0 | -1.14% | +3.16% | -1.14% | n/a | reference |
| 39 | B0/baseline | XBTEUR | full 31d | regime defaults (ER=32, enter=0.33, band=0.07, trend=0.66) | 1 | same stops | -2.08% | +5.50% | -2.08% | n/a | regime worse by robust (-2.08 vs -1.14); defaults misconfigured |
| 40 | B0/baseline | ETHEUR | full 31d | no-regime CURRENT | 1 | stops: LL=0.25/LV=0.35/MV=0.50/HV=0.65/HH=0.80, min_margin=0.01 | -4.61% | -9.91% | -9.91% | n/a | reference |
| 41 | B0/baseline | ETHEUR | full 31d | regime defaults | 1 | same stops | -2.74% | -9.39% | -9.39% | n/a | regime marginally better (+0.52%); correct direction |
| 42 | B1/stageA | XBTEUR | full 31d | stops[0.05,0.95,0.15] k_act=1.0 fixed, MM null | 600 | LL=0.80/LV=0.95/MV=0.95/HV=0.95/HH=0.35 | -2.08% | -3.72% | -3.72% | LV/MV/HV@0.95 (upper) | edge rule triggered; re-run with extended range |
| 43 | B1/stageA | XBTEUR | full 31d | stops[0.05,0.95,0.15] k_act null, MM=0.010 fixed | 600 | LL=0.05/LV=0.05/MV=0.80/HV=0.65/HH=0.20 | -0.16% | -0.73% | -0.73% | LV@0.05 (lower) | edge rule triggered; re-run with extended range |
| 44 | B1/stageA-v2 | XBTEUR | full 31d | stops[0.00,1.00,0.20] k_act=1.0 fixed, MM null | 600 | LL=0.00/LV=1.00/MV=0.60/HV=0.20/HH=0.40 | -1.74% | -3.08% | -3.08% | LV@1.00 (domain ceiling) | 2nd extension still edge-pinned → structural fix: LV=1.00 |
| 45 | B1/stageA-v2 | XBTEUR | full 31d | stops[0.00,1.00,0.20] k_act null, MM=0.010 fixed | 600 | LL=0.40/LV=0.20/MV=0.40/HV=0.00/HH=0.80 | -2.57% | +6.66% | -2.57% | HV@0.00 (domain floor) | LV resolved interior; HV at floor → structural fix: HV=0.00 |
| 46 | B1/stageA | ETHEUR | full 31d | stops[0.00,1.00,0.20] k_act=1.0 fixed, MM null | 600 | LL=0.60/LV=1.00/MV=1.00/HV=0.00/HH=0.80 | +0.21% | +2.25% | +0.21% | LV@1.00, MV@1.00, HV@0.00 | structural: LV=MV=1.00, HV=0.00 for K_ACT branch |
| 47 | B1/stageA | ETHEUR | full 31d | stops[0.00,1.00,0.20] k_act null, MM=0.010 fixed | 600 | LL=0.80/LV=0.00/MV=0.80/HV=0.00/HH=0.00 | +41.25% | +14.37% | +14.37% | HV@0.00, HH@0.00, LV@0.00 | large train/test gap (27%) — suspect; stage D will validate |
| 48 | B1/stageD | XBTEUR | AB (21d) | stops[0.00,1.00,0.20] k_act null, MM=0.010 | 400 | — | — | — | — | FAILED: insufficient ops even at min_ops=5; Gate 1 unmet for XBTEUR |
| 49 | B1/stageD | ETHEUR | AB (21d) | stops[0.00,1.00,0.20] k_act null, MM=0.010 | 400 | LL=0.00/LV=0.40/MV=0.00/HV=1.00/HH=0.00 | +8.75% | +8.04% | +8.04% | HV@1.00 | HV flipped from full-window (0.00→1.00); instability signal |
| 50 | B1/stageD | XBTEUR | AB (21d) | same, min_ops=5 | 400 | — | — | — | — | FAILED again; XBTEUR insufficient ops in any 14d window |
| 51 | B1/stageD | XBTEUR | BC (21d) | stops[0.00,1.00,0.20] k_act null, MM=0.010, min_ops=5 | 400 | LL=0.80/LV=0.00/MV=0.60/HV=0.20/HH=0.60 | -11.76% | +6.52% | -11.76% | — | 4/5 dims differ from full-window; temporal instability |
| 52 | B1/stageD | ETHEUR | BC (21d) | stops[0.00,1.00,0.20] k_act null, MM=0.010 | 400 | LL=0.60/LV=0.60/MV=0.00/HV=1.00/HH=0.80 | +5.25% | +5.81% | +5.25% | — | HV=1.00 again (consistent with AB); but flips vs full-window; instability |
| 53 | B2/stageA | XBTEUR | full 31d | stops[0.30,0.90,0.30] k_act[0.0,3.0,0.5] MM null | 600 | k=2.5 LL0.9/LV0.6/MV0.6/HV0.3/HH0.3 | +4.93% | +3.11% | +3.11% | k=2.5 (interior) | k_act=2.5 in 5/5; stable interior; LIVE at 2.5 |
| 54 | B2/stageA | ETHEUR | full 31d | stops[0.30,0.90,0.30] k_act[0.0,3.0,0.5] MM null | 600 | k=2.0 LL0.3/LV0.6/MV0.9/HV0.3/HH0.3 | +1.71% | +1.48% | +1.48% | k=3.0 in 3/5 (upper edge) | edge rule triggers; extended to 4.5 |
| 55 | B2/stageA-v2 | ETHEUR | full 31d | stops[0.30,0.90,0.30] k_act[0.0,4.5,0.5] MM null | 600 | k=4.0 | +0.30% | -0.14% | -0.14% | k=4.0 interior | worse robust than original; extension found overfitting basin; revert to k=2.0 winner |
| 56 | B3/stageA | XBTEUR | full 31d | stops[0.30,0.90,0.30] k_act null MM[0,0.020,0.004] | 600 | mm=0.000 LL0.6/LV0.3/MV0.6/HV0.9/HH0.9 | +4.20% | +3.52% | +3.52% | mm@0.000 (domain floor) | floor = prod reference = fix candidate; not under-coverage |
| 57 | B3/stageA | ETHEUR | full 31d | stops[0.30,0.90,0.30] k_act null MM[0,0.020,0.004] | 600 | mm=0.004 LL0.6/LV0.9/MV0.9/HV0.3/HH0.9 | +8.41% | +19.28% | +8.41% | none | mm=0.004 in 5/5; interior; LIVE; test>train but robust=train |
| 58 | B2/stageD | XBTEUR | BC (21d) | stops[0.30,0.90,0.30] k_act[0.0,3.0,0.5] MM null | 400 | k=2.5 | +4.97% | +3.94% | +3.94% | — | k_act=2.5 stable vs full-window; PASS |
| 59 | B2/stageD | ETHEUR | BC (21d) | stops[0.30,0.90,0.30] k_act[0.0,3.0,0.5] MM null | 400 | k=3.0 | +3.91% | +2.99% | +2.99% | — | k_act zone 2.0-3.0 consistent; PASS |
| 60 | B3/stageD | XBTEUR | BC (21d) | stops[0.30,0.90,0.30] k_act null MM[0,0.020,0.004] | 400 | mm=0.008 | -5.22% | +3.45% | -5.22% | — | mm shifts 0.000→0.008; but 0.000 is domain floor+prod ref → fix at 0.000 |
| 61 | B3/stageD | ETHEUR | BC (21d) | stops[0.30,0.90,0.30] k_act null MM[0,0.020,0.004] | 400 | mm=0.004 | +1.45% | +4.74% | +1.45% | — | mm=0.004 stable across windows; PASS |
| 62 | B4/stageA | XBTEUR | full 31d | stops[0.30,0.90,0.30] k=2.5 fixed, mm=0 fixed, regime ER[8,96,8] enter[0.10,0.50,0.10] band[0.03,0.18,0.03] trend[0.55,0.85,0.10] | 800 | mm=0 LL0.9/LV0.6/MV0.9/HV0.3/HH0.3 ER=88 enter=0.50 band=0.15 trend=0.55 | +8.84% | +10.15% | +8.84% | none | first seed; test>train (gap ~1.3%); ER=88/enter=0.50/band=0.15 |
| 63 | B4/stageA | ETHEUR | full 31d | stops[0.30,0.90,0.30] k[2,3,0.5], mm=0.004 fixed, regime same | 800 | mm=0.004 LL0.6/LV0.3/MV0.9/HV0.3/HH0.9 ER=32 enter=0.30 band=0.18 trend=0.75 | +12.29% | +20.21% | +12.29% | none | test>train; first seed |
| 64 | B4/stageA-v2 | XBTEUR | full 31d | same as 62 | 800 | mm=0 LL0.6/LV0.9/MV0.6/HV0.6/HH0.6 ER=88 enter=0.50 band=0.15 trend=0.65 | +15.60% | +13.17% | +13.17% | none | ER=88/enter=0.50/band=0.15 stable across 2 seeds; trend varies (0.55→0.65) → DEAD; winner: ER=88/enter=0.50/band=0.15 |
| 65 | B4/stageA-v2 | ETHEUR | full 31d | same as 63 | 800 | mm=0.004 LL0.6/LV0.3/MV0.9/HV0.3/HH0.3 ER=72 enter=0.10 band=0.18 trend=0.66 | +21.20% | +7.56% | +7.56% | none | train>>test (overfitting); ER jumped 32→72; enter jumped 0.30→0.10 |
| 66 | B4/stageA-v3 | ETHEUR | full 31d | same | 800 | mm=0.004 LL0.3/LV0.6/MV0.9/HV0.3/HH0.9 ER=48 enter=0.40 band=0.03 trend=0.66 | +11.49% | +19.28% | +11.49% | none | ER=48/enter=0.40/band=0.03 but 3 seeds all differ (32/72/48); noise-dominated; winner for Stage B baseline |
| 67 | B4/stageB | XBTEUR | full 31d | CURRENT baseline ER=88 enter=0.50 band=0.15 trend=0.65 | 1 | same | +6.46% | +11.96% | +6.46% | — | Stage B baseline; robust=+6.46% |
| 68 | B4/stageB | XBTEUR | full 31d | ER=80 (ER-1step) | 1 | — | +6.46% | +5.69% | +5.69% | — | Δrobust=-0.77% → LIVE |
| 69 | B4/stageB | XBTEUR | full 31d | ER=96 (ER+1step) | 1 | — | -2.15% | +3.85% | -2.15% | — | Δrobust=-8.61% → LIVE (cliff above 88) |
| 70 | B4/stageB | XBTEUR | full 31d | enter=0.40 (enter-1step) | 1 | — | -5.68% | +3.33% | -5.68% | — | Δrobust=-12.14% → LIVE (cliff below 0.50) |
| 71 | B4/stageB | XBTEUR | full 31d | enter=0.60 (enter+1step) | 1 | — | +7.06% | +12.03% | +7.06% | — | Δrobust=+0.60% → LIVE |
| 72 | B4/stageB | XBTEUR | full 31d | band=0.12 (band-1step) | 1 | — | +8.36% | +5.86% | +5.86% | — | Δrobust=-0.60% → LIVE |
| 73 | B4/stageB | XBTEUR | full 31d | band=0.18 (band+1step) | 1 | — | +7.06% | +12.03% | +7.06% | — | Δrobust=+0.60% → LIVE |
| 74 | B4/stageB | XBTEUR | full 31d | trend=0.55 (trend-1step) | 1 | — | +6.46% | +11.96% | +6.46% | — | Δrobust=0.00% → DEAD |
| 75 | B4/stageB | XBTEUR | full 31d | trend=0.75 (trend+1step) | 1 | — | +6.46% | +11.96% | +6.46% | — | Δrobust=0.00% → DEAD; trend fixed at 0.65 |
| 76 | B4/stageB | ETHEUR | full 31d | CURRENT baseline ER=48 enter=0.40 band=0.03 trend=0.66 (live env stops+mm=0.010) | 1 | — | +0.52% | -10.44% | -10.44% | — | Stage B baseline; robust=-10.44% (live env config; regime hurting with non-optimised stops) |
| 77 | B4/stageB | ETHEUR | full 31d | ER=40 (ER-1step) | 1 | — | -3.71% | -10.00% | -10.00% | — | Δrobust=+0.44% → DEAD direction |
| 78 | B4/stageB | ETHEUR | full 31d | ER=56 (ER+1step) | 1 | — | +5.83% | -14.87% | -14.87% | — | Δrobust=-4.43% → LIVE → ER overall LIVE |
| 79 | B4/stageB | ETHEUR | full 31d | enter=0.30 (enter-1step) | 1 | — | +2.15% | -9.64% | -9.64% | — | Δrobust=+0.80% → LIVE |
| 80 | B4/stageB | ETHEUR | full 31d | enter=0.50 (enter+1step) | 1 | — | +8.18% | -8.92% | -8.92% | — | Δrobust=+1.52% → LIVE |
| 81 | B4/stageB | ETHEUR | full 31d | band=0.00 (band-1step) | 1 | — | +2.15% | -9.64% | -9.64% | — | Δrobust=+0.80% → LIVE |
| 82 | B4/stageB | ETHEUR | full 31d | band=0.06 (band+1step) | 1 | — | +8.18% | -12.78% | -12.78% | — | Δrobust=-2.34% → LIVE; ER/enter/band LIVE; trend DEAD (fix at 0.66) |
| 83 | B4/stageD | XBTEUR | BC (21d) | stops[0.30,0.90,0.30] k=2.5/mm=0 fixed, regime ER[8,96,8] enter[0.10,0.50,0.10] band[0.03,0.18,0.03] trend=0.65 fixed | 400 | k=2.5 ER=88 enter=0.10 band=0.15 trend=0.65 | +4.81% | +5.27% | +4.81% | — | ER=88+band=0.15 STABLE vs full-window; enter 0.50→0.10 UNSTABLE → fix enter at prod ref 0.33 |
| 84 | B4/stageD | ETHEUR | AB (21d) | stops[0.30,0.90,0.30] k[2,3,0.5] mm=0.004 fixed, regime ER[8,96,8] enter[0.10,0.50,0.10] band[0.03,0.18,0.03] trend=0.66 fixed | 400 | mm=0.004 ER=32 enter=0.40 band=0.12 trend=0.66 | +12.10% | +5.30% | +5.30% | — | ER/band differ from full-window; ETHEUR dims all unstable across windows |
| 85 | B4/stageD | ETHEUR | BC (21d) | same | 400 | k=2.5 ER=72 enter=0.20 band=0.06 trend=0.66 | +6.09% | +8.28% | +6.09% | — | branch flip (K_ACT vs MM); ER/enter/band all differ from full+AB; ETHEUR regime noise-dominated → fix all at prod defaults |
| 86 | B5/AUTO | XBTEUR | full 31d | stops[0.30,0.90,0.30] k=2.5/mm=0 fixed, ER[72,96,8] enter=0.33/trend=0.65 fixed, band[0.12,0.18,0.03] | AUTO | k=2.5 ER=96 enter=0.33 band=0.15 LL0.9/LV0.6/MV0.9/HV0.3/HH0.3 | +7.53% | +9.73% | +7.53% | ER=96 (ceiling) | NOT CONVERGED (0/4 seeds agreed); ER edge-pinned at 96 → extend range; retry with band fixed + ER[80,120,8] |
| 87 | B5/AUTO | ETHEUR | full 31d | stops[0.30,0.90,0.30] k[2.0,3.0,0.5] mm=0.004 fixed, regime all fixed at prod defaults | AUTO | mm=0.004 ER=32 enter=0.33 band=0.07 LL0.3/LV0.3/MV0.9/HV0.3/HH0.9 | +11.71% | +14.34% | +11.71% | none | NOT CONVERGED; MM branch wins all 5 candidates (k=null); K_ACT never wins → disable K_ACT for retry |
| 88 | B5/AUTO-v2 | XBTEUR | full 31d | stops[0.30,0.90,0.30] k=2.5/mm=0/enter=0.33/band=0.15/trend=0.65 all fixed, ER[80,120,8] | AUTO | k=2.5 ER=112 enter=0.33 band=0.15 LL0.9/LV0.9/MV0.6/HV0.3/HH0.3 | +17.32% | +13.04% | +13.04% | none (ER=112 interior in [80,120]) | NOT CONVERGED (0/4 seeds agreed); ER=112 stable across top-4 but stops scatter; data-volume verdict → park |
| 89 | B5/AUTO-v2 | ETHEUR | full 31d | stops[0.30,0.90,0.30] k_act=null mm=0.004 fixed, regime all fixed at prod defaults | AUTO | mm=0.004 ER=32 enter=0.33 band=0.07 LL0.3/LV0.3/MV0.9/HV0.3/HH=0.9 | +11.71% | +14.34% | +11.71% | none | CONVERGED (3/4 seeds agreed, 1500 trials); deploy candidate (subject to Gates) |

---

## Block 4 Verdicts

### XBTEUR regime dims

| dim | Stage B verdict | Stage D verdict | final decision |
|---|---|---|---|
| er_window | LIVE (Δ=-8.61% at ER+8; cliff) | STABLE (88 in full+BC) | **LIVE; search [72,96,8]** |
| chop_enter_pct | LIVE (Δ=-12.14% at enter-1step; cliff) | UNSTABLE (0.50→0.10) | **FIX at 0.33 (prod ref)** |
| chop_dead_band | LIVE (±0.60% both dirs) | STABLE (0.15 in full+BC) | **LIVE; search [0.12,0.18,0.03]** |
| trend_pct | DEAD (Δ=0.00% both dirs) | — (fixed) | **FIX at 0.65** |

### ETHEUR regime dims

| dim | Stage B verdict | Stage D verdict | final decision |
|---|---|---|---|
| er_window | LIVE (Δ=-4.43% at ER+8) | UNSTABLE (32/72/48/32/72) | **FIX at 32 (prod ref)** |
| chop_enter_pct | LIVE (both dirs ≥0.80%) | UNSTABLE (0.30/0.10/0.40/0.40/0.20) | **FIX at 0.33 (prod ref)** |
| chop_dead_band | LIVE (both dirs ≥0.80%) | UNSTABLE (0.18/0.18/0.03/0.12/0.06) | **FIX at 0.07 (prod ref)** |
| trend_pct | DEAD (inherited from XBTEUR) | — (fixed) | **FIX at 0.66** |

**ETHEUR regime conclusion:** All dims either DEAD or UNSTABLE at 31 days. Regime for ETHEUR parks at prod defaults until Gate 1 (≥20 test ops) is met.

---

## Block 5 Results

### XBTEUR — NOT CONVERGED (parked, data-volume verdict)

Two AUTO attempts failed to converge on stop_pcts despite all other dims being fixed. ER zone shifted from 88 → 96 → 112 across successive runs as the stop configuration changed — evidence of strong stop-regime interaction. The search is correct; the data is insufficient.

- **Best available config (not deploy-ready):** k_act=2.5, min_margin=0, ER=112, chop_enter=0.33, chop_exit=0.48, trend=0.65, stops LL=0.90/LV=0.90/MV=0.60/HV=0.30/HH=0.30
- **Action:** Re-run AUTO-v2 (job 88 space) once Gate 1 passes (≥20 test ops; expected around ≥60 days of data)

### ETHEUR — CONVERGED ✓

3/4 seeds agreed in 1500 trials (one retry was sufficient — disabling K_ACT branch was the fix).

**Deploy candidate (subject to Gates 1-3):**
```
ETHEUR_MIN_MARGIN=0.004
ETHEUR_STOP_PCT_LL=0.30
ETHEUR_STOP_PCT_LV=0.30
ETHEUR_STOP_PCT_MV=0.90
ETHEUR_STOP_PCT_HV=0.30
ETHEUR_STOP_PCT_HH=0.90
ETHEUR_ER_WINDOW=32
ETHEUR_ER_CHOP_ENTER_PCT=0.33
ETHEUR_ER_CHOP_EXIT_PCT=0.40
ETHEUR_ER_TREND_PCT=0.66
```

---

## Final Calibration Summary (2026-06-11, 31 days)

### Dimension verdicts

| dim | XBTEUR decision | ETHEUR decision |
|---|---|---|
| stop_pcts | search [0.30,0.90,0.30]; LL/LV/MV/HV/HH all live | search [0.30,0.90,0.30]; converged at LL=LV=HV=0.30, MV=HH=0.90 |
| k_act | LIVE; fix at 2.5 (stable across all windows) | DEAD for this dataset; K_ACT branch consistently loses → null |
| min_margin | FIX at 0.000 (domain floor; prod reference) | LIVE; fix at 0.004 (stable, converged) |
| er_window | LIVE; search [80,120,8]; winner ~112 (stop interaction) | FIX at 32 (unstable; prod default) |
| chop_enter_pct | FIX at 0.33 (LIVE but temporally unstable) | FIX at 0.33 (unstable; prod default) |
| chop_dead_band | LIVE; fix at 0.15 (stable); re-search once Gate 1 passes | FIX at 0.07 (unstable; prod default) |
| trend_pct | FIX at 0.65 (DEAD; Δ=0.00%) | FIX at 0.66 (DEAD; inherited) |

### Gate status (2026-06-11)

| gate | status | note |
|---|---|---|
| G1: test_ops ≥ 20 | ❌ not met | API does not expose op count; likely 4-6 test ops at 31d / 80-20 split |
| G2: regime episodes ≥ 6 | ❓ not checked | Need to count chop↔trend transitions from backtest operations |
| G3: verdict stability | ❓ pending | Requires weekly CURRENT+OPTIMIZE probes; not yet established |

### Next actions when data grows

1. **Weekly Gate 3 probes** (4 jobs/week): 1 CURRENT + 1 OPTIMIZE per pair, fixed space, fixed seed → track whether winner zone changes
2. **Re-run Block 5 XBTEUR** when G1 passes: use job 88 search space (stops[0.30,0.90,0.30], k=2.5, mm=0, ER[80,120,8], band=0.15, enter=0.33, trend=0.65, seed=42)
3. **Block 4 Stage C** for XBTEUR regime dims: step refinement for ER and band once G1/G3 pass
4. **ETHEUR regime re-calibration**: all regime dims parked at prod defaults; re-run Block 4 Stage A for ETHEUR once G1 passes
