# Farthest-insertion reorder operators

**Code:** `SimAnn_VRP_Operators.py`
**BL operator:** `PermuteChain`
**Helper:** [farthest_insertion_order.md](farthest_insertion_order.md)
**Governed by:** [../operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md)

Three operators sharing `_FarthestInsertionReorderBase`.

## Why they exist

Every other operator edits a route locally: move a customer, swap a pair, reverse a run. These
discard the ordering of a whole span and rebuild it.

That matters for **recovery**. A badly ordered neighbourhood can be fixed in ONE accepted move
instead of a long chain of intermediate states the acceptance test may refuse. Measured motivation:
from a deliberately bad start, the solver needed about 13x the time a greedy start needed to reach
the same objective. Measured at n=500, capacity 400.

**Route COUNT is the axis that matters, not customer count.** Capacity 400 gives about seven long
routes; capacity 25 gives about forty-seven short ones. Those are different problems for a
span-rebuild operator, and both are realistic -- long routes deliver safety pins, short routes
deliver dryers. Neither instance is the reference and neither is a caveat on the other.

## Design: selection only

They reuse `PermuteRoute` unchanged. **No new delta math, no new revert path.** The only new thing
is how the permutation is chosen.

`_choose_span` returns `(route, start, stop)`. Everything downstream -- fixed endpoints, the
helper call, the position mapping -- is written once in the base class. A fourth selection rule is
one method.

Fixed endpoints are the nodes **outside** the span: the neighbouring visits, or the route's depots
at the ends. That is what makes a whole-route rebuild well posed.

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

Two properties on `Operator` do that pricing, and both apply to all three: `exploit_only` restricts
them to improving moves, and `exploit_selection_penalty_factor` discounts their selection rate to
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

## `choose_random_nonempty_route_ordered`

These operators use the **ordered** variant of route selection.

`choose_random_nonempty_route` sets empty routes aside with a swap-remove and re-adds them at the
end, which permutes `all_routes`. Operands are drawn **positionally**, so a permuted RouteSet
changes which route a later draw returns. Selection alone would then divert the search while
leaving cost, vehicle chains and depot membership perfectly intact -- correct by every value check
and still wrong.

The ordered variant restores positions exactly via `undo_remove`, unwound LIFO. It is a separate
method so the other operators do not pay for bookkeeping they never read.

Found by stress: 93 `revert_not_exact` findings, all fingerprint field 3, cost identical.
