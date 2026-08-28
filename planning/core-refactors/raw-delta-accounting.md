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
3. **Bookkeeping.** `FullSolution` owns one call that applies an **already-processed** accounting
   record, propagating update handles down to its vehicles and routes. Nothing else writes a derived
   cache. `Operator` drives it on apply and drives its inverse on revert. That is one class and four
   methods, with no subclass overriding any of them, so it lands once and covers all 34 operators.

**Stage 2 and stage 3 must not merge.** The processor is a dedicated class in its own file and is
the only place a step function is evaluated. `FullSolution` applies resolved numbers and decides
nothing. Merging them is tempting, because `FullSolution` already holds the state the processor
reads — and it would put step-function evaluation back inside the core model, which is the dual
truth this plan exists to remove.

**The check:** if the apply call contains a threshold comparison or a zero-crossing test, the
processing has leaked into the sink.

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

It does not start [module-structure](module-structure.md). The processor is a static class in its
own file, `SimAnn_VRP_Accounting.py`. That is one file, not a reorganization of the core model, and
that refactor stays deferred.

`RawDeltaRecord` stays in the core model beside `ObjectiveTermDelta`. The core model produces the
record, so housing it with the processor would make the core model import the processor and close a
cycle. Import direction is `Core_Model` <- `Accounting` <- `BLOperators`, which gives a structural
completion check: **the core model must never import the processor.** If it has to, accounting is
still entangled with mutation.

## What it costs

Comprehensive, but stageable per objective term.

The seam is not per operator, and not old-path-beside-new-path. Both of those fail, because the
accounting structure itself is being replaced and core-model mutators do their accounting inline.
The seam that exists is the objective term. `ObjectiveTermDelta` is a five-field NamedTuple that
adds componentwise, so a term can be produced by the old path or the new one and the sum stays
correct, as long as exactly one side produces each term.

Two things open that seam. The L3 aggregators temporarily return both delta types side by side. The
processor starts as a stub that accepts the raw record and does nothing.

Six steps. Each is a physical code edit that moves a term, so there is no runtime flag and nothing
to pay per call.

| step | what moves | cache stripped |
|---|---|---|
| 0 | plumbing: record, stub processor, dual return, missing oracles | none — behavior identical |
| 1 | `travel_distance` | none |
| 2 | `total_route_overload` | none |
| 3 | `depots_activated`, `vehicles_activated`, `vehicles_overloaded` | `depot_route_starts`, `num_routes_overloaded`, `num_routes_with_customers` |
| 4 | end-depot usage tracking | new field |
| 5 | cleanup: delete the dual return and the dead L2 methods | — |

**Steps 1 and 2 strip no cache.** Distance and route overload are backed by raw caches whose step
functions are already evaluated at read time, so only the derivation moves.

**Step 3 is indivisible.** Its three terms all read the same two transitions, route activity and
route-to-vehicle assignment, and one mutation updates all three caches in a single body. Converting
one of them alone means deriving those transitions in the processor and in the mutator at the same
time — a temporary patch with no place in the final code.

**Step 4 adds end-depot usage.** It is derivative from route changes, so the processor carries it
once route transitions are trusted. The work is emitting the explicit end-depot changeset, which
three operators need plus the route creation path. Hard in the old shape, easy in this one, and
sequenced last because a new accounting field should not be vetted alongside the extraction that
makes it cheap.

Commit per step while working, then squash. The side-by-side state is scaffolding, not history.

Surface, from the [touch list](../raw_delta_accounting_refactor_guide.txt):

| layer | what happens | size |
|---|---|---|
| raw computation (`travel_delta_if_*`) | unchanged | ~26 methods |
| accounting derivation | absorbed into the processor | ~29 methods |
| per-mutation aggregation (`cost_deltas_*`) | returns raw instead of objective terms | 24 methods |
| core-model mutators | inline bookkeeping stripped | ~44 call sites, all in the core model |
| processor (new file) | resolves raw + state into terms and an accounting record | 1 class |
| `OperatorBL` | prices: unpacks the dual return, calls the processor | 1 class, 11 subclasses |
| `Operator` | applies: accounting top-up and undo | 1 class, 4 methods, no overrides |
| `FullSolution` | writes resolved numbers to derived caches. Decides nothing | 1 new method |

## Verification

The existing suite is the gate, and it is already shaped for this. `assert_operator_contract`
checks purity, then every objective term against ground truth, then the oracles, then exact revert.
`objective_terms()` recomputes from scratch, so the per-term comparison is a true oracle rather than
a cache compared against itself. `stress.py --inject-delta` confirms the detector fires.

The per-term shape is what makes the rollout gateable. Each step moves one term, and the assertion
that fails names that term.

Four additions, all in step 0:

- **Two oracles are missing.** `all_problems()` checks `depot_route_starts` and `route.current_load`
  but nothing checks `vehicle.num_routes_overloaded` or `vehicle.num_customers`. Those back
  `vehicles_overloaded` and `vehicles_activated`. A corrupt counter makes `objective_terms()` and
  the predicted delta wrong together, so the per-term assertion passes and the corruption is
  invisible. Add both, and prove each fires by deliberate corruption, before any term moves.
- **A raw-record oracle.** Read each route's load, customer count, start depot, and vehicle before
  and after apply, and assert the record's transitions match. This checks the record independently
  of any term, so later steps only have to get the derivation right.
- **Composition coverage.** Compose the raw records for N moves, reconstruct once, and assert the
  result equals applying the N moves one at a time with reconstruction after each. There is implicit
  coverage today through `_SequentialCombineRoutes` and `cost_deltas_for_removing_empty_routes`;
  the merge rule itself has none.
- **New `ObjectiveTermDelta` fields must have no default.** `term_deltas()` in the harness builds
  the tuple with explicit keyword arguments, so a field with a default is silently skipped by every
  per-term assertion.

Step 0 changes no behavior, so its gate is stronger than the others: a bit-identical deterministic
run against the pre-change commit. Same seed, same trajectory, same objective, same `fingerprint`.

Run the full matrix, not the reduced default. A change to the accounting foundation earns it.

### When the accounting record is applied

**`FullSolution` owns one central call that applies an already-processed accounting record**,
propagating update handles down to its vehicles and routes. Nothing else writes a derived cache, and
this call resolves nothing — the processor did that.

Mutation and accounting are separate events, so `Move` carries **two independent state bits**:

| bit | means |
|---|---|
| `already_applied` | the structural mutation is in the solution |
| `accounting_applied` | the accounting record is in the caches |

A predictive operator sets both in one step. An operator that prices by mutating leaves
`(applied, not accounted)` when `evaluate()` returns, and the accounting is topped up later.

`Operator` drives both bits:

- **apply** — if the move is not applied, mutate and then apply the accounting. If it is applied but
  not accounted, apply the accounting only. If both, do nothing.
- **revert** — undo the accounting if it was applied, then undo the move if it was applied.

Today both apply paths return outright on `already_applied`, which is why the accounting has to be
topped up there rather than deeper down. The call sites are four methods on one class, and **no
subclass overrides any of them** across all 34 operators:

```
SimAnn_VRP_Operators.py:282   if move.already_applied or not move.is_actionable:   apply_for_acceptance
SimAnn_VRP_Operators.py:325   if move.already_applied:                             apply
SimAnn_VRP_Operators.py:336   if not move.already_applied:                         revert_and_reject
SimAnn_VRP_Operators.py:357   if not move.already_applied:                         revert
```

`Move` is a frozen dataclass whose only sanctioned mutation is `mark_applied()`. The second bit
needs a parallel `mark_accounting_applied()` — one named method, trivial to grep, matching the
reason the first one exists.

**The oracle rule that follows:** while a move is applied but not yet accounted, **accounting
oracles cannot run.** The derived caches are legitimately behind the structure. That window exists
only for `_evaluates_by_applying` operators, between their `evaluate()` and the next `apply()`.

Neither by-applying operator is otherwise a blocker. `PermuteChain` permutes within one route, so no
derived cache moves and its record is distance-only. `_SequentialCombineRoutes` is reference only
and prices by composing L3 aggregators, which makes it the composition test rather than a special
case. Neither reads `objective_terms()`.

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
