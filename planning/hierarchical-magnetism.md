# Hierarchical weight magnetism

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

### Only children

`RandomRoutePermutation` is the sole leaf under `RANDOM`, so its sibling set is itself and the magnet
degenerates.

**Reference class = the leaves of the smallest ancestor subtree containing more than one leaf.** An
only child has no competition at its own level anyway -- it is drawn whenever its parent is, so what
it needs is for its PARENT not to be starved. The walk up is computed once when the tree is built.

### Propagation: lifting a family lifts its whole subtree

A node's weight is the MAX of its children, so a node cannot be raised on its own -- raising it has
to mean something about its members.

**When a node is pulled up by a factor `f`, every descendant is multiplied by `f`.** A uniform
proportion preserves both the MAX relationship and the internal ordering, so the family rises without
its internal competition changing.

Order of work, once per segment:

1. **Bottom-up:** node weight = MAX over children. Also mark whether any operator in the subtree was
   proposed this segment.
2. **Top-down DFS:** at each internal node, take the geometric mean of its children's weights. For
   each child whose subtree saw no proposals, compute the magnet factor and carry it down,
   multiplying it into every descendant.

One pass each way, `O(total nodes)`. The current tree has 17 internal nodes and 24 leaves, once per
100 proposals. It stays linear as the tree grows, which matters once
[family-generation](family-generation.md) starts creating sub-operators.

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
