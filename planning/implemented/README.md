# Implemented features

Features planned and built. Each file records the plan as agreed, then how it diverged (if at all) and what shipped. The commit column names when the feature reached final form.

| feature | commit | description |
|---|---|---|
| [scoring-rework.md](scoring-rework.md) | `c25a7a0` | replaced hand-set penalties with a dynamic one; the improvement-weighted version inverted its own ranking at plateau and was replaced again -- see [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md) |
| [hierarchical-magnetism.md](hierarchical-magnetism.md) | `c25a7a0` | the weight magnet pulls an unproposed operator toward its SIBLINGS, not the flat roster -- see [design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md) |
| [forget-benefit-not-cost.md](forget-benefit-not-cost.md) | `c25a7a0` | the weight EMA decays benefit every segment while the cost-ratio penalty never decays -- see [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md) |
| [doubly-linked-references.md](doubly-linked-references.md) | `e5262c3` | every doc reference recorded at both ends; shipped as three scripts (`link_scan.py`, `link_annotate.py`, `update_linkages_for_move.py`) plus two skills, wider than the plan's checker-only design |
| [module-structure.md](module-structure.md) | `c9090b6` | the mechanical `self` -> typed-parameter split, applied to the delta arithmetic only. 51 methods became free functions in `SimAnn_VRP_Core_Model/deltas/`; `Route` fell from 2,046 lines to 833. Every other method on a core-model type stays a method, and the oracle twins are still not parallel -- see the divergence section |
| [raw-delta-accounting.md](raw-delta-accounting.md) | `321864b` | the core model reports raw structural deltas; one processor derives every objective term and one sink writes every cache, replacing ~29 per-mutation derivations. The record shape and apply mechanism diverged from the plan; step 4 (end-depot usage) is deferred -- see [design/raw_delta_accounting/](../../design/raw_delta_accounting/) |

## References

- [scoring-rework.md](scoring-rework.md) -- replaced hand-set penalties with a dynamic one.
- [hierarchical-magnetism.md](hierarchical-magnetism.md) -- the weight magnet pulls an unproposed
  operator toward its siblings, not the flat roster.
- [forget-benefit-not-cost.md](forget-benefit-not-cost.md) -- the weight EMA decays benefit every
  segment while the cost-ratio penalty never decays.
- [doubly-linked-references.md](doubly-linked-references.md) -- every doc reference recorded at
  both ends, rolled out repo-wide.
- [raw-delta-accounting.md](raw-delta-accounting.md) -- one processor derives every objective term
  from raw structural deltas; one sink writes every cache.
- [module-structure.md](module-structure.md) -- the delta arithmetic became free functions in a
  `deltas` subpackage; the rest of the core model did not.
- [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md)
  -- the shipped penalty that scoring-rework and forget-benefit-not-cost feed.
- [design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md)
  -- the mechanism hierarchical-magnetism became.

## Links to here

- [../README.md](../README.md) -- cites this folder in the "Implemented features" section.
- [retros/2026-08-26_doc_linking_and_time_robust_tuning.md](../../retros/2026-08-26_doc_linking_and_time_robust_tuning.md) -- retro; notes the caught hand-edit of this file's ## References
