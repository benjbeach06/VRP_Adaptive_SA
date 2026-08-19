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

The other three homes do not overlap with this one:

| where | what |
|---|---|
| `design/` | why the code is shaped this way |
| [planning/](../planning/README.md) | planned features, and the gate for starting each |
| [RESULTS.md](../RESULTS.md) | every measurement, including the withdrawn ones |
| [METHODOLOGY.md](../METHODOLOGY.md) | how a measurement earns the right to be believed |

## Contents

| area | doc | covers |
|---|---|---|
| farthest distance | [farthest_insertion_order](furthest_distance/farthest_insertion_order.md) | the fixed-endpoint path helper, why farthest insertion, the measured O(n^2) |
| | [reorder_operators](furthest_distance/reorder_operators.md) | the three span-rebuild operators over `PermuteChain` |
| operator selection | [exploitation_governance](operator_selection/exploitation_governance.md) | `exploit_only`, the cost-amortizing penalty factor, the `adj_weights` mirror |

## Target structure

One folder per **BL operator**, and inside it a folder per `Operator` class that uses it when there
is more than one. The current folders predate that rule and are migrated toward it as more of the
code gets covered, not restructured ahead of need.
