# Joint parameter search

**Status: not started. Deliberately parked after two flat searches — see the measurement note
below, which is the reason this is not simply "run a bigger search".**

## The idea

Both searches so far moved a small number of knobs and held the rest fixed:

| search | searched | held fixed |
|---|---|---|
| annealing schedule, 704 trials | temperature and cooling parameters | operator selection |
| operator selection, 149 trials | `one_minus_K`, `segment_length`, `explore_reward` | `initial_temp_factor`, `cooling_rate`, `plateau_reheat_exponent` |

Both came back flat, and hand defaults won both. But **a flat subspace does not imply a flat
space.** If the schedule and the selection parameters interact — and there is an obvious mechanism,
since `segment_length` sets both the weight-update rate and the plateau-reheat threshold, and
reheating is a schedule behavior — then neither search could have seen it. Each held constant the
thing the other was varying.

So the open question is whether several tweaks *together* beat any of them alone.

## The measurement problem comes first, and the obvious fix is a trap

**Do not run a wider search before fixing the noise floor.** Widening the space makes the existing
problem worse, and the existing problem is variance, not trial count.

The 149-trial search had a per-trial standard deviation of **0.0062** — 0.62% — with each trial
already averaging four 60-second runs. That is the floor a real effect has to clear, and it comes
mostly from **wall-clock termination**: a fixed seed does not fix the iteration count, so two runs of
"the same" configuration do different amounts of work.

The arithmetic is unforgiving. Detecting a 1% effect against 0.62% per-trial noise needs many trials
per configuration; adding dimensions multiplies the configurations needed. Spending the budget on
more trials at the current noise level buys very little.

**Do NOT reach for iteration-count termination here.** It looks like the fix and it is worse than
the problem.

Under a fixed iteration budget, **an expensive operator is free**. A parameter set that shifts
weight toward expensive operators does more work per iteration, so it wins the test -- and loses in
production, where those iterations cost wall clock. The selection parameters are exactly the ones
that control operator cost, so the bias lands squarely on the thing being tuned.

That is BIAS, not noise. A quieter objective measuring the wrong quantity is worse than a noisy one
measuring the right quantity: it returns a confident wrong answer instead of an uncertain right one.

**The test must measure what a user gets: solution quality at a fixed TIME limit.** That fixes the
termination rule and leaves only one way to lower the noise floor -- more runs per configuration.

(Iteration-count termination would also not deliver reproducibility on its own. Operator weighting
is timing-based, so CPU load changes which operators are selected even at a fixed iteration count.
Removing that too means `set_deterministic_weighting`, which forces mean cost to 1 and stops
measuring the shipped solver. See Known Limitations in [RESULTS.md](../../RESULTS.md).)

So the order is: decide how many runs per configuration the noise floor demands, price that against
the number of dimensions, and only then decide whether the search is affordable. There is no
cleverer termination rule waiting to make it cheap.

## Three ways to make it affordable

The budget is runs-per-configuration, and it is bounded by wall clock. Three levers move that bound
without waiting longer. They are independent and they multiply.

**1. Raise throughput.** Faster iterations mean shorter runs measure the same amount of search.
Profiling found few easy wins: the time is spread across `[self]` attribute lookups in the operators'
own frames rather than concentrated anywhere. That points at structural work --
[module-structure](../core-refactors/module-structure.md) turns `self` into a typed parameter, and
[inverted-view-refactor](../core-refactors/inverted-view-refactor.md) removes the lookup chain that feeds the hottest
delta path.

**2. Parallelize -- primarily on remote HPC or cloud, not locally.** Runs are independent: different
seeds, different configurations, no shared state. That is the standard vector for this shape of
workload, and it is where "more compute in the same wall clock" actually scales. A local machine
buys a small constant factor; a cluster buys the order of magnitude the power calculation needs.

**Local parallelism only via MPI-style independent processes, never threads.** The solve is CPU-bound
Python, so the GIL makes thread parallelism worthless -- threads would serialize the work and, worse,
serialize the timings that operator weighting reads. Independent processes, one per core, are the
only local form that works.

**Either way, one measurement risk, and it is the same one that rules out iteration-gating.**
Operator weighting is timing-based. Solves that contend for a core inflate `mean_valid_call_time`, which
changes which operators get selected, so a contended run measures a slightly different solver.
Pin one solve per physical core, and check that a parallel trial reproduces a solo trial's operator
mix before trusting a parallel search.

**3. Make the solver converge faster.** Better operators, and ablate the ones that earn nothing.
Steeper descent means plateaus arrive sooner, so a shorter run still exercises the reheat behavior
that the schedule parameters exist to control. This one is different in kind: it does not just buy
more runs, it makes each run need less time to measure the same thing.
[heuristic-survey](../search-methods/heuristic-survey.md) is the cheap first step.

## If it does get run

- **Include `segment_length` × schedule interaction explicitly.** That is the one mechanism with a
  concrete story, since `max_plateau_size = PLATEAU_ITERATIONS / segment_length` couples selection
  sampling to reheat timing.
- **Carry the unresolved trace.** The 15 best trials of the last search all had `segment_length`
  between 18 and 79 against a default of 100. Confounded by the sampler concentrating, so it is a
  hypothesis rather than a finding — but it is the one region worth sampling densely.
- **Keep the stopping rule stated in advance.** Report bucket means and the expected minimum under
  pure noise, not the argmax. The last search produced an apparent 1.11% winner that was *less*
  extreme than noise predicts for 149 draws; without that comparison it would have looked adoptable.
- **Run `tools/preflight.py` first**, as always.

## Gate

A noise floor low enough to resolve the effect being looked for, which means budget for many runs
per configuration. Without that this is a more expensive way to reach the same flat answer twice.

Worth saying plainly: the prior is that this finds nothing. Two searches over different parameter
sets both landed on the hand-chosen values, which is evidence the solver is genuinely insensitive
here. The interaction argument is real but it is a reason to keep the question open, not a reason to
expect a different result.

## References

- [planning/search-methods/heuristic-survey.md](../search-methods/heuristic-survey.md)
- [planning/core-refactors/inverted-view-refactor.md](../core-refactors/inverted-view-refactor.md)
- [planning/core-refactors/module-structure.md](../core-refactors/module-structure.md)
- [RESULTS.md](../../RESULTS.md)

## Links to here

- [planning/README.md](../README.md)
- [planning/operator-selection/family-generation.md](../operator-selection/family-generation.md)
- [experiment_logs/tuning/2026-08-26_time_robust.md](../../experiment_logs/tuning/2026-08-26_time_robust.md) -- empirical parameter-importance measurement consistent with this doc's reheat-equilibrium argument
