# Improved modularization

**IMPLEMENTED IN PART, commits `2593704`, `5d56b98` and `c9090b6` on branch
`modularize-core-model`.** The delta arithmetic shipped: it is now
[SimAnn_VRP_Core_Model/deltas/](../../SimAnn_VRP_Core_Model/deltas/), six modules of free
functions over the model types. The rest of the plan -- every OTHER method on a core-model type
becoming a free function -- did not ship and is not queued.

The plan as agreed follows, with one factual correction applied in place: the file was **4,940**
lines immediately before the work, not 4,662. How the work diverged, and why, is at the end. What
the divergence taught us is in
[retros/2026-09-07_core_model_modularization.md](../../retros/2026-09-07_core_model_modularization.md).

---

**Status: identified early, deliberately deferred. Not started because of timeboxing, not because
it is unclear.**

## The problem

`SimAnn_VRP_Core_Model.py` is 4,940 lines. It holds the node types, the route and vehicle types, the
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

A design doc covers a coherent unit. `SimAnn_VRP_Core_Model.py` is 4,940 lines holding four
separable concerns, so there is no unit to write about -- a doc would either cover everything or
carve an arbitrary slice.

So core-model design docs wait on this split. Anything that would need one right now gets recorded
where its CALLER is documented instead.

## Gate

After publication, and **not interleaved with functional work.** It is a large diff touching nearly
everything, so it wants a quiet window where the only question being asked is "is the objective
still identical?"

Sequence it against [inverted-view-refactor](../core-refactors/inverted-view-refactor.md). That refactor changes how
position is represented, so doing it first would mean moving the same functions twice. Either do
this one after it, or accept the rework.

## How this diverged, and why

The transformation itself shipped exactly as described: `self` became an explicitly typed first
parameter named for its class, and no arithmetic changed. `compare_deterministic.py` reported
IDENTICAL against the pre-refactor commit on all four fields. What diverged is the SCOPE, the
SHAPE, and the GATE.

### Only the delta arithmetic moved

The plan says "every method on a core-model type becomes a free function". 51 did -- every delta
computation on `Route`, on the four `RouteVisit` kinds, and on `FullSolution`. Nothing else did.
State accessors, mutators, linkage maintenance and the recompute oracles are all still methods.

`Route` fell from 2,046 lines to 833, and `routes.py` from 2,180 to 972. The four separable
concerns this plan names are now three files plus a subpackage, not one file. But the type still
holds both state and behaviour, so the plan's headline benefit -- "the data model becomes readable
as a data model" -- landed only for the pricing half.

### A file split came first, and it is not in this plan

`2593704` split the 4,940-line module into a ten-module package before any method moved. The plan
assumes a single file throughout and never proposes that step. It made the rest tractable: the
delta region was already isolated behind a `#region` marker, and the excision could assert against
it.

### Six modules, not one static evaluator

The plan proposes "an independent static evaluator" -- one unit. What shipped is a `deltas`
subpackage split by WHAT THE MOVE CHANGES: `visit_arcs` (the primitives), `route_moves` (the route
is the moving object), `customer_chain_moves` (customers are), `route_reordering` (same customers,
new order, one route), `route_segmentation` (split and combine), `solution_sweeps` (many routes at
once). Benjamin set that division and its names.

### `vehicle` never appeared, because `Vehicle` prices nothing

The plan predicts the parameter will be `customer`, `first_visit`, `route` or `vehicle`. The three
that shipped are `route`, `visit` and `sln`. `Vehicle` owns no delta computation at all -- it
holds the route chain and its cached counters, and every counter is written by the accounting
sink. That was measured before the work started, not discovered during it.

### Two renames were forced

`Route.travel_delta_if_removed` and the `RouteVisit.travel_delta_if_removed` PROPERTY carry the
same name. As methods they never met; as free functions they share a namespace. They are now
`travel_delta_if_route_removed` and `travel_delta_if_visit_removed`. The plan calls the
transformation mechanical, and it is, but "mechanical" does not mean name-preserving.

### One delta stayed a method

`RouteVisit.travel_delta_if_inserting_customer_before_this` has three implementations across the
visit hierarchy. A free function would need a three-branch `isinstance` chain in place of virtual
dispatch, on the insertion pricing path. Benjamin agreed to leave it.

### The oracle twins are still not parallel

This was the plan's second listed benefit. It did not land. The recompute-from-scratch twins
(`total_distance`, `path_distance`, `recompute_current_travel`, `recompute_current_load`) are
still methods on the types, while their incremental partners are now free functions one directory
down. The symmetry is no better than before, and arguably worse, because the two halves now sit in
different files.

### The gate was wrong about the blast radius, and the work ran before publication

The gate says "after publication, and not interleaved with functional work", because "it is a
large diff touching nearly everything". For the delta half that was not true. Outside the core
package there are 15 call sites in 3 files: 12 in `SimAnn_VRP_BLOperators.py`, 3 in
`tests/test_raw_delta_record.py`. Delta methods are called from the operator layer and almost
nowhere else, so the blast radius is bounded by that one file.

The work ran during the pre-publication window in which no new functionality is allowed, which is
the opposite of what the gate specifies. That was Benjamin's call, and the small blast radius is
what made it safe.

### It was not done incrementally, one family at a time

The plan says the split "can be done incrementally, one family of functions at a time, with the
suite green between each". It shipped as one commit for all six modules. Lifting one family at a
time would have meant either duplicate definitions or per-family call-site churn, and the lift was
done by tooling that had to see every call site at once to rewrite receivers into arguments.

The full gate ran at the end instead: IDENTICAL, 120 tests, `stress.py` clean with the detector
shown to fire under injection, pyright at 0 errors.

### `inverted-view-refactor` was not done first, so the rework is accepted

The Gate section offers that choice explicitly.
[inverted-view-refactor](../core-refactors/inverted-view-refactor.md) is still deferred and gated,
so the delta functions may have to move again when position representation changes.

### The design-doc block is partly lifted

`deltas/` is now a coherent unit with a stated contract -- nothing in it mutates, nothing in it
reads an objective coefficient, and the dependency on the data model runs one way. That is
writable as a design doc today. The data model itself still is not.

## References

- [planning/core-refactors/inverted-view-refactor.md](../core-refactors/inverted-view-refactor.md)
- [retros/2026-09-07_core_model_modularization.md](../../retros/2026-09-07_core_model_modularization.md)
  -- the retro covering the period this landed in; what the divergence taught us.

## Links to here

- [retros/2026-09-07_core_model_modularization.md](../../retros/2026-09-07_core_model_modularization.md) -- the retro for the period this landed in
- [planning/implemented/README.md](README.md) -- lists this as implemented in part
- [planning/operator-selection/budget-gated-selection.md](../operator-selection/budget-gated-selection.md) -- proposes cost-estimate field placement for budget gating
- [planning/README.md](../README.md)
- [planning/experiments/joint-parameter-search.md](../experiments/joint-parameter-search.md)
- [raw-delta-accounting.md](raw-delta-accounting.md)
