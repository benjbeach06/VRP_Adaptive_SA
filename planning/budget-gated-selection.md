# Budget-gated operator selection

**Status: not started. Necessary at some point, not optional.** Benjamin's design.

## The problem

Adaptive weighting balances cost against effect, but only **after** an operator has run. It learns
from measured `mean_cost`, so it cannot price an operator it has never proposed.

That is fine when every operator is cheap. It stops being fine now that the roster holds operators
that are O(k^2) in route length.

**The failure case: a large instance with a small budget.** An expensive operator gets proposed,
consumes a large share of the budget in a single call, and the run ends having done almost no work.
The weighting never gets enough samples to demote it, because demoting it requires running it.

The larger the instance, the worse this is -- which is exactly backwards, since large instances are
where throughput matters most.

## The shape

**Gate selection on the remaining budget.** Start with the cheap operators only. Admit more
expensive ones as the run demonstrates it can afford them.

- **Estimate cost early.** Measure operator cost in the opening phase of a solve, when proposals
  are cheap and plentiful. Those estimates feed the gate.
- **Expand the roster as time sufficiency is established.** An operator is admitted once the
  remaining budget can absorb many calls at its estimated cost -- not one call.
- **Contract near the end.** The same logic in reverse: an operator whose expected cost is a large
  fraction of the time left should not be proposed at all.

## The end-of-run rule, concretely

**Benjamin's, 2026-08-20.** Near the end of the solver budget, do not select an operator whose
expected cost exceeds **one quarter of the remaining budget**.

Expected cost is the operator's average RECORDED cost, or a dynamic estimate when it has not run yet.
An operator with no history still needs a number, so the estimate has to exist either way -- which is
the same requirement the early-phase cost estimate above already creates.

**The cost of the rule itself is negligible.** It wastes a few microseconds at the very end of a run
by declining moves that would have been affordable. That is nothing against losing the last seconds
of a solve to one call that could not finish.

One quarter is a starting value, not a tuned one.

The gate is about **affordability**, not about value. Weighting still decides value among the
operators that are admitted.

## Why not just cap operator cost

Capping span length would work, and it throws away the reason the operator exists. A whole-route
rebuild is the move that fixes a route's global shape in one step. Making it always cheap makes it
always weak.

The affordability question belongs to the solver, which knows the budget. It does not belong to the
operator, which does not.

## Gate

None on correctness. It becomes urgent the first time the solver is run on a large instance with a
short budget, which has not happened yet -- every measurement so far used budgets generous relative
to instance size.

Related: [family-generation](family-generation.md) -- a dynamically generated family
gates its own operator creation on the same cost estimates. [module-structure](module-structure.md) for where the estimate would live, and
[route-distance-tracking](route-distance-tracking.md), which removes one of the current
per-proposal costs. Design context in
[design/span_reorder/reorder_operators.md](../design/span_reorder/reorder_operators.md).

## References

- [family-generation.md](family-generation.md) -- dynamically gated family creation on the same cost estimates
- [design/span_reorder/reorder_operators.md](../design/span_reorder/reorder_operators.md) -- design context for the span reorder operators
- [module-structure.md](module-structure.md) -- where per-operator cost estimates would be stored
- [route-distance-tracking.md](route-distance-tracking.md) -- removes one of the per-proposal costs this plan would gate

## Links to here

- [design/span_reorder/farthest_insertion_ops.md](../design/span_reorder/farthest_insertion_ops.md)
- [README.md](README.md)
- [operator-selection.md](operator-selection.md)
- [solver-progress-metric.md](solver-progress-metric.md)
