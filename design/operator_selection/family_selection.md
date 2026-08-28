# Family-level operator selection

**Code:** `SimAnn_VRP_Operators.py` -- `Family`, and the `family` ClassVar on each operator
**Code:** `SimAnn_VRP_Solver.py` -- `_build_family_tree`, `refresh_family_tree`, `choose_operator`

Selection draws a family, then descends to an operator, instead of drawing once over a flat roster.

> **Roster snapshot: 2026-08-20, 24 operators.** Every count, share, and timing below is measured
> against that roster and drifts as operators are added. They describe the SHAPE of the allocation,
> not a current inventory. Re-measure with `tools/family_tree.py` before citing one as a fact about
> today's solver.

## What it fixes

**The case for the tree is STRUCTURAL, not empirical.** Flat selection accumulated weights across
every operator on every proposal, so **a family's share of the budget depended on how many members it
happened to have.** Adding a good intra-route operator raised the intra-route share whether or not
intra-route work deserved more. That is operator-family dilution: a KIND of move is diluted by how
many implementations of it the roster holds.

The roster is a list of available moves. It should not also be the allocation policy.

The numbers below describe what the mechanism does. They are not the argument for building it, and
none of them is strong enough to be. **Whether the tree improves the objective is unmeasured until
family-level ablation runs** -- see [planning/ablations.md](../../planning/experiments/ablations.md).

## Operators carry a PATH, not a class position

Each operator declares a tuple of `Family` values, root first. The tree is rebuilt by grouping on
prefixes, so depth varies per branch -- one level for `CHANGE_END_DEPOT`, four for
`ReorderShortSpanExactly`.

**The class hierarchy cannot supply this.** `ReverseClosestPairTogether` and `CombineRandomRoutes`
both inherit `BestOfCandidates`, which is a mechanism base, so grouping by class would put them in
one subfamily across two different root families. Aligning the class tree with the family tree is
possible later; the path keeps the tree independent of whether that ever happens.

Tags sit on the widest base that is entirely one family and subclasses inherit, so fourteen
declarations cover twenty-four operators. The ClassVar has **no default** -- an operator added to the
roster without a path raises rather than landing in an arbitrary family.

## A family is defined by its WIDEST reach

Anything that can change customer-to-route assignment is `INTER_ROUTE`, even when a given draw
happens to stay inside one route. Only operators confined to one route on **every** draw are
`INTRA_ROUTE`.

| root family | operators | what it changes |
|---|---|---|
| `INTRA_ROUTE` | 9 | order within one route |
| `INTER_ROUTE` | 11 | which route a customer belongs to |
| `FULL_ROUTE` | 1 | which vehicle serves a route; no customer changes route |
| `CHANGE_NUM_ROUTES` | 2 | how many routes exist |
| `CHANGE_END_DEPOT` | 1 | end-depot assignment only |

`ChangeRandomEndDepot` touches two routes through the vehicle chain, so a "touches 2+ routes" rule
would place it in `INTER_ROUTE`. The definition beats the heuristic: no customer changes route, so
it stays separate.

## Weight is the MAX over the subtree

A node is worth what its best member is worth. **Size-independence is exact:** adding a member never
changes a family's weight unless the new member beats everything already there.

A geometric mean does not give that. Adding a mediocre member LOWERS the family weight, so a family
is penalized for the members that did not work out -- backwards, since finding that out is the point.
Max also removes the small-family fragility outright, where one collapsed member drags its siblings
down as `1/n`.

MAX is associative, so the fold is one bottom-up pass and depth costs nothing.

**The trade, accepted on purpose: one spiking member lifts its whole family.** The geometric mean
damped that. Two reasons to think it is acceptable, neither measured: the family routes nearly all of
its share to the star that earned it, which is correct behavior rather than a failure; and spikes
decay, since a high reaction factor makes them sharp and short-lived. Whether a spike does harm
before it decays is in [planning/ablations.md](../../planning/experiments/ablations.md).

## Size still matters, indirectly, and that is the right incentive

MAX makes family weight independent of member COUNT. It does not make depth worthless.

A family with several genuinely different members has more chances to hold the best operator for the
current instance and the current phase. Depth does not inflate the weight; it raises the odds that
the family holds a star at all.

**And it buys phase-robustness.** A family's weight is the upper envelope of its members over time,
so a family spanning cheap-and-early and expensive-and-late stays competitive across a whole run,
while a single-member family rises and falls with its one operator.

The incentives come out right both ways. Adding a genuinely useful member helps, because it may
become the max. Padding a family with weak members does nothing, because they never will. A family
with few members and nothing special in it loses -- correctly.

## The dependency that IS load-bearing

**Family weights are only as good as no-op detection.** An operator that proposes nothing useful must
be SEEN to propose nothing. If a degenerate proposal reports a zero-delta VALID instead of NOOP, that
operator earns weight it did not earn.

Under MAX the error does not stay local. One operator with an inflated weight becomes its family's
max and lifts the whole family's share, so a single bad gatekeeper misallocates a family rather than
an operator.

So family selection depends on the gatekeeping convention: degenerate operands report INVALID or
NOOP, never a zero-delta VALID. The identity-permutation check in
[span_reorder/reorder_operators.md](../span_reorder/reorder_operators.md) closed one such hole and
the suite now detects them, but **the audit is not complete.**

## Descent, one level at a time

Sampling among siblings in proportion to weight, repeatedly, is **identical in distribution** to
drawing one leaf from the product of its conditional probabilities. Descending is much cheaper to
evaluate, because it touches only one root-to-leaf path.

Flat selection was O(roster) per proposal, so adding an operator taxed every family. Descent is
O(depth x branching), so a new operator costs one extra comparison inside its own family and nothing
anywhere else. **That is what makes generated families affordable later.**

Measured against the flat version it replaced, same roster of 24, same protocol -- 10,000 reps of
100 calls, median reported because a scheduling tail pulls the mean:

| | us per selection |
|---|---|
| flat accumulate | 1.538 |
| tree descent | **0.432** |

**3.56x.** The cumulative arrays are built once per segment in `refresh_family_tree`, not per
proposal, which is where the saving comes from.

## Depth changes share, and that is the point

Descent multiplies conditionals, so a deep leaf is drawn less often than a shallow one at equal
weights. Measured over 600,000 draws with every weight set to 1.0:

| operator | depth | share | flat would give |
|---|---|---|---|
| `ChangeRandomEndDepot` | 1 | 16.6% | 4.17% |
| `SplitRandomRoute` | 1 | 8.3% | 4.17% |
| `ReorderShortSpanExactly` | 4 | 2.1% | 4.17% |
| `ReorderSpanByFarthestInsertion` | 4 | 0.69% | 4.17% |

A 24x spread from tree position alone.

**This is deliberate. Operators do not need equal weight; families do.** At a plateau nothing scores
and the EMA carries every weight toward uniform, which is exactly when the tree matters: it keeps the
KINDS of move balanced rather than letting whichever kind has the most implementations dominate.
Equal weight across 24 operators is type dilution, not fairness.

**The floors bind precisely in that state.** With all weights equal the natural root share is 0.20
each, which is under both 0.25 floors, so intra-route and inter-route clamp up and the remaining
three split what is left at 0.166. Measured root shares at equal weights: 0.250, 0.251, 0.166, 0.167,
0.166. So the guarantee is not decorative -- it is active exactly when the search is stuck.

The deep families are deep because they earned refinement. The root floors are what pays for that
depth -- see [share_floors.md](share_floors.md).

## The tree is objects, not arrays

Two classes. `_FamilyNode` holds children, a cumulative array and a floor. `_LeafNode` holds one
operator. Every node carries a `parent` link.

**Two classes rather than one.** One class would need `Operator | None` on every node and a check at
every read. The Optional is the thing being avoided, not a detail.

**Narrowing is by `isinstance`.** A literal discriminator attribute does not narrow a union in
pyright -- neither `ClassVar[Literal[True]]` nor an instance `Literal[True]`. Only `isinstance`
does, and it costs nothing measurable. So the union carries no flag attribute at all.

### Rejected: integer-indexed arrays

The first version encoded the tree as adjacency lists over integer ids, with internal nodes below
`n_internal` and leaves above.

**It assumed the tree shape never changes**, and that assumption was never stated or checked.
[planning/family-generation.md](../../planning/operator-selection/family-generation.md) has families adding and removing
members during a solve, so positional ids would mean reindexing or tombstones on every change.

The two forms are within a few nanoseconds of each other per selection, which is under 0.1% of even
the cheapest operator's cost. **Nothing was traded for the object form.**

## Changing the roster

`remove(target)` takes a family path tuple, an `Operator` subclass, or a node.

It detaches the node from its parent, drops that subtree's operators from `adj_weights` and the
roster, and removes any parent left with no children. **It rebuilds nothing.** Ancestor weights and
cumulative arrays are recomputed by `refresh_family_tree`, which already runs once per segment.

A node with no children cannot report a MAX, which is why an emptied parent goes as well.

**Dynamic ADD is the same capability and is not built.** The structure now permits it. See
[planning/family-generation.md](../../planning/operator-selection/family-generation.md).

- [share_floors.md](share_floors.md) -- the projection that guarantees each root family a minimum
  share. Floors bind at level 0 only.
- [exploitation_governance.md](exploitation_governance.md) -- the per-leaf penalty factor, which
  multiplies into the leaf weight and so feeds the family max. **It is 1.0 for every operator as of
  2026-08-22**, so families currently compete on raw weight and cost. The adaptive penalty that
  restores cost-adjusted competition is now built -- [dynamic_penalty.md](dynamic_penalty.md).
- [hierarchical_magnetism.md](hierarchical_magnetism.md) -- the sibling-local magnet that runs on
  this tree, folding and lifting the same `adj_weights` this doc describes.
- [planning/operator-selection.md](../../planning/operator-selection/operator-selection.md) -- open selection work.
- [span_reorder/reorder_operators.md](../span_reorder/reorder_operators.md) -- the inheritance there
  marks a family boundary, and the tree now reads it.

## Links to here

- [../span_reorder/reorder_operators.md](../span_reorder/reorder_operators.md) -- its inheritance
  marks a family boundary this tree reads.
- [README.md](README.md) -- summarises this doc in the folder index.
- [../README.md](../README.md) -- summarises this doc in the top-level index.
- [share_floors.md](share_floors.md)
- [planning/experiments/ablations.md](../../planning/experiments/ablations.md)
- [planning/operator-selection/family-generation.md](../../planning/operator-selection/family-generation.md)
- [planning/operator-selection/operator-selection.md](../../planning/operator-selection/operator-selection.md)
- [planning/operator-selection/repeated-work-detection.md](../../planning/operator-selection/repeated-work-detection.md)
- [retros/2026-08-26_doc_linking_and_time_robust_tuning.md](../../retros/2026-08-26_doc_linking_and_time_robust_tuning.md) -- retro; the body_links() reversed-section bug was found on this file

## References

- [hierarchical_magnetism.md](hierarchical_magnetism.md) -- sibling-local magnet running on this tree
- [share_floors.md](share_floors.md) -- projection guaranteeing minimum share per root family
- [design/span_reorder/reorder_operators.md](../span_reorder/reorder_operators.md) -- inheritance marks family boundary
- [exploitation_governance.md](exploitation_governance.md) -- per-leaf penalty factor feeding family max
- [planning/operator-selection/operator-selection.md](../../planning/operator-selection/operator-selection.md) -- open selection work
- [dynamic_penalty.md](dynamic_penalty.md) -- cost-adjusted competition
- [planning/experiments/ablations.md](../../planning/experiments/ablations.md) -- family-level ablation to measure tree effectiveness
- [planning/operator-selection/family-generation.md](../../planning/operator-selection/family-generation.md) -- dynamic family growth and member removal
