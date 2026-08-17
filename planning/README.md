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
| [module-structure](module-structure.md) | deferred by timeboxing | 4,662-line core model; a mechanical `self` -> typed-parameter split into a static evaluator |

## New: re-tune operator selection

`explore_reward` floored an accepted move's score at a positive value, which removed the sign that
`OperatorStats.record_accept` was using to decide whether a move improved. The whole
operator-selection search ran after that and is void. This is now the highest-priority item and has
no planning file yet, because the work is simply to rerun the pipeline against the fixed counter.

The defaults meanwhile are the hand-chosen originals, which is where they started.

## Evidence

The measurements these plans are gated on -- geometric guidance, operator ablation, and the
withdrawn tuning result -- are in [METHODOLOGY.md](../METHODOLOGY.md), together with the rules used
to accept them. They are kept there rather than here so that a reader meets the evidence before the
roadmap that cites it.

The short version, for ordering purposes:

- **Ablation ranks operators; acceptance rate does not.** The roster's most valuable operator
  accepts 1.09% of its proposals.
- **Geometric guidance raises acceptance from 0.00% to 0.30%, but its objective effect sits at
  about 2 sigma.** That is why `inverted-view-refactor` is gated rather than scheduled.
