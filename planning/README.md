# Planning

Planned features for this solver. Each entry states the problem, the measurement that motivates it,
and **the gate that would justify starting it**.

Most are not started yet. The gate is the useful part: it says what has to be true before the work
is worth doing, so the ordering is arguable from evidence rather than asserted.

| plan | status | one-line reason |
|---|---|---|
| [inverted-view-refactor](inverted-view-refactor.md) | deferred, gate NOT met | O(1) "where is customer j"; needs ablation evidence for guidance, which currently sits at 2 sigma |
| [kd-tree-neighbors](kd-tree-neighbors.md) | deferred, not needed yet | neighbor table build is O(n^2); only matters above ~50k customers |
| [ruin-and-recreate](ruin-and-recreate.md) | ready to start | the real gap against modern VRP; primitives already landed |
| [operator-scoring](operator-scoring.md) | implemented, unproven | the floor selects CHEAP explorers over expensive ones; effect is below the current noise floor |
| [end-depot-index](end-depot-index.md) | measured, small | the only operator whose cost grows with instance size |
| [warm-start](warm-start.md) | small, isolated | saved solutions cannot be loaded back |
| [module-structure](module-structure.md) | deferred by timeboxing | 4,662-line core model; a mechanical `self` -> typed-parameter split into a static evaluator |
| [route-distance-tracking](route-distance-tracking.md) | small, self-verifying | no route knows its own length; maintain it like load, with an oracle twin |
| [vehicle-time-limits](vehicle-time-limits.md) | blocked on the above | travel + service + loading time per vehicle; the largest step toward realistic dispatch |
| [asymmetric-distances](asymmetric-distances.md) | gated on a real need | supplied distance oracle, directed by default; breaks O(1) chain reversal |
| [deterministic-operator-weighting](deterministic-operator-weighting.md) | not started | deterministic operators re-propose identical rejected moves; weighting cannot see it |
| [determinism-import-branch](determinism-import-branch.md) | small, isolated | per-call attribute read on a hot path for a determinism-only decision |
| [plan-metrics](plan-metrics.md) | deferred on purpose | rule agreed, scale not designed; bad estimates are worse than none |
| [heuristic-survey](heuristic-survey.md) | cheap, gates new operators | the algorithm shortlist was four; DIMACS lists many more, with fixed-endpoint variants unexamined |
| [budget-gated-selection](budget-gated-selection.md) | necessary, not started | expensive operators can eat a small budget in one call; weighting only learns AFTER they run |
| [joint-parameter-search](joint-parameter-search.md) | gated on the noise floor | two flat searches held each other's knobs fixed; needs many more runs per config, and iteration-gating is a trap |

## Done: the re-tune, and its answer

The void search was rerun against the fixed counter — 149 trials, 10 hours, on the reference
instance. **It found nothing.** The best of 149 was less extreme than pure noise predicts for that
many draws, and 51% of trials beat defaults, which is a coin flip. Defaults stand, unchanged, as
the hand-chosen originals.

Numbers and reasoning in [RESULTS.md](../RESULTS.md). The follow-up question — whether
several parameters *together* do what none does alone — is
[joint-parameter-search](joint-parameter-search.md), and it is gated on fixing the noise floor
first.

## Evidence

The measurements these plans are gated on -- geometric guidance, operator ablation, and the
withdrawn tuning result -- are in [RESULTS.md](../RESULTS.md), with the rules used
to accept them. They are kept there rather than here so that a reader meets the evidence before the
roadmap that cites it.

The short version, for ordering purposes:

- **Ablation ranks operators; acceptance rate does not.** The roster's most valuable operator
  accepts 1.09% of its proposals.
- **Geometric guidance raises acceptance from 0.00% to 0.30%, but its objective effect sits at
  about 2 sigma.** That is why `inverted-view-refactor` is gated rather than scheduled.
