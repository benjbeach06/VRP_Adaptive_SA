# Family generation: one operator per parameter value

**Status: not started. Unlocked by family selection, which is now built.**

## The problem it solves

`ReorderShortSpanExactly` draws its span length uniformly from [3, 8]. Those spans do not cost the
same -- 6 permutations against 40,320 -- and they do not pay off the same either. One operator, one
weight, one `mean_call_time` **averaged over a 6000x cost range.** The scoring cannot tell "span 4 is
excellent value" from "span 8 is waste", so it prices the blend and acts on neither.

**Generate the family instead:** one fixed-span operator per size. Each prices independently, on its
own measured cost and its own measured payoff. The family aggregates them.

## It generalizes to any numeric parameter

Span length is one instance. `k` in the BestOfk operators, chain length, `NEIGHBOR_ROUTE_DRAWS` --
each is a constant chosen once and searched offline, and each could instead be a generated family
whose members compete.

**That is online parameter learning**, and it attacks the problem
[joint-parameter-search](joint-parameter-search.md) says is unaffordable. Offline tuning of these
values needs runs measured in days, per instance shape, and does not transfer. A generated family
learns the value DURING the solve, on the instance actually being solved.

## Why it needed family selection first

**Generation without family selection is harmful.** Splitting one operator into six multiplies that
operator's share of a flat draw by six -- the roster-composition bias, made worse deliberately.

Two properties of the built tree make generation safe:

- **MAX gives exact size-independence.** A family of six span sizes cannot out-earn a family of one
  by having more members, because only the best member counts.
- **Descent is O(depth x branching), not O(roster).** Six new members cost one extra comparison
  inside one family and nothing to any other family. Flat selection would have charged the whole
  roster on every proposal.

Both are in [design/operator_selection/family_selection.md](../design/operator_selection/family_selection.md).

## What it costs

Nothing is free. The tree removed the allocation penalty; two costs remain.

**Within-family dilution.** Six members share one family's budget, so each is drawn about a sixth as
often as a single operator would be. The family keeps its share; each member gets less of it.

**Learning cost.** Every member needs proposals before its weight means anything. Six members need
roughly six times the samples before the family knows which is best, and until then the family spends
real budget on members that will turn out useless. On a short run that may never converge -- the same
power problem as [joint-parameter-search](joint-parameter-search.md), moved inside the solve.

## The open question

Members differing by orders of magnitude in cost still have to be comparable to each other WITHIN a
family, and that comparison runs through `mean_cost` in the score. Whether the existing per-operator
cost division is enough, or whether generated members need their own normalization, is unmeasured.

That is the same question [operator-selection](operator-selection.md) asks about the roster as a
whole, appearing again one level down.

## Gate

Family selection is built, so the blocker is gone. Do not start until [ablations](ablations.md) has
priced `EXACT_REORDER_MAX_SPAN` -- generating six span sizes before knowing whether span size matters
is expensive guessing.

## Related

[operator-selection](operator-selection.md) is the selection hub.
