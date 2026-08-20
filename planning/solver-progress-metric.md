# A solver progress metric

**Status: not started. Wanted by at least four other plans, and none of them can proceed cleanly
without it.**

## The problem

The solver knows a lot about where it is in a run and exposes none of it as one number. There is
`elapsed_time` against `max_time`, `curr_plateau_size`, `num_plateau_reheats`, and the objective
trajectory -- but no normalized "how converged is this run" that an operator or the selector can
read and act on.

Every consumer below currently has to either guess, or behave the same way throughout a run when it
should not.

## Who wants it

**Brute-force subpath seeding.** The exact span optimizer seeds its branch-and-bound bound with the
better of the incumbent ordering and a farthest-insertion pass. That is right early, when orderings
are poor and a tighter bound pays for itself.

**It inverts late.** Once the solution is good, pruning against the incumbent is already aggressive,
so the O(K^2) seed can cost more than the search it accelerates -- and can return a worse bound than
the incumbent it was meant to improve. The seed should be gated on progress and is not, because
there is nothing to gate on.

**[budget-gated-selection](budget-gated-selection.md)** needs to know how much budget remains
relative to what an operator costs, to admit expensive operators only when they are affordable.

**[operator-selection](operator-selection.md)** notes that repeat
proposals concentrate in a converged, quiet solution. A progress metric is how an operator would
know it is in that regime.

- **[operator-selection](operator-selection.md)** -- to trigger a low-temperature penalty on
  fully-random operators. Raw temperature is instance-scaled, so the trigger needs a normalized
  progress signal, not a constant.

## What it has to be

Normalized, cheap to read, and meaningful across instance sizes and budgets. Candidate inputs, none
chosen:

- fraction of budget elapsed -- simple, but says nothing about whether the search is still moving
- recent improvement rate -- closer to what consumers actually mean by "converged"
- plateau depth and reheat count -- already tracked, already normalized against `max_plateau_size`
- objective delta over the last N segments against the delta over the first N

The last two are the most promising, because they measure the SEARCH rather than the clock. A run
that plateaus at 10% of budget is converged; one still descending at 90% is not.

## Gate

None on correctness. It becomes worth building when a second consumer needs it -- which has now
happened, so the gate is met. It is deliberately not built yet only because the consumers work
without it, more crudely.

Design it once and share it. Three consumers each inventing their own progress heuristic is the
outcome to avoid.
