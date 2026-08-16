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

## Evidence: does geometric guidance help?

This is the measurement the inverted-view refactor is gated on, so it is recorded here rather than
buried in a commit message.

**Acceptance rates. Decisive.** Each guided operator against its own blind twin — same move type,
same 60 s run at 500 customers / capacity 400, so both saw identical conditions:

| move type | blind | guided |
|---|---|---|
| relocate | `RandomCustomerReassignment` 0.00%, **0** accepts, 0 improving | `ReassignChainNextToNeighbor` 0.30%, **654** accepts, 385 improving |
| cross-exchange | `RandomChainSwap` 0.01%, **1** accept | `SwapChainsWithNeighbor` 0.46%, **1703** accepts, 900 improving |

The adaptive weighting reached the same conclusion independently: `SwapChainsWithNeighbor` drew
368,245 proposals, more than any other operator in the roster.

**Final objective. NOT established.** Paired 60 s runs, five seeds, roster with the two operators
against the roster without them:

| | value |
|---|---|
| mean improvement | +15.56 |
| standard deviation | 16.59 |
| standard error | 7.42 |
| wins | 4 of 5 |

That is 2.1 standard errors, and the effect is smaller than the spread within a single condition.
Suggestive, not proven.

The two results are not in conflict. The operators demonstrably produce accepted, improving moves
at roughly 30-1700x the rate of their blind twins. Whether that converts into a better objective
inside a 60 s budget is a separate question, and this solver converts compute into objective slowly:
on the tuning harness, **4x the time bought 0.46%**. A test that can resolve a 15-unit difference
needs either many more runs or iteration-count termination, which is item 4 of
`TODO(debug-tooling)` in the solver.

## How results get accepted here

Two rules the project has stuck to, because both were learned the expensive way:

**A measurement beats an argument.** Several plausible optimizations in this repo were killed by
measuring them — the decomposed `CombineRoutes` was 8.5x slower than the predictive version, and the
annealing-schedule search found nothing above its own noise floor across 704 trials.

**Verify the detector before trusting a clean run.** `tools/stress.py --inject-delta` deliberately
corrupts a move's price and must be seen to fail before a zero-findings run means anything.
