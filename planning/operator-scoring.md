# Operator scoring: uphill moves score zero

**Status:** ready to start. Small change, but it decides how the whole roster gets sampled.

## Problem

`Operator.update_stats_for_accept` scores an accepted move as:

```python
sign = -1 if move.improvement < 0 else 1
score = max(0, sign * (abs(move.improvement) ** 1.5) / mean_cost)
```

An accepted move that made the solution worse scores `max(0, negative)` = **exactly zero**.

In simulated annealing, uphill acceptance is the escape mechanism. So an operator whose value is
exploration rather than exploitation can never earn weight, no matter how well it performs.

## The measurement

From a 500-customer run, ranked by time per accepted move:

| operator | ms/accept | accepts | improving | proposals | LogWeight |
|---|---|---|---|---|---|
| ReverseClosestPairTogether | 0.17 | 68,566 | 15,981 | 370,386 | −0.31 |
| **RandomRouteReassignment** | **0.17** | 267 | **0** | **2,872** | −0.88 |
| SwapRouteTailsAtSharedDepot | 1.06 | 1,600 | 810 | 132,851 | +3.23 |

`RandomRouteReassignment` ties for the best efficiency in the roster and sits at the minimum-weight
floor. All 267 of its accepted moves were uphill, so all 267 scored zero.

## What is NOT yet known

Low `ms/accept` is not proof of worth. Cheap uphill moves are easy to generate and most of them are
noise. Whether those 267 escapes actually mattered is an ablation question, not something the table
settles. The finding is that the scoring **cannot express the question**, not that the operator is
being cheated.

## Related, already recorded in the source

`TODO(rescore)` on `update_stats_for_accept` notes that SCORE and COST answer deliberately different
questions with different denominators, and that the statistics cannot express the split properly
since the solver moved to "apply only when accepting". Fix the statistics first, then decide what
the score should divide by. Do not tune the formula against numbers that measure the wrong thing.

A second, smaller item in the same area: `mean_apply_time` is averaged over accepted moves only, so
for a rarely-accepted operator it rests on a handful of samples. `CombineRandomRoutes` was accepted
**once** in 33,654 proposals in one 60 s run, making its printed 268 us apply figure a one-sample
artifact. It feeds nothing but the end-of-run print — scoring reads `mean_call_time` — but it is
reported as though it were a cost.

## The floor has since landed, and it broke a counter

`explore_reward` now floors an accepted move's score at a small positive value, which is the fix this
plan called for. It also broke the improvement counter, because `OperatorStats.record_accept` decided
"did this improve?" by testing `score > 0` — and a positive floor removes the sign that test depended
on. Every accepted move counted as an improvement until `improvement > 1e-9` replaced it.

That invalidated the operator-selection tuning run outright. See
[METHODOLOGY.md](../METHODOLOGY.md#the-result-that-was-accepted-and-then-withdrawn).

It is a direct instance of the warning above: a statistic was tuned against before it was fixed.
Worse, the statistic was *made* wrong by one of the parameters being tuned. The order in the Gate
below is not stylistic.

## Gate

None, but do the statistics before the formula, in that order.

**Add an oracle for the improvement counter as part of this work.** It is now a control input, not a
reporting field, and no test asserts anything about it — which is exactly why the suite stayed green
through the defect.
