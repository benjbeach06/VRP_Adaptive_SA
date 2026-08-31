# Design

Why the solver code is shaped the way it is. One folder per feature area.

A design doc records what was **decided** and why, including alternatives rejected. It is not a
description of the code -- if a reader could get it from the source in ten seconds, it does not
belong here.

**On defects.** A defect earns a mention only if it passes all three:

- **It is a DESIGN defect, not a code bug.** The design was wrong, not its implementation.
- **It reached a commit.** Anything fixed before the first commit never existed in the repo.
- **It blocked effective use.** A tuned constant does not qualify. A mechanism that could not work
  does.

Then write the DECISION it forced, not the incident.

The other homes do not overlap with this one:

| where | what |
|---|---|
| `design/` | why the code is shaped this way |
| [planning/](../planning/README.md) | planned features, and the gate for starting each |
| [RESULTS.md](../RESULTS.md) | every measurement, including the withdrawn ones |
| [METHODOLOGY.md](../METHODOLOGY.md) | how a measurement earns the right to be believed |
| [retros/README.md](../retros/README.md) | how the work went, and what we changed about working |

## Contents

| area | doc | covers |
|---|---|---|
| span reorder | [reorder_operators](span_reorder/reorder_operators.md) | the `_SpanReorderBase` seam, the family tree, and the exact short-span optimizer |
| | [farthest_insertion_ops](span_reorder/farthest_insertion_ops.md) | the three heuristic variants and how they differ |
| | [farthest_insertion_order](span_reorder/farthest_insertion_order.md) | the fixed-endpoint path helper, why farthest insertion, the measured O(n^2) |
| operator selection | [README](operator_selection/README.md) | the folder's own reading order |
| | [family_selection](operator_selection/family_selection.md) | the family tree, MAX aggregation, and descending it one level at a time |
| | [share_floors](operator_selection/share_floors.md) | the guaranteed minimum share per root family, and the projection that enforces it |
| | [exploitation_governance](operator_selection/exploitation_governance.md) | `exploit_only`, the cost-amortizing penalty factor, the `adj_weights` mirror |
| | [hierarchical_magnetism](operator_selection/hierarchical_magnetism.md) | pulling an unproposed operator toward its SIBLINGS rather than the flat roster |
| | [dynamic_penalty](operator_selection/dynamic_penalty.md) | score, the weight EMA, and the cost-ratio penalty -- plus the design defect that forced its current shape |
| schedule | [time_based_schedule](schedule/time_based_schedule.md) | one clock for cooling and plateau detection, in seconds by default and iterations as the determinism fallback |
| raw-delta accounting | [README](raw_delta_accounting/README.md) | the four layers, and the folder's reading order |
| | [raw_delta_record](raw_delta_accounting/raw_delta_record.md) | one map per field keyed by route, transition form, the composition rule, travel as one number |
| | [processor](raw_delta_accounting/processor.md) | the two outputs, the check behind the three activation terms, why the bases are read before the mutation |
| | [accounting_record](raw_delta_accounting/accounting_record.md) | the `AccountingRecord` fields, its derived `inverse`, and how the sink applies one |
| | [tracking_for_cached_accounting](raw_delta_accounting/tracking_for_cached_accounting.md) | the two bits that track a move's applied structure and accounting, and the one-time cache build |

## Target structure

One folder per **BL operator**, and inside it a folder per `Operator` class that uses it when there
is more than one. The current folders predate that rule and are migrated toward it as more of the
code gets covered, not restructured ahead of need.

## References

- [design/operator_selection/dynamic_penalty.md](operator_selection/dynamic_penalty.md) -- score, weight EMA, and cost-ratio penalty, plus the design defect that forced its current shape
- [planning/README.md](../planning/README.md) -- planned features and entry gates
- [retros/README.md](../retros/README.md) -- work narrative and changes to working methods
- [design/operator_selection/README.md](operator_selection/README.md) -- reading order for the operator selection folder
- [design/operator_selection/family_selection.md](operator_selection/family_selection.md) -- family tree, MAX aggregation, and descent strategy
- [design/span_reorder/farthest_insertion_order.md](span_reorder/farthest_insertion_order.md) -- fixed-endpoint path helper and O(n^2) analysis
- [design/operator_selection/share_floors.md](operator_selection/share_floors.md) -- minimum share guarantees and projection enforcement
- [design/span_reorder/reorder_operators.md](span_reorder/reorder_operators.md) -- span reorder base seam, family tree, and optimizer
- [design/operator_selection/exploitation_governance.md](operator_selection/exploitation_governance.md) -- exploit-only mode, cost amortization, and adjusted weights
- [METHODOLOGY.md](../METHODOLOGY.md) -- measurement criteria and verification standards
- [design/operator_selection/hierarchical_magnetism.md](operator_selection/hierarchical_magnetism.md) -- magnet pull toward siblings rather than flat roster
- [design/schedule/time_based_schedule.md](schedule/time_based_schedule.md) -- unified clock for cooling and plateau, seconds or iteration fallback
- [design/span_reorder/farthest_insertion_ops.md](span_reorder/farthest_insertion_ops.md) -- three heuristic insertion variants and their differences
- [RESULTS.md](../RESULTS.md) -- all measurements, including withdrawn results
- [design/raw_delta_accounting/accounting_record.md](raw_delta_accounting/accounting_record.md) -- the accounting record, its inverse, and the sink
- [design/raw_delta_accounting/processor.md](raw_delta_accounting/processor.md) -- the resolver from raw record to objective delta
- [design/raw_delta_accounting/raw_delta_record.md](raw_delta_accounting/raw_delta_record.md) -- the record the core model produces
- [design/raw_delta_accounting/README.md](raw_delta_accounting/README.md) -- the raw-delta accounting hub: four layers and reading order
- [design/raw_delta_accounting/tracking_for_cached_accounting.md](raw_delta_accounting/tracking_for_cached_accounting.md) -- the two application-tracking bits, and the one-time cache build

## Links to here

*(none yet)*
