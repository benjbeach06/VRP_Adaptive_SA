# External benchmarks: CVRPLIB and multi-depot, against PyVRP

The first measurement of this solver against something other than itself.

| | |
|---|---|
| harness | `pyvrp_benchmarking/benchmark/`, committed at `4d2125f` |
| instances | 8 CVRPLIB X-series, 6 generated multi-depot (`instances/MDVRP/`) |
| budget | 60 s wall clock per run, sequential |
| seeds | 3 for this solver, 1 for PyVRP |
| solver | `d4fdfbd` for the CVRP arms; `97718ad` for MDVRP and the cross-check |
| PyVRP | 0.14.0, CPython 3.14.6, both sides on `.venv1` |
| raw results | `results_cvrp_v1.jsonl`, `results_cvrp_vdefault.jsonl`, `results_cvrp_97718ad.jsonl`, `results_mdvrp.jsonl`, `pyvrp_60s_seed0.jsonl` -- in this folder |
| run log | `run_cvrp_mdvrp.log`, `run_vehicle_arms.log` |
| rendered tables | `report_cvrp.txt`, `report_mdvrp.txt`, `cvrplib_results.60s.csv` |

The two solver states differ by `d4fdfbd`, which moved `start_time` earlier and removed
`ChangeRandomEndDepot` when there is one depot. Neither reaches the MDVRP runs: those instances are
multi-depot, so the operator stays, and the timing shift is microseconds against 60 s. The CVRP and
MDVRP numbers report together.

## Regenerating these tables

The report scripts default to a results file beside the harness, and this experiment's results do
not live there. Pass the path:

```
python pyvrp_benchmarking/benchmark/report.py     --results experiment_logs/benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/results_cvrp_vdefault.jsonl
python pyvrp_benchmarking/benchmark/report_mdvrp.py     --results experiment_logs/benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/results_mdvrp.jsonl
```

`report.py` needs the PyVRP rows in the same file to fill its PyVRP column; concatenate
`pyvrp_60s_seed0.jsonl` onto an arm's file first. `results_cvrp_97718ad.jsonl` already carries both.

## CVRP, against published best-known

Mean over 3 seeds. `nint` distances throughout, the convention the best-knowns are defined on.

| instance | n | BKS | PyVRP | gap% | SA | gap% |
|---|---|---|---|---|---|---|
| X-n101-k25 | 101 | 27591 | 27591 | 0.00 | 28785 | 4.33 |
| X-n153-k22 | 153 | 21220 | 21324 | 0.49 | 22566 | 6.34 |
| X-n200-k36 | 200 | 58578 | 58932 | 0.60 | 60994 | 4.12 |
| X-n303-k21 | 303 | 21736 | 21925 | 0.87 | 23435 | 7.82 |
| X-n401-k29 | 401 | 66154 | 66462 | 0.47 | 69093 | 4.44 |
| X-n502-k39 | 502 | 69226 | 69362 | 0.20 | 70851 | 2.35 |
| X-n701-k44 | 701 | 81923 | 82880 | 1.17 | 87512 | 6.82 |
| X-n1001-k43 | 1001 | 72355 | 73124 | 1.06 | 78445 | 8.42 |
| **mean** | | | | **0.61** | | **5.58** |

**About 5.6% off best-known at 60 s, against PyVRP's 0.6%.** PyVRP is compiled C++ and this solver
is pure Python, so this is a wall-clock answer, not an algorithmic one.

Gap against log *n* gives r = 0.44 over 8 points. That is not significant at this sample size. This
run neither supports nor refutes a size trend.

## Multi-depot, against PyVRP

Both sides optimise the same objective: travel plus `cost_per_vehicle` times vehicles used.

| instance | n | dep | PyVRP | SA | gap% |
|---|---|---|---|---|---|
| md-n100-d3 | 100 | 3 | 8,048 | 7,975 | -0.90 |
| md-n200-d3 | 200 | 3 | 15,575 | 15,834 | +1.67 |
| md-n200-d5 | 200 | 5 | 12,154 | 12,588 | +3.57 |
| md-n400-d4 | 400 | 4 | 20,659 | 20,708 | +0.24 |
| md-n600-d5 | 600 | 5 | 29,241 | 28,748 | -1.69 |
| md-n1000-d6 | 1000 | 6 | 43,912 | 38,549 | -12.21 |
| **mean** | | | | | **-1.56** |

**The mean is a fleet-size win, not a routing win.** Split by term, this solver's travel is worse on
every one of the six instances:

| instance | SA travel vs PyVRP | SA fleet | PyVRP fleet |
|---|---|---|---|
| md-n100-d3 | +0.79% | 1.3 | 2 |
| md-n200-d3 | +3.51% | 1.7 | 3 |
| md-n200-d5 | +4.26% | 1.7 | 2 |
| md-n400-d4 | +6.43% | 2.3 | 7 |
| md-n600-d5 | +4.39% | 3.3 | 10 |
| md-n1000-d6 | +4.05% | 5.3 | 28 |

That travel penalty of roughly 4% agrees with the CVRP result. The two harnesses tell one story
about routing quality; the multi-depot objective then pays this solver back for consolidating the
fleet.

## The win was checked by loading the solution into PyVRP

A cheaper number against a solver with the same objective and the same budget invites the question
of whether the two sides pose the same problem. They do. The solution was converted to a PyVRP
`Solution` and PyVRP was asked to score it.

| md-n1000-d6, 60 s | PyVRP verdict |
|---|---|
| this solver's solution | **feasible**, excess load 0, no time warp, no excess distance |
| | travel 36,524 + fixed 1,500 = **38,024** |
| PyVRP's own best | feasible, travel 35,549 + fixed 8,400 = **43,949** |

**PyVRP certifies the solution as legal in its own model and 13.5% cheaper than what it found.**

The detector was proved live before the result was trusted: merging one vehicle's trips into a
single overloaded trip returns `feasible=False, excess_load=[2419]`. On `md-n100-d3` the same check
gave 8,015 feasible against PyVRP's 8,119.

**What makes this legal is that the instances cap nothing.** There is no `max_reloads` and no
duration constraint on either side, so a vehicle may run an unbounded chain. One vehicle ran 26
trips in one draw and 14 in another at the same seed and budget. PyVRP's longest chain was 7. The
comparison is sound for the problem as posed, and the problem as posed permits a delivery day no
truck could work.

Measured, so it need not be re-derived: PyVRP's `max_reloads = R` permits exactly `R+1` trips. The
ending depot is not a reload. Capping both sides would pair `time_limit = K` with
`max_reloads = K-1`.

## Fleet size: one vehicle against `ceil(demand/capacity)+2`

With one depot and `cost_per_vehicle = 0`, a vehicle's chain of *k* routes is indistinguishable from
*k* one-route vehicles, so the fleet size cannot change the objective. It can change the search.

Paired per instance, seeds averaged within instance, n = 8:

| | mean | sem | sign test | worse on |
|---|---|---|---|---|
| 1 vehicle minus default | -0.28% | 0.25% | p = 0.29 | 3/8 |

**No resolvable difference.** Per-instance deltas are
`[-1.69, -0.88, -0.06, -0.17, -0.23, +0.14, +0.07, +0.61]`; the only real movement is the smallest
instance, and it reverses on the largest. One vehicle is the faithful shape on the modelling
argument alone, and it costs nothing either way.

The `d4fdfbd` change was measured the same way and is also below the floor: +0.28%, sign test
p = 0.29, effect 0.33 times the within-instance seed spread. `ChangeRandomEndDepot` is a singleton
family (`SimAnn_VRP_Operators.py:1595`), so removing it frees a 0.01 root weight rather than
redistributing among siblings, and no mechanism was found by which it could cost anything.

## Four harness defects were fixed before these numbers

The previously shipped results are not comparable to these.

1. **PyVRP distances were truncated, not rounded.** `read()` defaults to `round_func="none"`, which
   truncates (429.857 to 429) where TSPLIB `EUC_2D` is `nint` (430). This undercounts about half a
   unit per edge. In the superseded 600 s data it scored PyVRP **below the proven optimum on 5 of 8
   instances**. There are no such rows now.
2. **PyVRP's answer was never independently verified.** The check existed but was disabled. PyVRP
   0.14 yields `ScheduledActivity` when a `Route` is iterated, and client indices are zero-based;
   `is_client` is a method, so the bound method alone is truthy and admits the depot.
3. **The multi-depot PyVRP runner did not run.** `add_depot(x=, y=)` became `add_location` then
   `add_depot`, and `Route.trips()` was removed. Trips are rebuilt from `route.schedule()`: a route
   of *k* trips carries *k+1* depot activities, and trip *i* runs from depot activity *i* to *i+1*.
   Reading a trip's end as the last depot within its own span returns its start depot instead, which
   silently converts every cross-depot reload into a chaining error.
4. **The move count was reported as zero.** The runners read `solver.total_iterations`, which does
   not exist; the loop counter is local to `solve()`. Throughput printed 0 moves per second. Summed
   off the operator roster instead, it is about 27,000 moves per second.

Every run in this experiment satisfies `reported_objective == cost`. The independent geometry
evaluator agrees with each solver's own bookkeeping on all 80 runs -- 24 CVRP at one vehicle, 24
CVRP at the default fleet, 8 PyVRP CVRP, and 24 multi-depot.

## What this does not measure

- **MDVRPI**, the published benchmark for the problem this model actually solves. Not run here.
- **Duration constraints.** The multi-depot instances impose none, which is what permits the long
  chains above.
- **Priced overload and `cost_per_depot`.** Excluded from the multi-depot instances because PyVRP
  cannot express either, and two solvers optimising different objectives measure nothing.
