# Hierarchical weight magnetism

**IMPLEMENTED, commit `c539a1e`.** See
[design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md)
for what shipped. The plan as agreed follows; how it diverged, and why, is recorded at the end.

---

**Status: not started. PRECEDES the scoring rework**, and is separable from it.

## The inconsistency it fixes

`update_weights` pulls an unproposed operator back up toward the roster's geometric mean:

```python
weight = reheat * max(weight, (weight / geom_mean_weight) ** 0.997 * geom_mean_weight)
```

**That mean is computed over the flat roster.** Family weights, meanwhile, aggregate by MAX up the
tree. So half the weighting is tree-aware and half is not, and the half that is not asks a question
with no good answer: what is a "typical" operator across a roster holding both an intra-route
reversal and a whole-route rebuild?

**Nothing.** Those operators do different jobs. Pulling a rare reversal toward a mean containing
whole-route rebuilds pulls it toward noise.

## The fix: siblings are the reference class

**Pull an unproposed node toward the geometric mean of its SIBLINGS**, not the roster. Siblings do
the same job at different settings, which is the only reference class where "typical" means
something.

This also makes the pull independent of population size, which is the same property MAX already
gives family weights. A family with many members no longer distorts the reference for a family with
few.

### Only children need no rule

An earlier draft of this plan gave only children a special reference class: walk up to the smallest
ancestor subtree holding more than one leaf.

**The recursion removes the need.** The magnet runs at every internal node over its own children. An
only child gets no lift at its own level, because a geometric mean of one value is that value. Its
PARENT is lifted a level up instead, and that factor multiplies down into it.

### Propagation: lifting a node lifts its whole subtree

A node's weight is the MAX of its children, so raising a node has to mean something about its
members. **The lift factor multiplies every leaf in the subtree**, which preserves both the MAX
relationship and the internal ordering.

Order per segment, in `update_weights`:

1. Fold post-order: node weight = MAX over children, and mark whether the subtree saw a proposal.
2. Lift top-down: at each internal node take the geometric mean of its children, pull any child whose
   subtree saw no proposals toward it, and scale that child's whole subtree.
3. Write the lifted weights back into `adj_weights`, then fold again for the floors and cumulative
   arrays.

**Partial proposal needs no special case.** The recursion descends into proposed children and lifts
unproposed ones wherever they sit.

### The reheat trigger stays global

`reheat = 1e5 if max(weights) <= 1e-10` detects total collapse, which is a whole-roster condition.
Per-family reheat would be a different mechanism, not a localization of this one.

## Why this goes first

- **It is a family-tree concern, not a scoring concern.** The tree is already built; this finishes
  making the weighting tree-aware.
- **It changes live behaviour**, unlike the scoring rework, which is mostly new machinery. The magnet
  runs today on every unproposed operator, every segment. That means it deserves its own ablation arm
  rather than being folded into a larger change nobody can attribute.
- **The scoring rework needs the same locality** for its shrunk improvement estimate. Building it
  here first means that arrives as a reuse rather than a second implementation.

## What comes next

The scoring rework applies the same sibling-local rule to a shrunk improvement estimate, and adds a
`Bayes_magnet` parameter in place of the hard-coded `0.997`. See
[scoring-rework](scoring-rework.md).

**Note what does NOT become local: the selection penalty.** Under star selection a family's weight is
its best member's adjusted weight, and that carries to the root. If the penalty were normalized
per-family, weights would mean different things in different families and full-family selection would
skew. **Only magnetism is local, and only for statistical relevance.**

## Open

**Should the magnet be symmetric?** It currently pulls only up, via the `max(...)`. Formal shrinkage
is symmetric -- an estimate above the population mean is shrunk toward it as well. Investigate after
the scoring redesign, because the answer depends on what the score is taken to mean, and the
exploration and plateau phases plausibly want different shapes.

**Current expectation:** keep the resolvability argument on the low end, but a weaker pull on the
high end than a symmetric rule would give.

---

## How this diverged, and why

Built almost exactly as designed. One refinement, not anticipated above: the fold in step 1 of
"Propagation" reads RAW `op.weight`, not `adj_weights`.

Folding adjusted weights cancels the penalty and can invert it. Equalizing adjusted weights forces
raw weights apart by `1/penalty`, so a cheap operator's raw weight is pulled down and an expensive
one's is pulled up -- backwards. Benjamin's framing, 2026-08-23, once the dynamic penalty
([scoring-rework.md](scoring-rework.md)) made the two differ enough to matter.

## References

- [design/operator_selection/hierarchical_magnetism.md](../../design/operator_selection/hierarchical_magnetism.md)
  -- the design this plan became.
- [scoring-rework.md](scoring-rework.md) -- the plan that lands after this one, and whose penalty
  made the raw versus adjusted fold distinction matter.

## Links to here

- [scoring-rework.md](scoring-rework.md) -- names this as the plan that landed first.
