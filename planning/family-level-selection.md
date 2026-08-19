# Two-level selection: choose a FAMILY, then an operator

**Status: not started. A structural bias in how operators are selected, not a tuning problem.**

## The problem

**Intra-route work crowds out everything else.** There are many intra-route operators, they improve
often, and flat selection rewards both of those facts. Big-picture exploration -- moving customers
between routes, changing route structure, changing which vehicle serves what -- gets what is left.

The bias is in the SELECTION MECHANISM, not in the weights. Selection draws over a flat list of
operators, so a family's share of the budget is decided by **how many members it happens to have**.
Adding a good intra-route operator raises the intra-route family's total share even when the family
already had more than it deserved.

That is backwards. The roster is a list of available moves. It should not double as the allocation
policy.

## Evidence

From the adaptive-weighting run, 180s at n=500 capacity 400, by wall-clock share:

| operator | share | scope |
|---|---|---|
| `ReverseClosestPairTogether` | 31.8% | intra-route |
| `ReorderSpanByFarthestInsertion` | 15.2% | intra-route |
| `CustomerBestOfkSwapInRandomRoute` | 8.4% | intra-route |
| `ReassignChainNextToNeighbor` | 12.9% | inter-route |
| `RandomRouteReassignment` | 7.3% | structural |

Three intra-route operators take **55%** of the budget between them. Full table in
`experiment_logs/`, produced by `tools/compare_runs.py`.

**The scope column is my classification and needs auditing** before it is used for anything. Naming
the families is the first task here, not a preliminary to it.

## The fix

**Families are structured by FURTHEST REACH or UNIQUE PURPOSE**, and the class tree expresses them
directly. Single inheritance is enough, because reach is one axis -- mechanism falls out of it
rather than competing with it. Swap and combine sit together because their purpose is the same, not
because their mechanism is.

First cut of the families:

| family | note |
|---|---|
| swap + combine | one family; shared purpose |
| change end depot | its own family; unique purpose, no relatives |
| intra-route moves | a family TREE, with sub-families |
| inter-route moves | a family TREE |
| whole-route moves | one family |

### Weights: MAX of members, leaves to root

A parent's weight is the **maximum of its children's weights**, computed recursively from the leaves
up. **A family is defined by its star, and does not care about its size.**

**Size-independence is exact, not approximate.** Adding a member never changes a family's weight
unless the new member is better than everything already there. That is the property generation
needs: splitting one operator into six span sizes does not cost the family its allocation.

It does not make generation free. It makes generation **almost** free, which is a different claim --
see the costs below.

A geometric mean does not give that. Adding a mediocre member LOWERS the family weight, so every
generated family is penalized for the members that did not work out -- which is backwards, since
finding out they do not work is the point.

**It also removes the small-family fragility outright.** Under a geometric mean, one collapsed member
drags its family down, and the damage grows as `1/n` in small families. Under a max, a collapsed
member is simply ignored.

### Size still matters, indirectly, and that is the right incentive

Max makes family weight independent of member COUNT. It does not make depth worthless.

A family with several genuinely different members has more chances to contain the best operator for
the current instance and the current phase. Depth does not inflate the weight; it raises the odds
that the family holds a star at all.

**And it buys phase-robustness.** A family's weight is the upper envelope of its members over time.
Six span sizes cover cheap-and-early and expensive-and-late, so the family stays competitive across
a whole run, while a single-member family rises and falls with its one operator.

So the incentives come out right in both directions. Adding a genuinely useful member helps, because
it may become the max. Padding a family with weak members does nothing, because they never do. A
family with few members and nothing special in it loses -- correctly.

### The trade, stated plainly

A geometric mean was chosen to stop an overperforming member drowning out the solve. **Max removes
that damping.** One spiking member lifts its whole family.

Two reasons to think that is acceptable, neither yet measured:

- **The family spends its budget on the star.** Conditional routing sends nearly all of the family's
  share to the member that earned it. A real overperformer getting budget is correct behaviour, not
  a failure.
- **Spikes are transient.** A high reaction factor makes them sharp and short-lived, and reheat
  re-randomizes. Divergence does not persist.

**What to check:** whether a transient spike lifting a whole family does harm before it decays. That
is the one thing max gives up, and it is measurable against real weight traces.

### Selection: descend the tree

Draw a family, then descend into it, one level at a time:

```
leaf weight        = op.weight * op.exploit_selection_penalty_factor
internal weight    = max(children weights)
P(child | parent)  = child_weight / sum(sibling weights)
```

At each level, sample among siblings in proportion to weight. Repeat until a leaf. That is
**identical in distribution** to computing the product of conditional probabilities per leaf, and
much cheaper to evaluate.

**Cost is O(depth x branching), not O(roster).** Flat selection accumulates over every operator on
every proposal, so it taxes the whole roster whenever any part of it grows. A hierarchical draw
touches only the siblings on one root-to-leaf path, so adding six span sizes costs one extra
comparison inside one family and nothing anywhere else.

That is what makes generation viable at scale rather than merely fair.

**`choose_operator` changes**, and `adj_weights` becomes per-NODE rather than per-leaf. Both are
still refreshed once per segment in `update_weights`, which already walks every operator.

### The greedy penalties are unchanged, and they propagate

`exploit_selection_penalty_factor` still multiplies into the LEAF weight, exactly as it does today.
Nothing about that mechanism changes.

**But it now feeds the family max as well**, because a parent takes the maximum of its children's
already-penalized weights. That is the right behaviour and worth stating explicitly: **families
compete on cost-adjusted merit, not on raw performance.**

An expensive operator cannot lift its family on payoff alone. It has to be worth its cost first,
and only the surviving figure is what its family presents upward. A family whose star is expensive
and a family whose star is cheap are compared after both have paid.

### Why the obvious risk mostly is not there

A geometric mean is pulled down hard by one small member, and the pull is worse in a SMALL family
because the exponent is `1/n`. A two-member family with one member at 1e-3 loses 32x; a
five-member family loses 4x.

**That case does not arise in practice, because weights do not spread that way.** Three observed
behaviours all work against it:

- **Rarely-used operators cluster.** They bunch at similar low weights rather than one member
  collapsing alone. A family is low together or healthy together; a lone outlier below its siblings
  is not the shape the distribution takes.
- **At a plateau with no accepted moves, weights converge toward uniform.** Nothing scores, so the
  EMA carries everyone to the same place.
- **Reheat re-activates the roster**, and a high reaction factor makes the resulting spikes both
  sharper and shorter-lived. Divergence is transient by construction.

So the geometric mean behaves like an arithmetic mean while members agree, and damps only when one
diverges -- which is exactly the transient spike it is meant to damp. **The protective property
fires precisely when it is wanted, and is inert otherwise.**

### The dependency that IS load-bearing

The convergence-at-plateau argument holds **only if no-ops are correctly detected.** An operator
that proposes nothing useful must be seen to propose nothing, or it keeps earning weight it has not
earned and the family average is wrong.

That makes family weighting depend on the gatekeeping convention: degenerate proposals report
INVALID or NOOP, never a zero-delta VALID. The identity-reorder fix
(`design/span_reorder/reorder_operators.md`) closed one such hole. **Audit the rest before
trusting family weights** -- a silent zero-delta VALID anywhere in a family corrupts that family's
mean, and now the corruption spreads to every sibling instead of staying local.

**There is precedent for the mechanism.** `update_weights` already computes `geom_mean_weight`
across the roster and uses it to pull unproposed operators back toward the middle
(`SimAnn_VRP_Solver.py:203, 217`). Geometric means are already load-bearing in this selector.

## What this UNLOCKS: family generation

The strongest reason to build this is not tidier allocation. It is that families make **generated
operators** safe, and generated operators turn a parameter into something the solver learns instead
of something a search has to find.

### The example

`ReorderShortSpanExactly` draws its span length uniformly from [3, 8]. Those spans do not cost the
same -- 6 permutations against 40,320 -- and they do not pay off the same either. One operator, one
weight, one `mean_call_time` **averaged over a 6000x cost range**. The scoring cannot tell "span 4 is
excellent value" from "span 8 is waste", so it prices the blend and acts on neither.

Generate the family instead: one FIXED-span operator per size. Each prices independently, on its own
measured cost and its own measured payoff. The family aggregates them.

### It generalizes to any numeric parameter

Span length is one instance. `k` in the BestOfk operators, chain length, `NEIGHBOR_ROUTE_DRAWS` --
each is a constant chosen once and searched offline, and each could instead be a generated family
whose members compete.

**That is online parameter learning, and it attacks the problem
[joint-parameter-search](joint-parameter-search.md) says is unaffordable.** Offline tuning of these
values needs runs measured in days, per instance shape, and does not transfer. A generated family
learns the value DURING the solve, on the instance actually being solved.

### The two ideas need each other

**Generation without family selection is harmful.** Splitting one operator into six multiplies that
operator's share of a flat draw by six. That is the roster-composition bias above, made worse
deliberately.

**Family selection without generation is only tidier.** It fixes an allocation bias that exists
today, which is worth doing, but it does not add capability.

Together they change what the solver can do: the family holds the budget, and the members inside it
compete to spend it.

### What generation actually costs

Nothing is free. Max removes the ALLOCATION penalty; three costs remain.

**Within-family dilution.** Six members share one family's budget, so each is drawn about a sixth as
often as a single operator would be. The family keeps its share; each member gets less of it.

**Learning cost.** Every member needs proposals before its weight means anything. Six members need
roughly six times the samples before the family knows which is best, and until then the family
spends real budget on members that will turn out useless. On a short run that may never converge --
which is the same power problem as [joint-parameter-search](joint-parameter-search.md), moved
inside the solve.

**A per-proposal tax on the WHOLE roster.** `choose_operator` accumulates cumulative weights across
every operator on every proposal, so it is O(roster). Tripling the roster triples that cost -- and
it charges every family, not just the generated one. At roughly 20k proposals per second, this is
not a rounding error.

That last one deserves attention because it is the one that fights throughput, and throughput is the
scarce resource here.

**The hierarchical draw removes this one.** See the selection section above: descending the tree
touches only one root-to-leaf path, so a generated family costs one extra comparison inside itself
and nothing to any other family. Flat selection would have charged the whole roster.

The other two costs -- dilution and learning -- are real and remain.

### The open question

**Size-independence is what makes generation viable, and MAX supplies it exactly** -- see the
weighting section above. A family of six span sizes cannot out-earn a family of one by having more
members, because only the best member counts.

What is still open is the cost side. Members differing by orders of magnitude in cost still have to
be comparable to each other WITHIN the family, and that comparison runs through `mean_cost` in the
score. Whether the existing per-operator cost division is enough, or whether generated members need
their own normalization, is unmeasured.

## Related

- [deterministic-operator-weighting](deterministic-operator-weighting.md) -- also modifies selection,
  via a multiplier. Two-level selection changes where that multiplier applies.
- [budget-gated-selection](budget-gated-selection.md) -- gates on affordability. A family level is
  the natural place to gate, since cost correlates with scope.
- [solver-progress-metric](solver-progress-metric.md) -- family weights plausibly SHOULD move with
  progress: structural moves early, intra-route refinement late. That is the strongest argument for
  building the metric.

## Gate

None on correctness. The gate is design: name the families, decide how scope is declared alongside
mechanism, and only then touch `choose_operator`.

Worth doing before the next ablation. Family-level ablation is the measurement that would show
whether the crowding actually costs objective, and it needs the families to exist first.
