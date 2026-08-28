# Score, weight, and the selection penalty

`adj_weights[op] = op.weight * op.exploit_selection_penalty_factor * op.penalty` is the value
selection draws on. This doc covers `op.weight` and `op.penalty`.
`exploit_selection_penalty_factor` is covered in
[exploitation_governance.md](exploitation_governance.md).

## The formula

**On accept** (`Operator.update_stats_for_accept`):

```python
gain  = improvement ** 1.5 if improvement > 0 else 0.0
score = max(explore_reward, gain)
```

Improvement magnitude only. `explore_reward` floors it, so an accepted uphill move is never worth
zero -- that is the whole exploration contribution to weight.

**Weight**, once per segment (`update_weights`):

```python
average_score = score_sum / num_proposals if score_sum > 0 else 0
p = 1 - exp(-op.segment_time / weight_time_constant)
weight = (1 - p) * weight + p * average_score
```

An EMA of score per PROPOSAL, not per accept, so an operator is priced by how often it fails as
well as by what it earns when it succeeds. The decay rate `p` comes from the operator's own
elapsed time -- see [../schedule/time_based_schedule.md](../schedule/time_based_schedule.md).

**Penalty**, once per segment:

```python
best = min(op.scoring_cost for op in operators)
op.penalty = best / op.scoring_cost
```

A pure cost ratio in `(0, 1]`, exactly 1.0 for the cheapest operator in the roster.

## Cost is priced exactly once

**Weight answers "how much per try". Penalty answers "how expensive was the try".** They multiply,
and cost enters only through the penalty.

The obvious alternative is to divide the score by cost as well, so that weight is already a
cost-adjusted rate. That prices cost twice: `adj_weight` would fall off as `1/cost**2`, against a
roster whose cost spread is already three orders of magnitude wide. Keeping the two factors
answering separate questions is what makes their product readable.

Normalization is GLOBAL, against the whole roster's cheapest operator, never per-family. A
family's weight is its best member's ADJUSTED weight and that carries to the root, so a per-family
maximum would make weights mean different things in different families and skew full-family
selection. Only magnetism is family-local -- see
[hierarchical_magnetism.md](hierarchical_magnetism.md).

## Cost accounting

`scoring_cost` is 1.0 when `weight_by_time` is off, which is what makes a run reproducible. With it
on, there are two branches: `mean_valid_call_time` once the operator has a valid call, and its
all-proposal `mean_call_time` before that. A never-proposed operator lands near zero through the
empty-count guards, so everything gets sampled early. **There is no floor** holding the valid cost
at or above the proposal cost.

Three accumulators feed this, and they are easy to confuse:

- **`mean_valid_call_time`** -- `(_valid_propose_time_total + _apply_time_total) / (_apply_count +
  num_useful_calls)`. Invalid and no-op propose time is excluded from BOTH numerator and
  denominator, so a cheap degenerate return cannot drag an operator's price down.
- **`stats.proposals`** -- the weight EMA's denominator. Counts EVERY proposal, valid or not, so an
  operator that mostly returns no-op is priced for that rather than judged only on the calls that
  worked.
- **`segment_time`** -- per-operator wall clock for the segment, read by the weight EMA's decay
  rate, NOT by `scoring_cost`. Includes apply time.

## Dead code retained

`improvement_estimate`, `ESTIMATE_FLOOR` and `cost_exponent` are all unread. Three sites are
commented out rather than deleted: the EMA that wrote the estimate, the `_fold_estimates` /
`_lift_unproposed` pair that magnetised it up the tree, and the penalty term that consumed it.
`cost_exponent` is still constructed and propagated to every operator, but its one use site sits
inside the commented-out cost division in the score. Why the estimate-driven penalty they served was
abandoned is in
[planning/implemented/scoring-rework.md](../../planning/implemented/scoring-rework.md).

Kept in place and commented rather than stashed -- a stash goes stale as the surrounding code moves.

## Related experiments

- [experiment_logs/ablations/2026-08-23_tuned_vs_stage1/](../../experiment_logs/ablations/2026-08-23_tuned_vs_stage1/README.md)
  -- this formula, tuned, against the scoring rework's stage-1 commit. Informed the shipped
  parameter defaults.
- [experiment_logs/ablations/2026-08-22_scoring_rework_trajectory/](../../experiment_logs/ablations/2026-08-22_scoring_rework_trajectory/README.md)
  -- per-stage trajectory and per-operator statistics. Informed pricing cost in the penalty alone.

## References

- [hierarchical_magnetism.md](hierarchical_magnetism.md) -- the sibling-local magnet that acts on
  `weight` between the EMA and the penalty.
- [exploitation_governance.md](exploitation_governance.md) -- the third factor in `adj_weights`.
- [../schedule/time_based_schedule.md](../schedule/time_based_schedule.md) -- `segment_time` and
  `weight_time_constant`, which set the weight EMA's decay rate.
- [planning/implemented/scoring-rework.md](../../planning/implemented/scoring-rework.md) -- the plan
  this came from, and why its improvement-weighted penalty was abandoned.

## Links to here

- [hierarchical_magnetism.md](hierarchical_magnetism.md) -- cites this for what is not family-local,
  and for the penalty its fold must not read.
- [exploitation_governance.md](exploitation_governance.md) -- names this as the replacement for its
  hand-set factor.
- [../schedule/time_based_schedule.md](../schedule/time_based_schedule.md) -- cites the weight
  EMA's decay clock as one of the wall-clock paths determinism has to close.
- [planning/implemented/scoring-rework.md](../../planning/implemented/scoring-rework.md) -- the
  plan this became; points here for what shipped.
- [README.md](README.md) -- summarises this doc in the folder index.
- [../README.md](../README.md) -- summarises this doc in the top-level index.
- [family_selection.md](family_selection.md) -- tree that cost-adjusted weights feed
- [planning/implemented/README.md](../../planning/implemented/README.md)
- [planning/implemented/forget-benefit-not-cost.md](../../planning/implemented/forget-benefit-not-cost.md)
- [planning/operator-selection/operator-selection.md](../../planning/operator-selection/operator-selection.md)
- [RESULTS.md](../../RESULTS.md) -- cites this as the pricing fix that would let K be learned rather than hand-swept
