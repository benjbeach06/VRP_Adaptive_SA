# Implemented features

Features planned and built. Each file records the plan as agreed, then how it diverged (if at all) and what shipped. The commit column names when the feature reached final form.

| feature | commit | description |
|---|---|---|
| [scoring-rework.md](scoring-rework.md) | `c25a7a0` | replaced hand-set penalties with a dynamic one; the improvement-weighted version inverted its own ranking at plateau and was replaced again -- see [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md) |
| [hierarchical-magnetism.md](hierarchical-magnetism.md) | `c25a7a0` | the weight magnet pulls an unproposed operator toward its SIBLINGS, not the flat roster -- see [design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md) |
| [forget-benefit-not-cost.md](forget-benefit-not-cost.md) | `c25a7a0` | the weight EMA decays benefit every segment while the cost-ratio penalty never decays -- see [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md) |
| [doubly-linked-references.md](doubly-linked-references.md) | `e5262c3` | every doc reference recorded at both ends; shipped as three scripts (`link_scan.py`, `link_annotate.py`, `update_linkages_for_move.py`) plus two skills, wider than the plan's checker-only design |

## References

- [scoring-rework.md](scoring-rework.md) -- replaced hand-set penalties with a dynamic one.
- [hierarchical-magnetism.md](hierarchical-magnetism.md) -- the weight magnet pulls an unproposed
  operator toward its siblings, not the flat roster.
- [forget-benefit-not-cost.md](forget-benefit-not-cost.md) -- the weight EMA decays benefit every
  segment while the cost-ratio penalty never decays.
- [doubly-linked-references.md](doubly-linked-references.md) -- every doc reference recorded at
  both ends, rolled out repo-wide.
- [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md)
  -- the shipped penalty that scoring-rework and forget-benefit-not-cost feed.
- [design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md)
  -- the mechanism hierarchical-magnetism became.

## Links to here

- [../README.md](../README.md) -- cites this folder in the "Implemented features" section.
