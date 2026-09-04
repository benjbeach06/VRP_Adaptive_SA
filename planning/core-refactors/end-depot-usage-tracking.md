# End-depot usage tracking

**Status: not started.** This is deferred step 4 of
[raw-delta-accounting](../implemented/raw-delta-accounting.md), carried forward on its own.

## The problem

`SwapRouteTailsAtSharedDepot` needs the routes that END at a given depot. It scans every route in
the solution to find them.

Its twin `SwapRouteHeadsAtSharedDepot` needs the routes that START at a depot, and reads
`depot_route_starts`, an O(1) index. The two operators are the same shape. Only one of them is
cheap.

That scan is the only cost in the roster that grows with instance size. The measurement is in
[end-depot-index](end-depot-index.md).

## Why there is no index today

Start-depot usage has a consumer besides the index: `depots_used()` counts the depots that at least
one active route starts at, and that is an objective term. The index is maintained because the
objective needs it anyway.

End-depot usage has no such consumer. So an end index used to be pure carrying cost. It would need
a hand-written update beside every mutator that moves an end depot, and that per-mutation
duplication is exactly what raw-delta accounting removed.

## What changed

The accounting pipeline now carries start-depot transitions as a field. End depots can take the
same path:

- the raw record gains `end_depot_changes`, one `(initial, final)` entry per route that moved;
- the processor passes it through, the way it passes `start_depot_changes` through;
- `apply_accounting` writes `depot_route_ends`, beside `depot_route_starts`.

No mutator maintains the index. One sink writes it, and the existing oracle convention grades it
against a fresh walk.

## The work

Three operators change an end depot, plus the route creation path. Each has to report the change
rather than just perform it. That is the whole of it; the machinery to resolve and apply the report
already exists.

**One subtlety, and it is the reason this is not a copy of the start-depot field.** A route's end
depot is the next route's start depot. Changing one end depot moves two entries, and removing a
route hands its start depot to its successor. So a single mutation can write to both indices, and
the report has to say so.

## Gate

Instance sizes where the scan costs enough to matter. [end-depot-index](end-depot-index.md) holds
the numbers and the threshold.

Nothing else is blocked on this. It is a speed change to one operator, not a capability.

## References

- [end-depot-index.md](end-depot-index.md) -- holds the measurement that motivates this: the scan is the only cost in the roster that grows with instance size
- [planning/implemented/raw-delta-accounting.md](../implemented/raw-delta-accounting.md) -- the pipeline this is deferred step 4 of; its start-depot field is the shape the end-depot field copies

## Links to here

- [planning/README.md](../README.md) -- the roadmap that lists this plan among the core refactors
- [retros/2026-09-04_vehicle_duration_objective.md](../../retros/2026-09-04_vehicle_duration_objective.md) -- the session that split this plan out
