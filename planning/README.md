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
| [end-depot-index](end-depot-index.md) | measured, small | the only operator whose cost grows with instance size |
| [warm-start](warm-start.md) | small, isolated | saved solutions cannot be loaded back |
| [module-structure](module-structure.md) | deferred by timeboxing | 4,662-line core model; a mechanical `self` -> typed-parameter split into a static evaluator |
| [route-distance-tracking](route-distance-tracking.md) | small, self-verifying | no route knows its own length; maintain it like load, with an oracle twin |
| [vehicle-time-limits](vehicle-time-limits.md) | blocked on the above | travel + service + loading time per vehicle; the largest step toward realistic dispatch |
| [asymmetric-distances](asymmetric-distances.md) | gated on a real need | supplied distance oracle, directed by default; breaks O(1) chain reversal |
| [operator-selection](operator-selection.md) | HUB | which operator gets chosen and how often; three coupled concerns and the mechanisms that attack them |
| [implemented/scoring-rework](implemented/scoring-rework.md) | IMPLEMENTED, then partly superseded | replaced hand-set penalties with a dynamic one; the improvement-weighted version inverted its own ranking at plateau and was replaced again -- see [design/operator_selection/dynamic_penalty.md](../design/operator_selection/dynamic_penalty.md) |
| [implemented/hierarchical-magnetism](implemented/hierarchical-magnetism.md) | IMPLEMENTED | the weight magnet pulls an unproposed operator toward its SIBLINGS, not the flat roster -- see [design/operator_selection/hierarchical_magnetism.md](../design/operator_selection/hierarchical_magnetism.md) |
| [repeated-work-detection](repeated-work-detection.md) | designed, gated | route version stamps so a deterministic operator reports NO-OP instead of re-deriving a rejected move |
| [forget-benefit-not-cost](forget-benefit-not-cost.md) | idea | decay an operator's remembered payoff but keep its remembered cost, so expensive operators run less even at plateau |
| [family-generation](family-generation.md) | not started | one operator per parameter value, competing inside a family; online parameter learning |
| [ablations](ablations.md) | not started | measurements that would settle questions already asked; currently scattered |
| [determinism-import-branch](determinism-import-branch.md) | small, isolated | per-call attribute read on a hot path for a determinism-only decision |
| [plan-metrics](plan-metrics.md) | deferred on purpose | rule agreed, scale not designed; bad estimates are worse than none |
| [heuristic-survey](heuristic-survey.md) | cheap, gates new operators | the algorithm shortlist was four; DIMACS lists many more, with fixed-endpoint variants unexamined |
| [solver-progress-metric](solver-progress-metric.md) | gate met, not started | three plans each need "how converged is this run" and none can ask |
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
