# Planning

Planned features for this solver. Each entry states the problem, the measurement that motivates it,
and **the gate that would justify starting it**.

Most are not started yet. The gate is the useful part: it says what has to be true before the work
is worth doing, so the ordering is arguable from evidence rather than asserted.

The plans are grouped into five folders by what they touch:

- **`core-refactors/`** -- internal restructuring of the core model, no new solver behavior.
- **`problem-model/`** -- extends what the solver can represent.
- **`operator-selection/`** -- which operator is chosen and how often; the hub and its mechanisms.
- **`search-methods/`** -- new algorithms and the neighbor machinery they need.
- **`experiments/`** -- measurement and tuning, not solver code.

## Roadmap, by folder

### core-refactors/

| plan | status | one-line reason |
|---|---|---|
| [inverted-view-refactor](core-refactors/inverted-view-refactor.md) | deferred, gate NOT met | O(1) "where is customer j"; needs ablation evidence for guidance, which currently sits at 2 sigma |
| [end-depot-index](core-refactors/end-depot-index.md) | measured, small | the only operator whose cost grows with instance size |
| [module-structure](core-refactors/module-structure.md) | deferred by timeboxing | 4,662-line core model; a mechanical `self` -> typed-parameter split into a static evaluator |
| [raw-delta-accounting](implemented/raw-delta-accounting.md) | **IMPLEMENTED** (steps 0-3, 5; step 4 deferred) | accounting was derived twice and independently; one processor now replaces ~29 per-mutation derivations |
| [route-distance-tracking](core-refactors/route-distance-tracking.md) | unblocked; raw-delta-accounting landed | no route knows its own length; maintain it like load, with an oracle twin |
| [determinism-import-branch](core-refactors/determinism-import-branch.md) | small, isolated | per-call attribute read on a hot path for a determinism-only decision |

### problem-model/

| plan | status | one-line reason |
|---|---|---|
| [warm-start](problem-model/warm-start.md) | small, isolated | saved solutions cannot be loaded back |
| [vehicle-time-limits](problem-model/vehicle-time-limits.md) | blocked on route-distance-tracking | travel + service + loading time per vehicle; the largest step toward realistic dispatch |
| [asymmetric-distances](problem-model/asymmetric-distances.md) | gated on a real need | supplied distance oracle, directed by default; breaks O(1) chain reversal |

### operator-selection/

| plan | status | one-line reason |
|---|---|---|
| [operator-selection](operator-selection/operator-selection.md) | HUB | which operator gets chosen and how often; three coupled concerns and the mechanisms that attack them |
| [repeated-work-detection](operator-selection/repeated-work-detection.md) | designed, gated | route version stamps so a deterministic operator reports NO-OP instead of re-deriving a rejected move |
| [family-generation](operator-selection/family-generation.md) | not started | one operator per parameter value, competing inside a family; online parameter learning |
| [solver-progress-metric](operator-selection/solver-progress-metric.md) | gate met, not started | three plans each need "how converged is this run" and none can ask |
| [budget-gated-selection](operator-selection/budget-gated-selection.md) | necessary, not started | expensive operators can eat a small budget in one call; weighting only learns AFTER they run |

### search-methods/

| plan | status | one-line reason |
|---|---|---|
| [kd-tree-neighbors](search-methods/kd-tree-neighbors.md) | deferred, not needed yet | neighbor table build is O(n^2); only matters above ~50k customers |
| [ruin-and-recreate](search-methods/ruin-and-recreate.md) | ready to start | the real gap against modern VRP; primitives already landed |
| [heuristic-survey](search-methods/heuristic-survey.md) | cheap, gates new operators | the algorithm shortlist was four; DIMACS lists many more, with fixed-endpoint variants unexamined |

### experiments/

| plan | status | one-line reason |
|---|---|---|
| [ablations](experiments/ablations.md) | not started | measurements that would settle questions already asked; currently scattered |
| [plan-metrics](experiments/plan-metrics.md) | deferred on purpose | rule agreed, scale not designed; bad estimates are worse than none |
| [joint-parameter-search](experiments/joint-parameter-search.md) | gated on the noise floor | two flat searches held each other's knobs fixed; needs many more runs per config, and iteration-gating is a trap |

## Done: the re-tune, and its answer

The void search was rerun against the fixed counter — 149 trials, 10 hours, on the reference
instance. **It found nothing.** The best of 149 was less extreme than pure noise predicts for that
many draws, and 51% of trials beat defaults, which is a coin flip. Defaults stand, unchanged, as
the hand-chosen originals.

Numbers and reasoning in [RESULTS.md](../RESULTS.md). The follow-up question — whether
several parameters *together* do what none does alone — is
[joint-parameter-search](experiments/joint-parameter-search.md), and it is gated on fixing the noise floor
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

## Implemented features

See [implemented/README.md](implemented/README.md) for features that have shipped.

## References

- [planning/core-refactors/inverted-view-refactor.md](core-refactors/inverted-view-refactor.md) -- O(1) "where is customer j"; needs
  ablation evidence for guidance, which currently sits at 2 sigma.
- [planning/search-methods/kd-tree-neighbors.md](search-methods/kd-tree-neighbors.md) -- neighbor table build is O(n^2); only matters above
  ~50k customers.
- [planning/search-methods/ruin-and-recreate.md](search-methods/ruin-and-recreate.md) -- the real gap against modern VRP; primitives already
  landed.
- [planning/core-refactors/end-depot-index.md](core-refactors/end-depot-index.md) -- the only operator whose cost grows with instance size.
- [planning/problem-model/warm-start.md](problem-model/warm-start.md) -- saved solutions cannot be loaded back.
- [planning/core-refactors/module-structure.md](core-refactors/module-structure.md) -- 4,662-line core model; a mechanical `self` ->
  typed-parameter split into a static evaluator.
- [planning/core-refactors/route-distance-tracking.md](core-refactors/route-distance-tracking.md) -- no route knows its own length;
  maintain it like load, with an oracle twin.
- [planning/problem-model/vehicle-time-limits.md](problem-model/vehicle-time-limits.md) -- travel + service + loading time per vehicle;
  the largest step toward realistic dispatch.
- [planning/problem-model/asymmetric-distances.md](problem-model/asymmetric-distances.md) -- supplied distance oracle, directed by
  default; breaks O(1) chain reversal.
- [planning/operator-selection/operator-selection.md](operator-selection/operator-selection.md) -- HUB; which operator gets chosen and how often.
- [implemented/README.md](implemented/README.md) -- features that have shipped.
- [planning/operator-selection/repeated-work-detection.md](operator-selection/repeated-work-detection.md) -- route version stamps so a
  deterministic operator reports NO-OP instead of re-deriving a rejected move.
- [planning/operator-selection/family-generation.md](operator-selection/family-generation.md) -- one operator per parameter value, competing inside
  a family; online parameter learning.
- [planning/experiments/ablations.md](experiments/ablations.md) -- measurements that would settle questions already asked; currently
  scattered.
- [planning/core-refactors/determinism-import-branch.md](core-refactors/determinism-import-branch.md) -- per-call attribute read on a hot
  path for a determinism-only decision.
- [planning/experiments/plan-metrics.md](experiments/plan-metrics.md) -- rule agreed, scale not designed; bad estimates are worse than
  none.
- [planning/search-methods/heuristic-survey.md](search-methods/heuristic-survey.md) -- the algorithm shortlist was four; DIMACS lists many
  more, with fixed-endpoint variants unexamined.
- [planning/operator-selection/solver-progress-metric.md](operator-selection/solver-progress-metric.md) -- three plans each need "how converged is
  this run" and none can ask.
- [planning/operator-selection/budget-gated-selection.md](operator-selection/budget-gated-selection.md) -- expensive operators can eat a small
  budget in one call; weighting only learns AFTER they run.
- [planning/experiments/joint-parameter-search.md](experiments/joint-parameter-search.md) -- two flat searches held each other's
  knobs fixed; needs many more runs per config, and iteration-gating is a trap.
- [RESULTS.md](../RESULTS.md) -- the evidence these plans are gated on, and the withdrawn re-tune
  result.
- [planning/implemented/raw-delta-accounting.md](implemented/raw-delta-accounting.md) -- accounting is derived twice and independently; one processor replaces ~29 per-mutation derivations.

## Links to here

- [design/README.md](../design/README.md) -- index to design folder
