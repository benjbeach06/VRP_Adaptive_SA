# Family generation: one operator per parameter value

**Status: not started. Unlocked by family selection, which is now built.**

## The problem it solves

`ReorderShortSpanExactly` draws its span length uniformly from [3, 8]. Those spans do not cost the
same -- 6 permutations against 40,320 -- and they do not pay off the same either. One operator, one
weight, one `mean_call_time` **averaged over a 6000x cost range.** The scoring cannot tell "span 4 is
excellent value" from "span 8 is waste", so it prices the blend and acts on neither.

**Generate the family instead:** one fixed-span operator per size. Each prices independently, on its
own measured cost and its own measured payoff. The family aggregates them.

## The worked case: K in `ReorderShortSpanExactly`

**Benjamin's, 2026-08-20.** Both the cost and the power of exact reordering are factorial in K, and
the choice of K makes a large empirical difference to performance. That combination is what makes it
the right first target: a parameter whose value matters a lot, over a range the solver cannot afford
to explore blindly.

**Generate one operator per K.** Each carries its own weight and its own measured cost, so the
solver learns which K is worth its time on the instance in front of it rather than being handed one
number chosen offline.

**Start with small K and expand as the run goes.** A generated set should not open with every K
active. Small K is cheap and always affordable; large K is where the factorial cost lives and should
have to earn admission.

Two ways to do that, and the choice is open:

- **Dynamic generation.** Add the next K up once the current largest is paying off. The set grows
  only as far as the instance justifies.
- **A fixed generated set behind strict activation gating.** All K values exist from the start, but
  the expensive ones stay inactive until a gate opens them. That is the activation-gate stub in
  [operator-selection](operator-selection.md), section C, and this is its first real consumer.

The second is easier to reason about, because the family tree is static and only the gate moves.

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
