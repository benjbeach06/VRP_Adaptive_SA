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
family-level ablation runs** -- see [planning/ablations.md](../../planning/ablations.md).

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
before it decays is in [planning/ablations.md](../../planning/ablations.md).

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

Measured, 300,000 calls on a 200-customer instance: **1.575 us per selection flat, 0.434 us
descending.** The cumulative arrays are built once per segment in `refresh_family_tree`, not per
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

## Node layout: internal nodes before leaves

Ids below `n_internal` index `node_children`; ids at or above it index `leaf_operator`. Two
consequences, both deliberate:

- **Neither array holds `None`.** An earlier version mixed internal nodes and operators in one array
  and needed `Operator | None` everywhere it was read.
- **A reverse scan is a valid bottom-up order**, because a parent is always created before its
  children. No topological sort is kept.

Every internal node exists because some operator's path ran through it, so none is childless and the
fold never calls `max()` on an empty sequence.

## Related

- [share_floors.md](share_floors.md) -- the projection that guarantees each root family a minimum
  share. Floors bind at level 0 only.
- [exploitation_governance.md](exploitation_governance.md) -- the per-leaf penalty factor. It still
  multiplies into the leaf weight, and now feeds the family max as well, so **families compete on
  cost-adjusted merit rather than on raw performance.**
- [planning/operator-selection.md](../../planning/operator-selection.md) -- open selection work.
- [span_reorder/reorder_operators.md](../span_reorder/reorder_operators.md) -- the inheritance there
  marks a family boundary, and the tree now reads it.
