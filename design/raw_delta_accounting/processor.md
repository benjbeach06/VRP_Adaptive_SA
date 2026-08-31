# The processor

`AccountingProcessor.process` takes a `RawDeltaRecord` and the current `FullSolution`, and returns
two things: an `ObjectiveTermDelta` and an `AccountingRecord`. It is static and stateless. It reads
the solution's current aggregate state and mutates nothing.

It reads current state rather than carrying shadow state across a sequence of moves. A composed
record already holds the final value of each transition, so one reconstruction at the end is
enough.

## Building the transitions

One pass covers every route the record names in a load, customer-count, or vehicle map. For each,
it builds those three transitions: from the record where the record speaks, and from the live route
where it stays silent. Start-depot changes are a separate pass over the start-depot map. Nothing
else is consulted about what changed.

## The two outputs

The inputs named below are the raw record's four maps -- route load changes, route customer-count
changes, route start-depot changes, route vehicle reassignments -- plus the solution's live
counters. See [raw_delta_record.md](raw_delta_record.md) for the record, and
[accounting_record.md](accounting_record.md) for the record the sink applies.

**The objective delta is the change in each objective term.** Every entry is a delta.

| term | inputs | result |
|---|---|---|
| travel distance | the record's travel delta | passed through unchanged |
| total route overload | route load changes; route vehicle reassignments; vehicle capacity | the change in load-above-capacity, summed over affected routes |
| depots activated | route start-depot changes; each affected depot's live start count | how many depots changed to or from zero routes |
| vehicles activated | route customer-count changes; route vehicle reassignments; each affected vehicle's live customer count | how many vehicles changed to or from zero customers |
| vehicles overloaded | route load changes; route vehicle reassignments; each affected vehicle's live overloaded-route count | how many vehicles changed to or from zero overloaded routes |

**The accounting record is how the processor hands its cache updates to the sink.** This table is
the derivation; see [accounting_record.md](accounting_record.md) for what each field is and how it
is applied.

| field | inputs | result |
|---|---|---|
| overloaded routes, per vehicle | route load changes; route vehicle reassignments; vehicle capacity | +1 or -1 per route whose over-capacity state flipped; a reassigned route moves its contribution from the old vehicle to the new |
| routes with customers, per vehicle | route customer-count changes; route vehicle reassignments | +1 or -1 per route that crossed zero customers; a reassigned route moves its contribution from the old vehicle to the new |
| customers, per vehicle | route customer-count changes; route vehicle reassignments | the route's customer-count change on its vehicle; a reassigned route moves its whole count from the old vehicle to the new |
| route load | route load changes | passed through |
| start depot | route start-depot changes | passed through |

The three per-vehicle deltas do double duty: the processor also reads each against the vehicle's
live counter to decide the matching objective term, and the sink then applies the same delta.

## The activation check

Three of the objective terms ask one question of a count: did it change to or from zero. A depot is
active when at least one route starts there. A vehicle is active when it has at least one customer,
and overloaded when at least one of its routes is. The processor runs the same to-or-from-zero
check for all three.

Route overload is different. It is the amount of load above capacity, if any. That is route-local,
so it needs no live base, and it is a magnitude rather than a threshold crossing.

The per-vehicle and per-depot changes are aggregated first. A route that keeps its vehicle
contributes a difference; a route that changes vehicle subtracts from the old and adds to the new.
Start-depot aggregation skips the virtual depot on both ends. Each aggregate then meets the live
counter to decide whether the threshold was crossed.

## Bases are read before the mutation

Each base is read off the live solution, its vehicles, and its routes, and each must hold the value
from before the mutation.

An operator that prices by mutating has already changed the structure by the time `process` runs. A
cache the mutator maintained would hold the after-value, and the processor would count the change
twice. So each route's current load and each vehicle's customer count are carried in the
`AccountingRecord` and written only by the sink, next to the counters that have thresholds of their
own.

A route's own customer count is exempt. It is the route's path length, computed from the structure
rather than cached, so it never disagrees with the record.

## References

- [raw_delta_record.md](raw_delta_record.md) -- the record this reads as input
- [accounting_record.md](accounting_record.md) -- the second return, defined there

## Links to here

- [README.md](README.md) -- the folder hub; this doc is the resolver, second in reading order
- [design/README.md](../README.md) -- parent index to the design folder
