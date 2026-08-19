# Asymmetric distances via a supplied distance oracle

**Status: not started. Read the operator cost section before scheduling this — it is larger than it
looks.**

## The problem

Distance is euclidean and computed inline. Real road networks are not symmetric: one-way streets,
divided highways, turn restrictions, and the well-known cost asymmetry between left and right turns
all mean `d(a, b) != d(b, a)`.

## The shape

A **distance oracle supplied by the caller**, rather than a flag on the model:

```python
class DistanceOracle(Protocol):
    is_directed: bool          # default TRUE for a supplied oracle
    def distance(self, a: Node, b: Node) -> Num: ...
```

The built-in euclidean implementation sets `is_directed = False`. Anything the caller supplies
defaults to `True`.

**That default is deliberate and it is the conservative direction.** Symmetry is not a property of
distance — it is an *assumption the delta arithmetic exploits*. Assuming symmetry for an oracle that
is actually directed produces silently wrong prices, and wrong prices in a minimization search do
not crash; they just quietly steer it somewhere worse. Assuming direction when the oracle happens to
be symmetric costs only speed. Wrong-and-fast is the bad corner, so the default points away from it.

## What it costs the operators — read this first

Symmetry is not a minor optimization here. It is load-bearing for the roster's most valuable
operator.

**Reversing a chain is O(1) only because the arcs inside it are unchanged.** Under symmetry,
reversing `a -> b -> c -> d` leaves `b->c` costing exactly what `c->b` costs, so only the two
boundary arcs need repricing. Under asymmetry **every internal arc flips and must be repriced**, and
the delta becomes O(chain length).

That lands on:

| operator | ablation evidence |
|---|---|
| `RandomCustomerChainReversal` | **+1.70% at σ = 18.7** — the largest single effect measured, larger than every other operator combined |
| `ReverseClosestPairTogether` | +0.70% at σ = 6.9 |
| `ReassignChainNextToNeighbor` and other chain moves | reversed insertion is one of the options priced |

So enabling directed mode does not merely add a branch. It changes the complexity class of the two
operators the roster most depends on, and those two are cheap-and-high-volume — which is precisely
*why* they matter (see [RESULTS.md](../RESULTS.md)). Making them more expensive per call
attacks the mechanism that makes them valuable.

**This must be measured, not assumed away.** Run the ablation again in directed mode. It is entirely
possible the right answer is a different roster for directed instances rather than the same roster
running slower.

## Less-obvious dependencies: code that computes distance ITSELF

A supplied oracle only takes effect where distance is actually asked for. Every site that computes
distance inline keeps using euclidean geometry and silently ignores the oracle. Those sites are the
real work of this plan, and they are easy to miss because none of them looks like a distance
function.

Known so far, NOT a complete audit:

- **`farthest_insertion_order`** -- calls `math.dist` directly and squares coordinate differences by
  hand. It reorders customers, so a directed oracle changes its answer completely. See
  [design/span_reorder/farthest_insertion_order.md](../design/span_reorder/farthest_insertion_order.md).
- **`nearest_indices` and the neighbour tables** -- numpy squared distances over a coordinate
  array. Under direction, "nearest TO c" and "nearest FROM c" differ, so one table becomes two.
- **`Route.closest_non_adjacent_customer`** -- used by the reversal selectors.
- **`make_initial_solution`** -- construction walks the neighbour tables, so it inherits whatever
  they assume.

**Audit before starting.** Grep for `math.dist`, `hypot`, and hand-written squared differences. A
missed site does not crash; it prices one part of the search with the wrong geometry, which is the
hardest class of bug to see.

## Design notes

- Keep the symmetric fast path. `is_directed = False` must cost exactly what it costs today, or the
  feature has taxed the common case to serve the rare one.
- The reversal operators need two implementations, selected once at construction rather than
  branched per call.
- A supplied oracle is likely to be a lookup table rather than a formula, so calls may be cheaper
  than euclidean — worth measuring before assuming directed mode is slower overall.
- The neighbor tables (`nearest_indices`) assume symmetry when they treat "nearest to" as mutual.
  Under direction, "nearest to *c*" and "nearest from *c*" differ, and the guided operators care
  about the outbound direction.

## Gate

Do not start this before [vehicle-time-limits](vehicle-time-limits.md). Time limits make the model
recognizably realistic for a much smaller cost; asymmetry makes it realistic in a narrower way for
a much larger one.

The gate to start: a concrete instance that needs it. Directed distance is a feature with a
customer, and building it speculatively means paying the reversal-operator cost above for a
capability nobody is currently asking for.
