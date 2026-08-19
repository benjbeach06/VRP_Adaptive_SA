# Operator scoring: uphill moves scored zero

**Status: implemented. Sound as a mechanism, unproven as a gain — and proving it needs more runs,
not a different experiment.**

The statistics are now expressive enough to distinguish exploration from exploitation. What remains
is the `TODO(rescore)` SCORE/COST split described below, an oracle for the improvement counter, and
patience.

## The original problem, kept for the record

`Operator.update_stats_for_accept` **scored** an accepted move as:

```python
sign = -1 if move.improvement < 0 else 1
score = max(0, sign * (abs(move.improvement) ** 1.5) / mean_cost)
```

An accepted move that made the solution worse scored `max(0, negative)` = **exactly zero**.

In simulated annealing, uphill acceptance is the escape mechanism. So an operator whose value is
exploration rather than exploitation could never earn weight, no matter how well it performed.

## What it scores now

```python
sign = -1 if improvement < 0 else 1
improved = improvement > 1e-9
score = max(self.explore_reward, sign * (abs(improvement) ** 1.5)) / max(mean_cost, 1e-9)
```

An accepted uphill move is now worth `explore_reward / mean_cost` instead of nothing.

**The floor is not a reward for exploring. It is a selection mechanism between explorers.** Because
the floor is divided by `mean_cost`, two operators whose accepted moves are all uphill are separated
by *how expensive their exploration is*: a cheap explorer earns more weight per accepted move than
an expensive one. Weight follows `score_sum / proposals`, so an operator that explores slowly but is
accepted often lands near one that explores quickly but is accepted rarely — which is the intended
equivalence. Frequency and cost trade off against each other, exactly as they already do on the
exploitation side.

The effect is to **gravitate toward cheap exploration**, not to decide whether exploration is worth
having. The solver spends some of its budget escaping local optima regardless; this makes it spend
that budget on the cheapest available source.

**Not yet proven useful.** Establishing that would need many more runs than have been spent —
`explore_reward` spanned nine orders of magnitude in the 149-trial search and the landscape was
indistinguishable from noise ([RESULTS.md](../RESULTS.md)). That is a statement about statistical
power, not about the mechanism. The honest position is that the rule is well-motivated and its
effect is below the current noise floor. Lowering that floor is the gating work -- and it is harder
than it looks, because timing-based operator weighting keeps a run non-reproducible even at a fixed
iteration count. See `joint-parameter-search.md`.

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

That invalidated the operator-selection tuning run outright, and the counter turned out to gate
plateau reheating rather than merely to report — so reheating had silently stopped firing. Both the
withdrawal and the rerun are in
[RESULTS.md](../RESULTS.md#parameter-tuning-a-withdrawal-and-a-null).

It is a direct instance of the warning above: a statistic was tuned against before it was fixed.
Worse, the statistic was *made* wrong by one of the parameters being tuned. The order in the Gate
below is not stylistic.

## Gate

None, but do the statistics before the formula, in that order.

**Add an oracle for the improvement counter as part of this work.** It is now a control input, not a
reporting field, and no test asserts anything about it — which is exactly why the suite stayed green
through the defect. `tools/preflight.py` checks it before a long run; that is a gate, not an oracle,
and the oracle still belongs in the stress harness.
