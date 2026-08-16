# Planning

What comes next for this solver, and why. Each entry states the problem, the measurement that
motivates it, and the gate that would justify starting it.

The point of writing these down is that most of them are **not** started, deliberately. Every entry
carries the evidence for its own priority, so the ordering is arguable rather than asserted.

| plan | status | one-line reason |
|---|---|---|
| [inverted-view-refactor](inverted-view-refactor.md) | deferred, gated | O(1) "where is customer j"; blocked on proving geometric guidance is worth it |
| [kd-tree-neighbors](kd-tree-neighbors.md) | deferred, not needed yet | neighbor table build is O(n^2); only matters above ~50k customers |
| [ruin-and-recreate](ruin-and-recreate.md) | ready to start | the real gap against modern VRP; primitives already landed |
| [operator-scoring](operator-scoring.md) | ready to start | an operator whose accepted moves are all uphill scores exactly zero |
| [end-depot-index](end-depot-index.md) | measured, small | the only operator whose cost grows with instance size |
| [warm-start](warm-start.md) | small, isolated | saved solutions cannot be loaded back |

## How results get accepted here

Two rules the project has stuck to, because both were learned the expensive way:

**A measurement beats an argument.** Several plausible optimizations in this repo were killed by
measuring them — the decomposed `CombineRoutes` was 8.5x slower than the predictive version, and the
annealing-schedule search found nothing above its own noise floor across 704 trials.

**Verify the detector before trusting a clean run.** `tools/stress.py --inject-delta` deliberately
corrupts a move's price and must be seen to fail before a zero-findings run means anything.
