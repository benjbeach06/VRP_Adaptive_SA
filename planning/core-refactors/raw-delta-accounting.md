# Raw-delta accounting

**Status: not started. Infrastructure. Prerequisite for
[route-distance-tracking](route-distance-tracking.md) and everything downstream of it.**

Function-level touch list: [raw_delta_accounting_refactor_guide.txt](../raw_delta_accounting_refactor_guide.txt).

## The problem

Every objective term is currently accounted twice, and the two derivations are independent.

A mutation is priced by a `cost_deltas_if_*` or `cost_deltas_for_*` method, which derives the
activation and overload consequences itself. The mutation is then performed by a core-model method,
which derives the same consequences again as inline bookkeeping. Nothing forces the two to agree.

That is a dual-truth structure. When the two derivations disagree the incremental state is corrupt,
the corruption is silent, and it persists. It is a worse failure than a missing update, which at
least tends to surface as a wrong objective.

The duplication is also large. The core model holds roughly 29 methods whose only job is to derive
accounting consequences for one specific mutation:

| family | count | example |
|---|---|---|
| depot usage counts | 7 | `depot_num_usage_deltas_if_inserted_before` |
| depot activation | 9 | `depot_activation_delta_if_removed` |
| vehicle activation | 3 | `vehicle_activation_delta_if_customers_added` |
| overload, route and vehicle | 10 | `is_vehicle_overloaded_delta_if_load_changes_from_other_route` |

Each of the 24 aggregators has to know which of these its own mutation needs. That per-site
knowledge is the maintenance cost, and it grows with the product of mutations and objective terms.

One symptom is already in the tree: `unlink_from_route_no_depot_accounting` exists only because
accounting is entangled with mutation, so a caller needed the mutation without the bookkeeping.

## The shape

Split accounting into three stages, and give the middle one a single owner.

1. **Raw deltas.** The core model reports only what structurally changed. Distance deltas, load,
   customer count, start depot, and route-to-vehicle assignment. No activation, no overload, no
   objective terms.
2. **Reconstruction.** A static processor turns the raw record plus current aggregate state into an
   `ObjectiveTermDelta` and an accounting record. This is the only place a step function is
   evaluated.
3. **Bookkeeping.** `OperatorBL` applies the accounting record on apply, and its inverse on revert.
   Its drivers already gatekeep the lifecycle, so this lands once and covers every subclass.

The key simplification: **the core model reports `num_use`-style changes, never `is_used`-style
ones.** Activation is a step function of a count, so it is nonlinear in the count and cannot be
derived mutation-locally without knowing the base. Today every mutation site solves that problem
separately. After, it is solved once.

### Transition form where the base is needed

Fields whose objective term is a step function carry `(initial, final)`, not a delta: route load,
customer count, start depot, and route-to-vehicle assignment. Distance carries a plain delta,
because distance is linear and deltas add.

Transition form does three things at once. Composition becomes one rule — chain on the route key,
and drop the entry when `initial == final`. The processor stops needing a shadow state for
sequential moves, because the composed record already carries the final value. And revert restores
a stored value rather than adding a negated one.

Route creation and disposal need no special case. A created route transitions from an `UNASSIGNED`
sentinel, a disposed one transitions back to it, and a create-then-dispose pair composes to
`UNASSIGNED -> UNASSIGNED`, which the drop rule removes.

### The prototype already exists

`Route.depot_activation_delta_from_depot_num_usage_deltas` is this design in miniature, for depots
only. It takes count deltas plus `depot_route_starts` and returns a resolved activation delta. The
processor generalizes that one function to vehicles, routes, and overload.

So this is not a new mechanism. It is one proven local pattern applied to every aggregate.

## What it buys

**It removes the dual truth.** One derivation, one owner, one place for a step function to be
evaluated. Oracles keep their role as initialization and periodic audit rather than as the only
thing standing between the two derivations.

**Objective terms stop costing per-mutation work.** A new term becomes a response function over an
already-tracked count. The four terms currently wanted are all piecewise-linear over one count:

| term | count it responds to | shape |
|---|---|---|
| vehicle activation | routes on the vehicle | step at 0 |
| route overload | route load | hinge at capacity |
| depot load time | active routes on the vehicle | linear |
| delivery time | customers on the vehicle | linear |

`vehicle-specific cost per active route` is then a per-vehicle coefficient, not new machinery.

**It removes a recompute.** Raw distances computed during pricing are carried into apply instead of
being derived a second time there.

## What it does not do

It does not add distance tracking. Per-route and per-vehicle distance become cheap to add
afterwards, because the full deltas already exist, but a new accounting field carries its own blast
radius and enables its own optimizations. That stays [route-distance-tracking](route-distance-tracking.md),
sequenced after this.

It does not start [module-structure](module-structure.md). The processor is a static class, which
is the same shape that plan proposes for the whole core model, but its file placement is not a
design question here. That refactor stays deferred.

## What it costs

Comprehensive, and not stageable. A per-term or per-operator split does not exist, because the
accounting structure itself is being replaced — there is no boundary to put a partial conversion
on. Running old and new paths in parallel is also unavailable: core-model mutators do their
accounting inline, so a parallel path means duplicating the mutators.

Surface, from the [touch list](../raw_delta_accounting_refactor_guide.txt):

| layer | what happens | size |
|---|---|---|
| raw computation (`travel_delta_if_*`) | unchanged | ~26 methods |
| accounting derivation | absorbed into the processor | ~29 methods |
| per-mutation aggregation (`cost_deltas_*`) | returns raw instead of objective terms | 24 methods |
| core-model mutators | inline bookkeeping stripped | ~44 call sites |
| `OperatorBL` | three driver hooks | 1 class, 11 subclasses |

## Verification

The existing suite is the gate, and it is already shaped for this. `assert_operator_contract`
checks purity, then every objective term against ground truth, then the oracles, then exact revert.
`objective_terms()` recomputes from scratch, so the per-term comparison is a true oracle rather than
a cache compared against itself. `stress.py --inject-delta` confirms the detector fires.

Two additions:

- **Composition coverage.** Compose the raw records for N moves, reconstruct once, and assert the
  result equals applying the N moves one at a time with reconstruction after each. There is implicit
  coverage today through `_SequentialCombineRoutes` and `cost_deltas_for_removing_empty_routes`;
  the merge rule itself has none.
- **New `ObjectiveTermDelta` fields must have no default.** `term_deltas()` in the harness builds
  the tuple with explicit keyword arguments, so a field with a default is silently skipped by every
  per-term assertion.

Run the full matrix, not the reduced default. A change to the accounting foundation earns it.

## Gate

None on its own. This is the gate for others.

Sequence it **before** [route-distance-tracking](route-distance-tracking.md), which is in turn the
blocker for [vehicle-time-limits](../problem-model/vehicle-time-limits.md). Doing distance tracking first would mean
adding a cached field at ~44 mutation sites by hand, then removing those updates again when the
processor takes ownership.

Not interleaved with [module-structure](module-structure.md) or
[inverted-view-refactor](inverted-view-refactor.md). All three touch the core model broadly, and
concurrent large diffs there make "is the objective still identical?" unanswerable.

## References

- [route-distance-tracking.md](route-distance-tracking.md) -- sequenced after this; the full deltas make it cheap, but a new accounting field carries its own blast radius
- [planning/problem-model/vehicle-time-limits.md](../problem-model/vehicle-time-limits.md) -- downstream of route-distance-tracking; its per-vehicle aggregates are what this infrastructure exists to make cheap
- [module-structure.md](module-structure.md) -- proposes the same static-class shape for the whole core model; deliberately NOT started by this plan
- [inverted-view-refactor.md](inverted-view-refactor.md) -- also a broad core-model diff; must not run concurrently with this one

## Links to here

- [planning/README.md](../README.md)
- [route-distance-tracking.md](route-distance-tracking.md) -- downstream plan whose old per-site-update shape is replaced by this refactor's processor output
- [retros/2026-08-27_raw_delta_accounting_plan.md](../../retros/2026-08-27_raw_delta_accounting_plan.md) -- the session that produced this plan, including the design attribution
