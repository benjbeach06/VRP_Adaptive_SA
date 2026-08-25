# Hierarchical weight magnetism

An operator that saw no proposals in a segment still needs a weight update. `update_weights` pulls
it toward its SIBLINGS rather than leaving it frozen:

```python
lifted = max(value, (value / gm) ** Bayes_magnet * gm)
```

`gm` is the geometric mean of the node's siblings — the other children of the same family node.
`Bayes_magnet` sits close to 1; smaller pulls harder.

## Siblings are the reference class

A mean over the flat roster asks what is "typical" across a roster holding both an intra-route
reversal and a whole-route rebuild. Nothing is: those operators do different jobs, and pulling a
rare reversal toward a mean containing whole-route rebuilds pulls it toward noise.

Siblings do the same job at different settings, which is the only reference class where "typical"
means something. It also makes the pull independent of population size, the same property MAX
already gives family weights — a family with many members does not distort the reference for a
family with few.

## Lifting a node lifts its whole subtree

A node's weight is the MAX of its children, so raising a node has to mean something about its
members. The lift factor multiplies every leaf in the subtree (`_scale_subtree`), preserving both
the MAX relationship and the internal ordering.

**An only child gets no lift at its own level**, because a geometric mean of one value is that
value. It is reached through its parent instead, one level up, and that factor multiplies down into
it. No special case is needed for it, and none for partial proposal either: the recursion descends
into proposed children and lifts unproposed ones wherever they sit.

## Order per segment

1. **Fold RAW `op.weight`**, post-order: node weight = MAX over children, and mark whether the
   subtree saw any proposal.
2. **Lift top-down** (`_lift_unproposed`): at each internal node take the geometric mean of its
   children, pull any child whose subtree saw no proposals toward it, and scale that child's whole
   subtree.
3. **Write the lifted weights into `adj_weights`**, multiplied by
   `exploit_selection_penalty_factor` and `penalty`.

**The fold reads raw weight, not `adj_weights`.** Folding adjusted weights cancels the penalty and
can invert it: equalizing adjusted weights forces raw weights apart by `1/penalty`, pulling a cheap
operator's raw weight down and an expensive one's up. See
[dynamic_penalty.md](dynamic_penalty.md).

## What stays global

**The reheat trigger.** `reheat = 1e5 if max(weights) <= 1e-10` detects total collapse, which is a
whole-roster condition. Per-family reheat would be a different mechanism, not a localization of
this one.

**The selection penalty.** Magnetism is local because "typical" needs a comparable reference class.
Normalization is not, because a family's weight is its best member's adjusted weight and that
carries to the root. See [dynamic_penalty.md](dynamic_penalty.md).

## Open

**Should the magnet be symmetric?** It pulls only up, via `max(...)`. Formal shrinkage is
symmetric — an estimate above the population mean is shrunk toward it as well. Unresolved. Current
expectation is to keep the resolvability argument on the low end and a weaker pull on the high end
than a symmetric rule would give, because exploration and plateau phases plausibly want different
shapes.

## References

- [dynamic_penalty.md](dynamic_penalty.md) — the penalty the fold must not read, and the global
  normalization this deliberately does not localize.

## Links to here

- [dynamic_penalty.md](dynamic_penalty.md) — cites this for what is family-local.
- [planning/implemented/hierarchical-magnetism.md](../../planning/implemented/hierarchical-magnetism.md)
  — the plan this became; points here for what shipped.
- [README.md](README.md) — summarises this doc in the folder index.
- [../README.md](../README.md) — summarises this doc in the top-level index.
