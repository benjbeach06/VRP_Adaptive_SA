# Improved modularization

**Status: identified early, deliberately deferred. Not started because of timeboxing, not because
it is unclear.**

## The problem

`SimAnn_VRP_Core_Model.py` is 4,662 lines. It holds the node types, the route and vehicle types, the
solution container, and all of the delta arithmetic that prices mutations. Those are four separable
concerns living in one file.

This is the first structural thing a reader meets, so it is worth saying plainly why it looks like
this.

## Why it was right at the time

Two decisions, both deliberate, both correct for the phase they were made in:

- **One file for the core model.** During initial development the model changed constantly, and
  every change touched several of those concerns at once. A single file made that cheap. Splitting
  early would have meant repeatedly re-drawing boundaries that had not settled yet.
- **Objects own their most relevant computations.** `Route` prices route-level deltas, `Vehicle`
  owns route chaining, and so on. Locality of that kind is extremely convenient when the question
  "where does this live?" has an obvious answer.

Both were traded against functional work — the operator lifecycle, chain moves, the delta
decomposition, the neighbor tables — which was more valuable per hour. The file size is the price
that was knowingly paid.

## The transformation

The important property is that this is **mechanical, not a redesign.**

Every method on a core-model type becomes a free function in an independent static evaluator, and
its `self` parameter becomes an explicitly typed parameter named for its class:

```python
# today, on the type
class Route:
    def total_distance(self) -> Num: ...

# after, in the evaluator
def total_distance(route: Route) -> Num: ...
```

`self` becomes `customer`, `first_visit`, `route`, `vehicle`. Nothing about the arithmetic changes.

That property is what makes the refactor safe to do late:

- **Behavior must be bit-identical.** Any objective difference is a bug in the move, not a design
  question. That is a far stronger verification than most refactors admit.
- **It can be done incrementally**, one family of functions at a time, with the suite green between
  each.
- **It does not interact with the functional roadmap**, so it can wait without accruing interest.

## What it buys

- **The data model becomes readable as a data model.** Types describe state; the evaluator describes
  arithmetic. Right now the two are interleaved across 4,662 lines.
- **The oracle twins become visibly parallel.** The naive recompute and the incremental delta would
  sit side by side as functions over the same types, which is what they conceptually are. Today one
  is a method and the other is a helper, and the symmetry is obscured.
- **Independent testability and import.** An evaluator that takes plain types can be exercised
  without constructing a solver.

## It also blocks design docs for the core model

A design doc covers a coherent unit. `SimAnn_VRP_Core_Model.py` is 4,662 lines holding four
separable concerns, so there is no unit to write about -- a doc would either cover everything or
carve an arbitrary slice.

So core-model design docs wait on this split. Anything that would need one right now gets recorded
where its CALLER is documented instead.

## Gate

After publication, and **not interleaved with functional work.** It is a large diff touching nearly
everything, so it wants a quiet window where the only question being asked is "is the objective
still identical?"

Sequence it against [inverted-view-refactor](inverted-view-refactor.md). That refactor changes how
position is represented, so doing it first would mean moving the same functions twice. Either do
this one after it, or accept the rework.
