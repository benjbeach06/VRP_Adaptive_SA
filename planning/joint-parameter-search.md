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

## The measurement problem comes first

**Do not run a wider search before fixing the noise floor.** Widening the space makes the existing
problem worse, and the existing problem is variance, not trial count.

The 149-trial search had a per-trial standard deviation of **0.0062** — 0.62% — with each trial
already averaging four 60-second runs. That is the floor a real effect has to clear, and it comes
mostly from **wall-clock termination**: a fixed seed does not fix the iteration count, so two runs of
"the same" configuration do different amounts of work.

The arithmetic is unforgiving. Detecting a 1% effect against 0.62% per-trial noise needs many trials
per configuration; adding dimensions multiplies the configurations needed. Spending the budget on
more trials at the current noise level buys very little.

**Iteration-count termination is the prerequisite.** It is already listed under Known Limitations in
[RESULTS.md](../RESULTS.md). Making runs terminate on iterations rather than seconds removes
the dominant variance source, which makes every trial cheaper in the only currency that matters here.
That is a smaller job than a wide search and it makes the wide search worth running.

Order: fix termination, re-measure the noise floor, *then* decide how many dimensions the budget can
actually support.

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

Iteration-count termination, and a re-measured noise floor. Without those this is a more expensive
way to reach the same flat answer twice.

Worth saying plainly: the prior is that this finds nothing. Two searches over different parameter
sets both landed on the hand-chosen values, which is evidence the solver is genuinely insensitive
here. The interaction argument is real but it is a reason to keep the question open, not a reason to
expect a different result.
