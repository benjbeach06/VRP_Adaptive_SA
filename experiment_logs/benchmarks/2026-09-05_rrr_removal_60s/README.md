# Paired 60 s CVRP A/B: removing `RandomRouteReassignment` when route movement cannot pay

`c5eda54` drops `RandomRouteReassignment` from the operator set when the solution has one depot and
moving a whole route between vehicles cannot change the objective. This run asks one question:
**does the removal change solution quality on CVRP?**

| | |
|---|---|
| harness | `pyvrp_benchmarking/benchmark/run_sa.py`, identical in both arms |
| instances | the 8 CVRPLIB X-series of the standing benchmark |
| budget | 60 s wall clock per run, sequential |
| seeds | 5 per arm |
| baseline | `ab16365`, checked out at `_worktrees/ab16365` -- operator PRESENT |
| treatment | `c5eda54`, main tree -- operator REMOVED |
| fleet | `run_sa.py` default, `ceil(demand/capacity) + 2` |
| construction | `greedy` |
| runs | 80, 16:03 to 17:24 EDT on 2026-09-05 |
| raw results | `results_baseline.jsonl`, `results_treatment.jsonl` |
| driver | `drive.py` |
| analysis | `tables.py` |
| run log | `run.log` |

All 80 runs are feasible, report `reported_objective == cost`, record zero problems, and finish
inside the budget. `drive.py` checks all three per run.

## The arms differ by exactly one operator

`git diff ab16365 c5eda54 -- pyvrp_benchmarking/` is EMPTY, so both arms run the same harness and
the same instance files. On the benchmark configuration the operator set is the only difference,
and that was measured in both trees rather than assumed:

| configuration | baseline | treatment |
|---|---|---|
| CVRP default, 12 vehicles, 1 depot, no duration model | 23 operators, present | **22 operators, removed** |
| one vehicle | present | removed |
| `cost_per_vehicle = 100` | present | present |
| `travel_time_per_distance = 1`, `vehicle_hourly_rate = 1` | present | present |

The last two rows are the detector firing the other way. Without them the first two rows prove
nothing.

## The design is PAIRED

For each (instance, seed) the driver runs the baseline and then the treatment back to back. Two
arms run as separate 40-minute blocks would differ in machine state as well as in code, which is
the confound the second arm exists to remove. Because the two runs of a pair share a seed, a
construction and a moment, the pair is the unit of analysis.

## Regenerating

```
python experiment_logs/benchmarks/2026-09-05_rrr_removal_60s/drive.py
python experiment_logs/benchmarks/2026-09-05_rrr_removal_60s/tables.py
```

`drive.py` needs the baseline worktree. Create it with
`python -c "import sys; sys.path.insert(0,'tools'); from worktrees import ensure; ensure('ab16365')"`.
It truncates both results files and APPENDS to `run.log`.

## Result

Mean over 5 seeds. `nint` distances, the convention the best-knowns are defined on.

| instance | n | BKS | baseline | gap% | treatment | gap% | delta% | sd(base) | sd(treat) |
|---|---|---|---|---|---|---|---|---|---|
| X-n101-k25 | 100 | 27591 | 28,618 | 3.72 | 28,624 | 3.74 | +0.02 | 213 | 99 |
| X-n153-k22 | 152 | 21220 | 22,518 | 6.12 | 22,530 | 6.17 | +0.05 | 133 | 131 |
| X-n200-k36 | 199 | 58578 | 60,880 | 3.93 | 60,893 | 3.95 | +0.02 | 192 | 254 |
| X-n303-k21 | 302 | 21736 | 23,540 | 8.30 | 23,362 | 7.48 | -0.76 | 276 | 268 |
| X-n401-k29 | 400 | 66154 | 68,958 | 4.24 | 68,717 | 3.87 | -0.35 | 278 | 260 |
| X-n502-k39 | 501 | 69226 | 70,811 | 2.29 | 70,867 | 2.37 | +0.08 | 135 | 42 |
| X-n701-k44 | 700 | 81923 | 87,401 | 6.69 | 87,494 | 6.80 | +0.11 | 286 | 279 |
| X-n1001-k43 | 1000 | 72355 | 78,501 | 8.49 | 78,475 | 8.46 | -0.03 | 312 | 72 |
| **mean** | | | | **5.47** | | **5.36** | | | |

**No effect.** Paired delta over 40 pairs: mean **-0.11%**, sd **0.60%**. The treatment is cheaper
on 19 pairs, dearer on 19, tied on 2. Sign test **p = 1.00**. The effect is 0.18x the pair-to-pair
spread.

That is the predicted outcome. An operator that cannot change the objective should not change the
objective when removed, and it did not.

**`X-n303-k21` at -0.76% is not a finding.** It is the largest row, but its own seed spread is 276
on a mean of 23,540, about 1.2%. The row sits inside its own noise.

## What this run does NOT measure

The tweak is an EFFICIENCY claim. `run_sa.py` records no iteration count, so nothing here says the
treatment ran more iterations. This run establishes only that quality did not degrade. Testing the
efficiency claim needs a separate measurement of iterations per second.

## Harness consistency, not a new finding

The baseline arm's 5.47% mean gap agrees with the 5.58% recorded on 2026-09-04 at the same budget
with 3 seeds, on a different day and from a different solver commit whose solver source is
identical. That is a check on the harness.

## References

*(none yet)*

## Links to here

- [experiment_logs/README.md](../../README.md) -- the experiment index, which carries this run's one-line summary and both arm commits
