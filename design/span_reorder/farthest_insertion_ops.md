# Farthest-insertion reorder operators

**Code:** `SimAnn_VRP_Operators.py` -- `_FarthestInsertionReorderBase` and its three subclasses
**Base:** [reorder_operators.md](reorder_operators.md)
**Algorithm:** [farthest_insertion_order.md](farthest_insertion_order.md)
**Governed by:** [../operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md)

Three operators that differ ONLY in which span they choose. The rebuild itself is
`farthest_insertion_order`, and everything between span and permutation is the shared base.

## Why they exist

Every other operator edits a route locally -- move a customer, swap a pair, reverse a run. These
discard the ordering of a whole span and rebuild it, so a badly ordered neighbourhood is fixed in
ONE accepted move rather than a chain of intermediate states the acceptance test may refuse.

Measured motivation: from a deliberately bad start the solver needed about 13x the time a greedy
start needed to reach the same objective, at n=500 capacity 400.

## The three

| operator | route choice | span |
|---|---|---|
| `ReorderSpanByFarthestInsertion` | uniform | uniform position, uniform length |
| `ReorderRandomRouteByFarthestInsertion` | uniform | the whole route |
| `ReorderLongRouteByFarthestInsertion` | weighted by squared distance | the whole route |


## Decisions and why

**Span length is uniform, not geometric.** `geometric_chain_length` has mean 4, and a 4-point
rebuild barely differs from any other order. It would not justify an O(k^2) operator. Uniform gives
mean span about half the route.

**The span is no longer anchored.** An earlier version anchored on a spatially close,
sequence-distant pair. That existed to compensate for nearest neighbour's weakness. Farthest
insertion rebuilds a span well wherever it sits, so the anchor bought little and cost an O(route
length) scan per proposal.

**Route weighting squares the distance.** A route twice as long is four times as likely. A rebuild
helps most where the ordering has the most slack, and that is superlinear in route length. One
weighted draw: cumulative squared distance, scale a [0,1) sample by the total, `bisect_left`.

**An identity reordering reports NOOP, not a zero-delta move.** When farthest insertion returns the
span unchanged, `farthest_insertion_order` returns an empty list rather than the identity
permutation. `PermuteChain` then reports NOOP. Otherwise a proposal that changes nothing would price
as a legitimate VALID move worth zero, which hides degeneracy from the counters that exist to show
it.

**They are deliberately expensive.** O(k^2) against O(1) or O(k) elsewhere.

That is the point, and it is not a compromise. Construction quality and construction cost **both**
matter. The job of a roster is not to pick the best point on that trade -- it is to **offer
operators that vary in cost and in effect**, and let adaptive selection do the balancing.

These three exist to occupy the expensive-and-effective end, which the roster previously lacked.

## How they are priced

`exploit_only` restricts all three to improving moves. A heuristic rebuild can genuinely produce an
ordering worse than the one already there, and accepting one overwrites the route with the same
worse answer every time, which is stagnation rather than exploration. See
[../operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md).

Cost is priced by the roster-wide penalty, `min(cost) / cost`, measured on the instance actually
being solved and recomputed every segment. Nothing about that is specific to these three. See
[../operator_selection/dynamic_penalty.md](../operator_selection/dynamic_penalty.md).

> **SUPERSEDED 2026-08-22.** These operators used to carry hand-set
> `exploit_selection_penalty_factor` values that discounted their selection rate to amortize O(k^2)
> toward O(k), with a x4 correction on the span variant because half a span costs a quarter. Stage 2
> of the scoring rework removed them; every operator's factor is 1.0 now. They are recorded because
> they are why the measured penalty exists: a per-operator constant is a magic number, and each one
> added an ablation factor.

**Whether the expensive end is priced correctly is still an ABLATION question**, and it is open. The
comparison that matters is against `ReorderShortSpanExactly`, whose cost does not scale with the
problem at all.

**Pricing is also incomplete in one structural way.** Weighting balances cost only AFTER an operator
has run. On a large instance with a small budget, one of these can consume the budget in a single
proposal, and no amount of feedback reacts in time. Gating selection on the remaining budget is what
closes that -- see
[planning/operator-selection/budget-gated-selection.md](../../planning/operator-selection/budget-gated-selection.md).


## Known cost, accepted on purpose

`ReorderLongRouteByFarthestInsertion` is **O(number of routes) per proposal**. Weighting by squared
distance needs every route's length, so `_choose_span` builds a cumulative array over the whole
route set on every call.

It reads `route.current_travel`, the sink-written cache, so each route costs one attribute read
rather than a walk of its path. That is what makes the scan affordable at its current width. The
cache arrived with per-route travel accounting; before it, the same selection was O(total
customers). See
[../raw_delta_accounting/README.md](../raw_delta_accounting/README.md).

## References

- [farthest_insertion_order.md](farthest_insertion_order.md)
- [planning/operator-selection/budget-gated-selection.md](../../planning/operator-selection/budget-gated-selection.md)
- [design/operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md)
- [reorder_operators.md](reorder_operators.md)
- [design/operator_selection/dynamic_penalty.md](../operator_selection/dynamic_penalty.md) -- the measured cost penalty that prices these operators now, in place of their removed hand-set factors
- [design/raw_delta_accounting/README.md](../raw_delta_accounting/README.md) -- maintains the cached route distance the long-route draw reads once per route

## Links to here

- [design/README.md](../README.md) -- design folder index
