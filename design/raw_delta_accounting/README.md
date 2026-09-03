# Raw-delta accounting

How a mutation's effect on the objective is computed, and how the derived caches are kept true to
the structure.

The core model reports raw structural transitions. One processor turns those into an objective
delta and a set of cache updates. One sink writes the caches. There is a single derivation of every
objective term, so the incremental state cannot disagree with itself.

## Four layers

| layer | file | job |
|---|---|---|
| core model | `SimAnn_VRP_Core_Model.py` | reports raw. The minimum data -- travel, load and customer-count changes, start depot, vehicle -- needed to reconstruct the objective change and the cached values. |
| processor | `SimAnn_VRP_Accounting.py` | resolves. Raw record plus current state, to an `ObjectiveTermDelta` and an `AccountingRecord`. Reads state, writes nothing. |
| `Operator` | `SimAnn_VRP_Operators.py` | applies. Drives two application-tracking bits in the `Move` and calls the sink. |
| `FullSolution` | `SimAnn_VRP_Core_Model.py` | is the sink. Writes derived caches from resolved numbers. |

The core model never resolves a step function. It reads an accessor only to tell whether a field
moved, and reports the raw change if it did. Every threshold and zero-crossing is the processor's.

The processor is its own entity. `FullSolution` holds the state the processor reads, so the two could
be one class, but then step-function evaluation would sit inside the core model, next to the
mutators. The split keeps the core model free of it. `RawDeltaRecord` and `ObjectiveTermDelta` live
in the core model because the core model produces them; the processor imports from the core model,
and nothing in the core model imports the processor.

## Docs

| doc | what it covers |
|---|---|
| [raw_delta_record.md](raw_delta_record.md) | The record the core model produces: one map per field keyed by route; transition form and where it does not apply; the two composition rules and what decides which a field uses; why a cross-route travel share has to be stated by its caller. |
| [processor.md](processor.md) | `AccountingProcessor.process`: the two outputs, the check behind the three activation terms, and why the bases it reads are read before the mutation. |
| [accounting_record.md](accounting_record.md) | The `AccountingRecord` fields, its derived `inverse`, and how the sink applies one. |
| [tracking_for_cached_accounting.md](tracking_for_cached_accounting.md) | The two bits that track whether a move's structure and accounting are applied, and the one-time build of every cache from a finished structure. |

**Reading order.** Record, then processor, then accounting record, then tracking. Producer,
resolver, the resolved record, keeping the caches right around it.

## Related work

Per-route and per-vehicle distance run through this pipeline like every other cache: the core model
reports a travel delta per route, the processor aggregates it per vehicle, and the sink writes both.
`Route.total_distance` and `Vehicle.get_total_distance` are the recompute twins.

End-depot usage as an objective term is not built. It is in
[planning/core-refactors/route-distance-tracking.md](../../planning/core-refactors/route-distance-tracking.md),
which this pipeline makes cheap to add.

## How this came to be

The plan, and the ways the built pipeline departed from it, are in
[planning/implemented/raw-delta-accounting.md](../../planning/implemented/raw-delta-accounting.md).

## References

- [raw_delta_record.md](raw_delta_record.md) -- the record the core model produces, covered first in reading order
- [processor.md](processor.md) -- the resolver that turns a record into an objective delta and cache updates
- [accounting_record.md](accounting_record.md) -- the record fields, its inverse, and how the sink applies one
- [tracking_for_cached_accounting.md](tracking_for_cached_accounting.md) -- the two application-tracking bits, and the one-time cache build
- [planning/core-refactors/route-distance-tracking.md](../../planning/core-refactors/route-distance-tracking.md) -- end-depot usage as an objective term, the one part of that plan still unbuilt
- [planning/implemented/raw-delta-accounting.md](../../planning/implemented/raw-delta-accounting.md) -- the plan, and how the built pipeline departed from it

## Links to here

- [design/README.md](../README.md) -- parent index to the design folder
- [retros/2026-08-29_raw_delta_accounting_implementation.md](../../retros/2026-08-29_raw_delta_accounting_implementation.md) -- the retro covering the build and its finalization
- [design/span_reorder/farthest_insertion_ops.md](../span_reorder/farthest_insertion_ops.md) -- cites the sink-written route distance this pipeline maintains, which its route-weighted draw reads
