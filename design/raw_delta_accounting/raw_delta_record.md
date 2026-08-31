# The raw delta record

`RawDeltaRecord` is what a mutation reports. It names what structurally changed, and nothing about
what that means for the objective.

## One map per field

The record holds four maps, each keyed by the route object:

| map | value |
|---|---|
| `load_changes` | `(initial, final)` load |
| `customer_deltas` | `(initial, final)` customer count |
| `start_depot_changes` | `(initial, final)` start depot |
| `vehicle_changes` | `(initial, final)` vehicle, `None` for an unassigned route |

A route is in a map only if it moved in that field. That membership is the whole test. A route
absent from all four maps changed nothing.

**Absent means unchanged, and the consumer reads the current value off the key.** The key is the
route object, so the base a step function needs is reachable through it. This holds because route
identity is stable across an apply then revert. For example, `split_at` refills the original route
object rather than building a fresh one.

Fields default to a shared immutable empty map, so a record for a mutation that moved nothing
allocates nothing.

## Start depot reports activity, not geometry

`start_depot_changes` records what `Route.used_start_depot` returns: the route's real start depot
while the route is active, and `VIRTUAL_DEPOT` while it is not. So a route that empties reports
`(real depot, VIRTUAL_DEPOT)` even though its geometric start depot never moved, and a route that
fills again reports the reverse. This is what lets the processor and the sink treat "a route left
the active set" and "a route changed which depot it starts at" as one transition.

## Transition form

Fields whose objective term is a step function carry `(initial, final)`, not a delta: load,
customer count, start depot, vehicle. A step function is nonlinear in its input, so resolving it
needs the value before the change, and the pair carries it.

Transition form gives one composition rule. To compose two records, chain each route's transitions
on the route key and drop the entry when initial equals final. A route created then disposed inside
a sequence composes to `(None, None)` and drops out. The composed record already holds the final
value of every field, so the processor needs no shadow state to reconstruct a sequence of moves.

## Travel distance is one number

Every other field is per route. Travel distance is a single delta on the record.

Link deltas do not count a moved chain's interior arcs. The interior cancels between the removal
half and the insertion half, because a moved chain carries its own arcs. That cancellation is what
makes a chain move O(1) in the chain length. The cost is that neither half is a route's real
distance change, so splitting travel per route would cost O(k) at pricing time, on the cheapest
pricing path in the solver.

So travel stays a bulk number, priced from link deltas. Per-route distance is
[route-distance-tracking](../../planning/core-refactors/route-distance-tracking.md), which accounts
it at mutation time instead.

## References

- [planning/core-refactors/route-distance-tracking.md](../../planning/core-refactors/route-distance-tracking.md) -- accounts per-route distance at mutation time, which is why travel stays a single number here

## Links to here

- [README.md](README.md) -- the folder hub; lists this doc first in reading order
- [design/README.md](../README.md) -- parent index to the design folder
- [accounting_record.md](accounting_record.md) -- reuses the activity-marker rule for the start-depot field
- [processor.md](processor.md) -- reads this record as its input
