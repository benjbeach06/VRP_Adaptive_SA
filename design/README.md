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

## Target structure

One folder per **BL operator**, and inside it a folder per `Operator` class that uses it when there
is more than one. The current folders predate that rule and are migrated toward it as more of the
code gets covered, not restructured ahead of need.
