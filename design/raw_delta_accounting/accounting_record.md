# The accounting record

The processor's second return is an `AccountingRecord`: resolved cache updates, ready to write. It
carries no thresholds and no derived state. Everything in it is a number the sink assigns or adds.

## The fields

| field | form |
|---|---|
| `vehicle_delta_routes_overloaded` | delta per vehicle |
| `vehicle_delta_active_routes` | delta per vehicle |
| `vehicle_delta_num_customers` | delta per vehicle |
| `route_loads` | `(initial, final)` per route |
| `start_depot_changes` | `(initial, final)` depot per route |

The three per-vehicle fields are signed deltas. The two per-route fields are transitions: they
carry the value before the change and the value after it.

`start_depot_changes` records what `Route.used_start_depot` returns, not the geometric start depot.
That is the real start depot while the route is active and `VIRTUAL_DEPOT` while it is not, so a
route that empties reports `(real depot, VIRTUAL_DEPOT)` and a route that fills again reports the
reverse. See [raw_delta_record.md](raw_delta_record.md).

## Inversion

`AccountingRecord.inverse` is a property computed from the record itself. Each per-vehicle delta
negates. Each transition swaps its two ends. Applying a record then applying its inverse is a
no-op.

There is no separate revert path. `apply_accounting` performs both directions, and reverting a
move is `sln.apply_accounting(record.inverse)`. `apply_accounting` returns nothing.

## Application

The sink adds each per-vehicle delta to its counter, assigns each route's load from its pair, and
moves each route between the per-depot route sets. It evaluates no threshold; the processor
resolved all of those.

A start-depot change is applied raw: remove the route from the initial depot's route set, add it
to the final one, skip `VIRTUAL_DEPOT` on each end. A record that names a route the initial depot
does not hold raises `KeyError`; a silent miss would leave the per-depot route sets permanently
wrong.

Route order within a depot's route set is not preserved across apply then revert. The route set is
swap-with-last, so a remove followed by a re-add lands at the end, and the record carries no
removal position to restore it. The route set reorders on every add and remove by design, and a
reordered set is a different random trajectory, not a wrong answer.

`VIRTUAL_DEPOT` is a module-level singleton with one construction site, so the processor and the
sink test for it by identity. It defines no hash, so a stray instance used as a dict key raises
rather than corrupting a count.

## References

- [raw_delta_record.md](raw_delta_record.md) -- the source-side record, and the activity-marker rule this field shares

## Links to here

- [README.md](README.md) -- the folder hub; this doc is the record and the sink, third in reading order
- [design/README.md](../README.md) -- parent index to the design folder
- [processor.md](processor.md) -- returns this record
