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
operators that vary in cost and in effect**, and let adaptive selection do the balancing. Score
divides by `mean_cost`, so the solver can prefer cheap operators on large instances and expensive
ones on small instances without anybody choosing in advance.

These three exist to occupy the expensive-and-effective end, which the roster previously lacked.

**SUPERSEDED 2026-08-22: the penalty factors are gone.** They were removed in stage 2 of the scoring
rework, so these operators now carry no cost discount at all until the adaptive penalty lands. The
paragraph below records what the attempt was.

**How to PRICE that end is still open.** The penalty factors were a first attempt, and they sat
beside `ReorderShortSpanExactly`, whose cost does not scale with the problem at all. Whether these
three are priced correctly against it, and against the cheap operators, is an ABLATION question. Do
not treat the current factors as settled.

Two properties on `Operator` do that pricing, and both apply to all three: `exploit_only` restricts
them to improving moves. `exploit_selection_penalty_factor` used to discount their selection rate to
amortize O(k^2) toward O(k). The span variant carries a x4 correction, since half a span costs a
quarter. Full reasoning in
[../operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md).

**This is incomplete.** Weighting balances cost only after an operator has run. On a large instance
with a small budget, one of these can consume the budget in a single proposal. Gating selection on
the remaining budget is needed at some point -- see
[planning/budget-gated-selection.md](../../planning/budget-gated-selection.md).


## Known cost, accepted on purpose

`ReorderLongRouteByFarthestInsertion` is **O(total customers) per proposal**, because no route
caches its own length and `total_distance()` walks the path.

Accepted for now rather than fixed. It measures whether weighting helps BEFORE paying for the
infrastructure. `planning/route-distance-tracking.md` makes it O(1).

## References

- [farthest_insertion_order.md](farthest_insertion_order.md)
- [planning/budget-gated-selection.md](../../planning/budget-gated-selection.md)
- [design/operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md)
- [reorder_operators.md](reorder_operators.md)

## Links to here

- [design/README.md](../README.md) -- design folder index
