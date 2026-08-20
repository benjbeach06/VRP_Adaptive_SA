# Forget benefit, not average cost

**Status: idea. Not started.** Benjamin's, 2026-08-20.

## The shape

An operator's score divides measured benefit by measured cost. Both are currently averaged the same
way, so both fade together.

**Decay the benefit and keep the cost.** An operator's remembered cost stays; its remembered payoff
decays. Expensive operators then always run less than cheap ones, **including at plateau**, where
today every weight converges toward uniform and cost stops mattering at all.

## Why it is attractive

**One factor.** The whole expensive-against-cheap balance collapses to a single global number that
can be ablated and tuned once, instead of a per-operator divider set by hand for every expensive
operator added.

**It adapts.** Cost is measured on the instance actually being solved, so an operator that is
expensive at capacity 400 and cheap at capacity 25 is priced correctly at both without anyone
deciding in advance.

**It would replace the manual dividers** -- mechanism 4 in
[operator-selection](operator-selection.md) -- which are magic numbers today and add an ablation
factor each.

## The risk

**Expensive operators may not get enough share.** Permanent cost memory is a permanent penalty, and
an expensive operator that is genuinely the right move late in a run would be held down exactly when
it is wanted.

The likely fix is to divide by `f(cost)` rather than by `cost`, compressing the range so that a
hundredfold cost difference is not a hundredfold penalty. **`f` is TBD** and is the real design work
here -- a square root, a logarithm, and a cap are all plausible and they behave very differently at
the extremes.

## Overlap to resolve first

**The improvement exponent.** It sets how long a newly rewarding operator keeps being repeated before
it is forgotten, so it is already a decay-rate control on the benefit side. Adding a second one
without exposing the first means tuning two coupled knobs, one of which is a literal in the source.
Expose it first -- mechanism 3 in [operator-selection](operator-selection.md).

**`reaction_factor`** sets how fast weights adapt at all, and shares that same surface.

## Gate

None on correctness -- this changes allocation, not answers.

Do not start until the improvement exponent is an explicit parameter, and until
[ablations](ablations.md) can say whether `explore_reward` buys anything. Both attack this problem
from different directions, and measuring a third mechanism against two unmeasured ones produces a
number that means nothing.

## Related

[operator-selection](operator-selection.md) is the hub. The built mechanism this would replace is in
[design/operator_selection/exploitation_governance.md](../design/operator_selection/exploitation_governance.md).
