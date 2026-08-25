# Scoring rework trajectory

**What each stage of the scoring rework bought, measured one commit at a time.**

This is not a parameter sweep. Each arm is a **git worktree pinned to a checkpoint commit**, running
the identical solver call. The arm dimension is the code version.

| | |
|---|---|
| instance | n=500, capacity 400, `tune.build_instance(500)` |
| budget | 300 s per run, NN start |
| seeds | 19 paired, **seeds as the outer loop** |
| driver | `tools/ablate_trajectory.py` |
| launched | 2026-08-22 03:16 |

## Arms

| folder | commit | what it adds |
|---|---|---|
| `01_pre_stage1` | `8d89ad1` | **baseline.** Tree as objects, `remove()`, arm table in `tools/`. Flat-roster magnet, hand-set penalty factors. |
| `02_stage1_magnetism` | `c539a1e` | sibling-local magnetism; `Bayes_magnet` exposed |
| `03_stage2_no_penalty_factor` | `30c6b07` | `exploit_selection_penalty_factor` to 1.0 for every operator |
| `04_stages34_dynamic_penalty` | `6e89e5b` | shrunk improvement estimate, and the dynamic penalty with its cancellation |
| `05_stage5_valid_cost` | `fbe7b9d` | cost is mean time per VALID proposal |
| `06_stages67_head` | `6940351` | `cost_exponent` exposed at its default, plus floor tests |

**Arm 06 is a replicate of arm 05.** Stage 6 defaults `cost_exponent` to 1 and stage 7 adds tests
only, so 06 differs from 05 in no way the solver can see. Run as a separate arm it measures
run-to-run variance at identical settings, which is the noise floor every other arm is read against.
That was confirmed before launch: a smoke run returned bit-identical objectives for the two.

## Why seeds are the outer loop

Every arm runs seed 0 before any arm runs seed 1. An interrupted study then has every arm at the
same seed count and stays paired. Finishing one arm at a time would leave the last arms with no data
at all.

Each arm's `results.json` is rewritten after every completed run, so a crash loses at most one run.

## Reading it

```bash
.venv1/Scripts/python.exe tools/plot_trajectory.py experiment_logs/ablations/2026-08-22_scoring_rework_trajectory
```

Four panels. The endpoint alone cannot separate a slow arm from a stuck one, so the convergence and
throughput panels come from the per-report `path` data that `ablate_param.run_once` records.

## What to expect, stated before the numbers arrive

**Stage 2 is the one at risk.** It removes a hand-set cost discount and puts nothing in its place
until stage 4. Arm 03 could well be worse than arm 02. If it is, that is the mechanism working as
designed, not a regression: the discount was a magic number covering for scoring that could not
price cost, and stage 4 is what replaces it.

**Stage 4 is where the gain should appear**, if the design is right. It is the direct answer to the
finding that `ReorderShortSpanExactly` held the roster's highest weight while producing 20.7
improving moves per second against `ReverseClosestPairTogether`'s 666.

**Stage 5 should be small and positive.** It stops cheap invalids from understating an operator's
cost, which matters most for operators with high no-op rates.

## Note

`_worktrees/` is git-ignored. Remove them with `git worktree remove <path> --force` once the study
is analysed.

---

# RESULTS, 19 seeds, complete 2026-08-22 12:48

| arm | mean | vs baseline | sigma | won | iterations | reheats |
|---|---|---|---|---|---|---|
| 01 pre-stage-1 | 1918.13 | — | — | — | 7,357,846 | 17.2 |
| **02 magnetism** | 1930.38 | **+12.25 +/- 5.18** | **+2.4** | 4/19 | 5,083,405 | 12.6 |
| 03 no penalty factor | 1923.28 | +5.16 +/- 5.70 | +0.9 | 7/19 | 4,390,761 | 11.7 |
| 04 dynamic penalty | 1919.09 | +0.97 +/- 7.45 | +0.1 | 9/19 | 3,784,793 | 9.3 |
| 05 valid cost | 1918.83 | +0.71 +/- 6.81 | +0.1 | 8/19 | 3,949,140 | 10.2 |
| **06 replicate of 05** | 1926.17 | **+8.04 +/- 7.48** | +1.1 | 9/19 | 3,746,941 | 9.8 |

## Read the replicate first

**Arm 06 is behaviourally identical to arm 05 and reads +8.04 where it must read 0.00.** That is the
noise floor, measured rather than assumed. An apparent effect of 8 units in this study means nothing.

## The objective is neutral

HEAD lands at +0.71 against the pre-rework baseline. **Nothing cleared 3 sigma.** On this instance at
this budget, the whole scoring rework neither helped nor hurt the objective.

## The throughput is not

**HEAD does 49% fewer iterations than the baseline in the same 300 seconds, and still ties it.**
Selection improved enough to offset halving the compute. The neutral objective hides that entirely.

Plateau reheats fall with it, 17.2 to 9.8, which is the same fact seen from the other side: fewer
iterations means fewer plateaus reached.

## Stage 1 is the one suggestive signal, and it points the wrong way

Sibling-local magnetism costs **+12.25 at 2.4 sigma, winning 4 of 19**. Two statistics agree: the
sign test is about 1% one-sided, and arm 02 carries the tightest error bar in the study because it
differs from baseline only in the magnet, so the paired trajectories stay close.

It is under the 3 sigma bar, and the replicate's own +8.04 argues for caution. **Not proven. Worth a
dedicated run.**

## The scoring stages repaired it

Arm 05 against arm 02: **-11.54 +/- 5.79, -2.0 sigma, won 12/19.** Stages 2 to 5 recovered most of
what stage 1 cost.

## What contradicts the design

**The penalty favours cheap operators, so stage 4 should RAISE throughput.** It fell instead, from
4.39M to 3.78M iterations. Either the new per-segment work is heavier than estimated, or the operator
mix moved toward expensive operators.

**Not established.** Arm 07 records per-operator time share and is the measurement that settles it.

## What this study cannot say

- **300 s only.** The defect the rework targets is worst AT PLATEAU, and fewer plateaus are reached
  here than in a 600 s run. A longer budget may read differently.
- **One instance.** n=500 capacity 400.
- **No operator-level data for arms 01 to 06.** Only the objective and the path were recorded, so the
  throughput loss cannot be attributed to a specific operator from this data.

---

# ARM 07 — HEAD at K=8, with per-operator statistics

Benjamin's request: run the most expensive operator at its old span under the NEW pricing, and see
what happens to its computational share and its weighting. 19 seeds, 300 s, n=500 capacity 400,
solver `6940351`, arm 12 (`full-K8`). Mean objective **1938.71**.

Compare against the pre-refactor K=8 profile recorded in `RESULTS.md`: `ReorderShortSpanExactly`
took **74% of wall clock**, produced **7.5 improving moves per second against 755** for
`ReverseClosestPairTogether`, and the weighting **ranked it first**.

## The weight ranking is FIXED

| operator | adj_weight | weight | penalty | time% | us/call | improving/s |
|---|---|---|---|---|---|---|
| `ReorderShortSpanExactly` | **1.062** | 41.0 | **0.6684** | 48.79 | 411.5 | 0.9 |
| `ReverseClosestPairTogether` | 0.033 | **111.7** | 0.0027 | 2.65 | 51.6 | 76.3 |

**On raw weight the cheap productive operator now leads 2.7x.** Pre-refactor the exact reorderer
ranked first. That half of the rework works, and its clock share fell from about 74% to 48.79% at
the same K.

## The PENALTY inverts it, 32x the wrong way

`adj_weight = weight * penalty` is what drives selection, and there the exact reorderer leads by
**32x**. The penalty promotes it 250x, swamping the 2.7x the weight got right.

## Why -- and this contradicts the design

`planning/scoring-rework.md` claims: *"When nothing is productive, every estimate clusters, so
penalty collapses to min_cost/cost -- ranking by cost alone, which is what a plateau wants."*

**The estimates do not cluster.** Measured at run end:

| operator | improvement_estimate | scoring_cost | whole-run improving/proposal |
|---|---|---|---|
| `ReorderShortSpanExactly` | 6.85e-06 | 7.26e-04 | 3.78e-04 |
| `ReverseClosestPairTogether` | 8.56e-09 | 4.62e-05 | 3.93e-03 |

They spread over five orders of magnitude, and **39% of operators sit at the 1e-10 floor**. The
exact reorderer does exhaustive search, so it still finds occasional improvements at plateau while
cheap random operators have exhausted theirs. Its estimate stays about 800x above the reversal's,
which dwarfs the 16x cost difference.

**So the penalty ranks by RECENTLY-improving per second.** At plateau that favours the exhaustive
operator -- exactly the one the design set out to demote.

Note the reversal's whole-run rate is 10x HIGHER than the exact reorderer's. The estimate inverts
the ranking because it is an EMA of recent segments, not a whole-run rate. That is by design; the
consequence was not.

## What this does NOT establish

- **Whether the late-run rates justify the ranking.** The estimate is not wrong as a measurement of
  recent behaviour. Whether "still improving at plateau" should outrank "16x cheaper" is a design
  question this data does not settle.
- **Where the trajectory study's 49% throughput loss went.** This arm is K=8, so its shares are not
  comparable to the K=4 arms. A K=4 run with the same statistics would settle it.
- **The 74% comparison is rough**, from a differently configured profiled run, as Benjamin noted.
