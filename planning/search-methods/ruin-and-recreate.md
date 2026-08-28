# Ruin and recreate

**Status:** ready to start. Prerequisites landed; this is the largest remaining gap.

## Problem

Every operator in the roster is a small local move: relocate a chain, swap two chains, reverse a
segment, split or combine a route. Modern VRP solvers get much of their strength from a large
neighborhood — remove k related customers, then reinsert them greedily — which no operator here
can express.

## Why it fits now

The lifecycle it needs already exists and is documented by a worked example.

**`_evaluates_by_applying`** lets an operator mutate while pricing. `_revert_info` is opaque — an
undo stack is a legal payload with no contract change. `PermuteRoute` uses the flag;
`DisposeOfEmptyRoutesBL` carries a real undo stack of `(route, predecessor)` pairs walked backwards.

**Removal and insertion are priced independently** as of the chain-delta split:

```
Route.cost_deltas_if_customer_chain_removed(chain)
Route.cost_deltas_if_customer_chain_inserted_before(visits, insert_visit)
```

The insertion half is destination-only. It takes detached visits and never asks where they came
from, because the removal already charged that side. That is exactly what a ruin step needs: it
removes customers long before it decides where they land. The older
`cost_deltas_if_customer_chain_moved` cannot be reused, because it prices both sides before either
happens and its depot and vehicle terms are "activates at the destination MINUS deactivates at the
source".

**`_SequentialCombineRoutes`** in `SimAnn_VRP_BLOperators.py` is a reference implementation of the
whole pattern, kept deliberately out of the roster.

**Relatedness** for Shaw removal, and candidate positions for reinsertion, both come from the
neighbor tables added for the guided operators.

## Three constraints, learned from the proof of concept

**Deltas must accumulate sequentially.** Overload is nonlinear in load, so each sub-step's delta
must be measured against the state the previous step left. Pricing all removals against the
original state and then all insertions does not sum correctly.

**Sub-steps must use `Route` mutators, not nested `OperatorBL.evaluate` calls.** `evaluate()` bumps
`sln.version` exactly once for an applying operator, and `revert()` asserts
`eval_version == sln.version - 1`.

**Empty-route disposal is the hazard.** Removing k customers can empty a route, and
`_dispose_empty_routes` runs every `empty_route_cleanup_interval` iterations and before every
snapshot. A disposed route in a pending undo stack is a dangling reference. Either suppress
disposal while a move is pending revert, or have the stack restore identity.

## Expected cost, and why it is acceptable here

A by-applying operator performs the move and undoes it on every **rejected** proposal. Measured on
`CombineRoutes`, that made the sequential version 3.7x slower than predictive at capacity 25 and
8.5x at capacity 400.

Combine is the worst case for the pattern: it has cheap predictive math and accepts almost never.
Ruin and recreate is the best case. There is no predictive alternative — you cannot price a
ruin-and-recreate without performing it — and greedy reinsertion mostly improves, so acceptance
should be high and the do-then-undo cost is amortized over moves that land.

## Gate

None. This is the next substantial piece of work.

## References

*(none yet)*

## Links to here

- [planning/README.md](../README.md)
