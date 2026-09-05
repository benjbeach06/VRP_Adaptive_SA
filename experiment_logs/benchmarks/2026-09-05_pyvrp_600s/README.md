# External benchmarks at 600 s: CVRPLIB and multi-depot, against PyVRP

The 2026-09-04 benchmark repeated at ten times the budget. Same instances, same harness, same
machine, one solver commit on both arms.

| | |
|---|---|
| harness | `pyvrp_benchmarking/benchmark/`, unchanged since `4d2125f` |
| instances | 8 CVRPLIB X-series, 6 generated multi-depot (`instances/MDVRP/`) |
| budget | 600 s wall clock per run, sequential |
| seeds | 3 for this solver, 1 for PyVRP |
| solver | `cbcbb4f`, clean tree, both arms |
| PyVRP | 0.14.0, CPython 3.14.6, both sides on `.venv1` |
| runs | 56, wall clock 01:45:25 to 11:05:48 EDT on 2026-09-05 |
| raw results | `results_cvrp.jsonl`, `results_mdvrp.jsonl` |
| driver | `drive_600s.sh`, byte-identical to the script that ran |
| run log | `run.log` |

All 56 runs are feasible, report `reported_objective == cost`, record zero problems, and show
elapsed between 600.00 s and 600.51 s.

## Regenerating

```
bash experiment_logs/benchmarks/2026-09-05_pyvrp_600s/drive_600s.sh
```

`drive_600s.sh` truncates both results files but APPENDS to `run.log`.

## CVRP, against published best-known

Mean over 3 seeds. `nint` distances, the convention the best-knowns are defined on.

| instance | n | BKS | PyVRP | gap% | SA | gap% | SA sd |
|---|---|---|---|---|---|---|---|
| X-n101-k25 | 101 | 27591 | 27591 | 0.00 | 28025 | 1.57 | 301 |
| X-n153-k22 | 153 | 21220 | 21274 | 0.25 | 22277 | 4.98 | 13 |
| X-n200-k36 | 200 | 58578 | 58635 | 0.10 | 60390 | 3.09 | 72 |
| X-n303-k21 | 303 | 21736 | 21850 | 0.52 | 22841 | 5.08 | 308 |
| X-n401-k29 | 401 | 66154 | 66388 | 0.35 | 68196 | 3.09 | 338 |
| X-n502-k39 | 502 | 69226 | 69362 | 0.20 | 70885 | 2.40 | 98 |
| X-n701-k44 | 701 | 81923 | 82406 | 0.59 | 87186 | 6.42 | 262 |
| X-n1001-k43 | 1001 | 72355 | 73079 | 1.00 | 78276 | 8.18 | 288 |
| **mean** | | | | **0.38** | | **4.35** | |

## Multi-depot, against PyVRP

Both sides optimise the same objective: travel plus `cost_per_vehicle` times vehicles used.
Negative means this solver is cheaper.

| instance | n | dep | PyVRP | SA | gap% | SA sd |
|---|---|---|---|---|---|---|
| md-n100-d3 | 100 | 3 | 7,822 | 7,779 | -0.55 | 36 |
| md-n200-d3 | 200 | 3 | 15,254 | 15,378 | +0.82 | 87 |
| md-n200-d5 | 200 | 5 | 12,091 | 12,048 | -0.36 | 88 |
| md-n400-d4 | 400 | 4 | 20,033 | 19,761 | -1.36 | 222 |
| md-n600-d5 | 600 | 5 | 27,920 | 28,006 | +0.31 | 308 |
| md-n1000-d6 | 1000 | 6 | 41,115 | 36,206 | -11.94 | 8 |
| **mean** | | | | | **-2.18** | |

**One instance carries the whole mean.** Drop `md-n1000-d6` and the other five average **+0.23%**,
which is a tie. The same was true at 60 s. The mean should not be quoted without this sentence.

## The mean is still a fleet result, split by term

| instance | SA travel vs PyVRP | SA fleet | PyVRP fleet |
|---|---|---|---|
| md-n100-d3 | -0.57% | 1.0 | 1 |
| md-n200-d3 | +0.83% | 1.0 | 1 |
| md-n200-d5 | +1.34% | 1.0 | 2 |
| md-n400-d4 | +2.54% | 2.0 | 5 |
| md-n600-d5 | +4.47% | 2.7 | 7 |
| md-n1000-d6 | +2.31% | 4.0 | 23 |
| **mean** | **+1.82%** | | |

The objective win is still fleet consolidation, which `cost_per_vehicle` prices. Travel is worse on
five of six instances.

## What ten times the budget bought

Same instance sets on both rows.

| | 60 s | 600 s |
|---|---|---|
| CVRP, SA gap vs best-known | 5.58% | **4.35%** |
| CVRP, PyVRP gap vs best-known | 0.61% | **0.38%** |
| MDVRP, SA objective vs PyVRP | -1.56% | **-2.18%** |
| MDVRP, SA travel vs PyVRP | +3.90% | **+1.82%** |

**The travel penalty roughly halved, from +3.90% to +1.82%.** That is the more informative
number of the four, because the multi-depot objective gap is dominated by fleet consolidation
while the travel term measures routing quality directly. It also no longer agrees with the CVRP
gap of 4.35%, which it did at 60 s. The two harnesses stopped telling one story, and this report
does not explain why.

Both sides improved, so the extra budget is not a one-sided gift. Neither side is converged.

## What this does not show

PyVRP is compiled C++ and this solver is pure Python. Every number here is a wall-clock answer at a
fixed budget, not a statement about the algorithms.

The seed count is 3 and the PyVRP arm is 1 seed, so per-instance differences smaller than the
listed `sd` are not resolved. `md-n1000-d6` at `sd` 8 on a 4,909 difference is the only multi-depot
gap that is unambiguous at this sample size.

## References

*(none yet)*

## Links to here

- [RESULTS.md](../../../RESULTS.md) -- cites the 600 s figures here as the second point on the CVRPLIB budget curve, and the multi-depot travel gap that stopped agreeing with the CVRP gap
- [experiment_logs/README.md](../../README.md) -- the experiment index, which carries this run's one-line summary and its solver commit
