# The raw delta record

`RawDeltaRecord` is what a mutation reports. It names what structurally changed, and nothing about
what that means for the objective.

## One map per field

The record holds five maps, each keyed by the route object:

| map | value |
|---|---|
| `travel_changes` | travel delta |
| `load_changes` | `(initial, final)` load |
| `customer_deltas` | `(initial, final)` customer count |
| `start_depot_changes` | `(initial, final)` start depot |
| `vehicle_changes` | `(initial, final)` vehicle, `None` for an unassigned route |

A route is in a map only if it moved in that field. That membership is the whole test. A route
absent from all five maps changed nothing.

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

## Transition form, and where it does not apply

Fields whose objective term is a step function carry `(initial, final)`, not a delta: load,
customer count, start depot, vehicle. A step function is nonlinear in its input, so resolving it
needs the value before the change, and the pair carries it.

Travel is the exception. Distance has no threshold of its own, so `travel_changes` is a plain delta
per route. The sink adds it and the inverse negates it, which is the treatment the per-vehicle
counters get one level down.

The solution-level figure the objective wants is **derived** from that map, as the sum of its
values. A stored total beside a per-route map would be two derivations of one quantity, which is
the structure this pipeline exists to remove.

## Composition, and the rule that decides its form

Two records compose when the second was measured against the state the first left. Delta maps add
and a zero entry drops. Transition maps chain on the route key and the entry drops when the two
ends match. A route created then disposed inside a sequence composes to `(None, None)` and drops
out. The composed record holds the final value of every field, so the processor needs no shadow
state to reconstruct a sequence of moves.

Transition maps chain in one of two ways, and **which one a field uses follows from who writes its
base**:

| base | fields | how two records chain |
|---|---|---|
| written by the sink | load | **by delta**: keep the first record's initial, and add the second record's own span to the first record's final |
| read live from the structure | customer count, start depot, vehicle | **by endpoint**: keep the first initial and the second final, asserting the two meet |

A sink-written base does not move when the structure does. An operator that prices two sub-steps
against one route therefore reads the **same** pre-move base both times, so the second record's
`final` already discards the first step. Composing by delta is correct whether the second base was
stale or live: when it was live the two forms coincide. This is why the endpoint gap assertion is
switched off for load and on for the other three, where a mismatch is a genuine composition bug.

Nothing in today's roster takes two sub-steps on one route, so the endpoint form was latent rather
than wrong. Ruin-and-recreate reaches it on its first same-route double removal. See
[ruin-and-recreate](../../planning/search-methods/ruin-and-recreate.md).

## Travel is per route, and the callers have to say whose it is

Link deltas do not count a moved chain's interior arcs. The interior cancels between the removal
half and the insertion half, because a moved chain carries its own arcs. That cancellation is what
makes a chain move O(1) in the chain length.

The consequence is that on a **cross-route** move neither half is a route's real distance change.
The source loses the moved chain's interior and the destination gains it, and the two link deltas
are only jointly correct. So a cross-route aggregator computes the interior once and hands each
route its own share; `Route.path_distance` and `Route.visits_distance` are the only places that
walk a sub-chain, and only three callers need one. Measured at 0.70 arcs per proposal, so the seam
exists to be swapped for a cached-arc or cumsum form later, not because the loop is expensive.

An intra-route move needs none of this: one route moved, one entry.

Getting a share wrong is invisible in the total, because misattributed shares still sum correctly.
That is why the record oracle grades each route's claimed share rather than only the solution
figure.

## References

- [planning/search-methods/ruin-and-recreate.md](../../planning/search-methods/ruin-and-recreate.md) -- the first planned search method that takes two sub-steps on one route, which is what makes delta composition load-bearing rather than latent

## Links to here

- [README.md](README.md) -- the folder hub; lists this doc first in reading order
- [design/README.md](../README.md) -- parent index to the design folder
- [accounting_record.md](accounting_record.md) -- reuses the activity-marker rule for the start-depot field
- [processor.md](processor.md) -- reads this record as its input
