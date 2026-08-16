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

## Evidence: which operators actually matter

One-factor-at-a-time ablation, 1641 runs over 21 seed-rounds, sizes 50 / 500 / 5000 at capacity
400. Harness `tools/ablate_operators.py`, full table `tools/ablation_report.txt`. Deltas are paired
on seed, so every variant solved the same instance from the same construction. Positive means the
variant is worse, so for `drop:X` a positive delta means X earns its place.

75 comparisons, so the bar is |sigma| >= 3. Five clear it, against 0.2 expected by chance:

| finding | size | delta | sigma |
|---|---|---|---|
| **drop RandomCustomerChainReversal** | 5000 | +157.32 (1.70%) | +18.7 |
| drop RandomCustomerChainReversal | 500 | +45.20 (2.16%) | +3.6 |
| drop ReverseClosestPairTogether | 5000 | +64.60 (0.70%) | +6.9 |
| NEIGHBOR_ROUTE_DRAWS 8 -> 16 | 5000 | −51.24 (0.55%) | −3.7 |
| NEIGHBOR_ROUTE_DRAWS 8 -> 4 | 5000 | +24.98 (0.27%) | +3.1 |

**`RandomCustomerChainReversal` is the backbone, and acceptance rate completely hid it.** That
operator shows 1.09% acceptance and 0.95s of a 60s run -- it reads as negligible in the per-operator
stats. Removing it is the largest effect in the whole study. Cheap, high-volume, low-acceptance
work is invisible to the metric the roster had been ranked by.

**The draws result is monotonic and mechanistic.** 4 -> 8 -> 16 improves at n=5000 and shows nothing
at n=500. It should: n=5000 at capacity 400 has ~69 routes, so a random draw rarely lands on one
holding a near neighbor, while n=500 has ~7 and 8 draws almost always succeeds. The principled form
is to scale draws with route count rather than fix a constant -- untested, since only 4/8/16 were
tried.

**Nothing at all resolves at n=50.** Largest effect 1.6 sigma. At that size operators substitute
for each other freely, so ablation cannot see them.

**The neighbor-guided operators are NOT yet proven by objective.** `ReassignChainNextToNeighbor` is
+17.51 (1.4 sigma) at n=500 and +16.92 (1.8 sigma) at n=5000 -- right sign twice, under the bar
both times. `SwapChainsWithNeighbor` flips sign between sizes. Note +17.51 matches the +15.56 +/-
7.42 from the independent paired A/B almost exactly: two measurements agreeing on a real-but-small
effect that neither can resolve. Their acceptance-rate advantage is large and certain; its
conversion into final objective is not.

**No k setting resolves anywhere**, and `drop:CustomerBestOfkSwapInRandomRoute` is negative at all
three sizes (−0.44, −3.70, −6.65). Removing the operator that consumes 44% of solver time may
actually help. Same sign three times is suggestive, not significant -- this deserves a targeted
study with real power, since it is the most expensive thing in the roster.

## How results get accepted here

Two rules the project has stuck to, because both were learned the expensive way:

**A measurement beats an argument.** Several plausible optimizations in this repo were killed by
measuring them — the decomposed `CombineRoutes` was 8.5x slower than the predictive version, and the
annealing-schedule search found nothing above its own noise floor across 704 trials.

**Verify the detector before trusting a clean run.** `tools/stress.py --inject-delta` deliberately
corrupts a move's price and must be seen to fail before a zero-findings run means anything.
