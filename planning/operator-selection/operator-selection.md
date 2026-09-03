# Operator selection

Hub for planned work on **which operator gets chosen, and how often**. Three related concerns. They
share mechanisms, which is why they share a page -- but they are separate questions and a fix for one
is not a fix for another.

- **A. Exploit-only against exploratory operators.** How much of the budget goes to operators that
  only take improving moves.
- **B. Expensive against cheap operators.** How an operator's cost should discount how often it runs.
- **C. Running operators the solver has no time for.** Not a balance question at all -- a question
  about whether a call is affordable before it is made.

Implemented mechanisms are documented in `design/`. This page records what is still open about them
and links out; it does not restate their design.

## The measurement driving this work

**n=500 capacity 400, 8 arms x 20 paired seeds, 180s** (`experiment_logs/ablations/2026-08-20_greedy_subtree_n500/`,
solver `8ddc893`). Dropping `ReorderShortSpanExactly` gained **24.59 at -4.8 sigma, winning 16 of 20
seeds.** The exact-only arms got monotonically worse as K rose, and K=10 lost every seed.

**Read it as a scoring failure, not an operator failure.** The operator took 74% of wall clock in an
earlier profiled run while producing 7.5 improving moves per second, against 755 for
`ReverseClosestPairTogether`. Its weight was the highest in the roster anyway. **The scoring could
not price a rare large improvement against a common cheap one, so it bought the expensive one.**

Benjamin's reading: the operator is not useful IN ITS CURRENT FORM UNDER THE CURRENT SCORING, and
should be useful at some span sizes once pricing is right. That is a hypothesis, and the ablation
does not test it -- every arm ran under the scoring being replaced.

## The rework these mechanisms converged on

[planning/implemented/scoring-rework.md](../implemented/scoring-rework.md) and
[planning/implemented/hierarchical-magnetism.md](../implemented/hierarchical-magnetism.md) are both
built now. Between them they resolved mechanisms 2, 3 and 4 below, though not as originally
planned -- see the implemented docs' own "what changed" notes. The entries here still record what
each mechanism was FOR.

## The formula every mechanism below acts on

**Superseded.** The formula that shipped is
[design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md),
not the one this section used to quote. Read that doc instead of this one.

**The table and the note below describe the PRE-REWORK formula.** Left as historical context for
the mechanism numbers used elsewhere in this file; not a description of shipped behaviour.

| term | mechanism, pre-rework |
|---|---|
| `explore_reward` floor | 2 -- keeps an accepted uphill move from scoring at or below zero |
| `improvement_exponent` | 3 -- currently a literal, not a solver parameter |
| the `mean_cost` divider | 1 would change how it decays; 4 multiplies a per-operator factor alongside it |
| `reaction_factor` in the fold | shares a tuning surface with 3 |

**A note on the floor, pre-rework.** `sign` makes a disimproving move score negative, and
`explore_reward` then raises it to a small positive value. So the floor is what lets an operator
paying off through
exploration earn any weight at all -- and it is also why `record_accept` still clamps with
`max(0, score)`, which the floor has made unreachable.

---

## A. Exploit-only against exploratory operators

| mechanism | status |
|---|---|
| `exploit_only` -- restricts an optimizing operator to improving moves | implemented, see [design](../../design/operator_selection/exploitation_governance.md) |
| `explore_reward` -- mechanism 2 below | implemented, ablation pending |
| discount random operators once the search is cold | idea |

**Discount random operators once cold.** Random moves are less useful for exploitation. Late in a run
the search is digging for scraps, and a random permutation almost never lands an improving move while
an optimized reorder still might. An operator's weight averages the whole run, so it carries
early-run value into a phase where that value is gone.

Only safe inside families that ALSO hold optimizing operators -- discounting a random operator with no
optimizing sibling removes the family's only move and leaves its share unspent. The family tree makes
that condition expressible.

"Cold" is not yet a question the solver can ask -- see [solver-progress-metric](solver-progress-metric.md).

**This pulls AGAINST `explore_reward`,** whose stated risk is too little exploration at plateau. Both
act at low temperature and in opposite directions. That tension is unresolved and is the clearest
example of why these mechanisms cannot be tuned one at a time.

---

## B. Expensive against cheap operators

### 1. Forget benefit, not average cost -- implemented

**IMPLEMENTED, though not as its own deliberate step.** It fell out of the weight/penalty split:
weight is a per-operator EMA that decays the benefit side every segment; the cost-ratio penalty
carries no EMA and never decays. See
[dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md). Original idea:
[forget-benefit-not-cost](../implemented/forget-benefit-not-cost.md).

### 2. `explore_reward` -- implemented, ablation pending

During the high-temperature phase this rewards exploration acceptance, attempting over time to solve
the same problem mechanism 1 attacks directly.

- **RISK:** no exploration at plateau. Expensive operators dominate the clock.
- **BENEFIT:** simple, one global ablation and tuning factor.
- Ablation in [ablations](../experiments/ablations.md). No separate planning file.

### 3. The improvement exponent should be an explicit solver parameter

**Small TODO: expose it.** It is currently a literal in the score computation.

It most directly sets how long the solver repeats a newly rewarding operator before forgetting it.
**Significant overlap with `reaction_factor`,** which sets how fast weights adapt at all -- the two
share one tuning surface and cannot be searched independently.

### 4. Manual dividers on expensive deterministic operators -- implemented

`exploit_selection_penalty_factor`, sized at solve start. See
[design](../../design/operator_selection/exploitation_governance.md).

- **RISK:** the values are non-adaptive magic numbers, or static functions of instance size. Each one
  adds an ablation factor.
- **Desire: replace with something more robust.** Mechanism 1 is the candidate for the PRICING half.
  For the wasted work itself, see
  [repeated-work-detection](repeated-work-detection.md) -- route version stamps that let a
  deterministic operator report NO-OP instead of re-deriving a rejected move.

### 5. Cap the cost instead of discounting the frequency -- implemented

`EXACT_REORDER_MAX_SPAN` bounds an operator's cost so it never needs a discount. The rule already
written down: **discount selection when cost scales with the problem; cap the scale when it does
not.** See [design](../../design/span_reorder/reorder_operators.md).

Only available when cost has a bound that does not depend on instance size.

### 6. The family tree and its floors -- implemented

Structural rather than tuned: descent bounds how much of the roster any one operator can capture,
with no factor to set. See [design](../../design/operator_selection/family_selection.md).

---

## C. Running operators the solver has no time for

Weighting learns from measured payoff, so it cannot price an operator it has never run. On a large
instance with a small budget, one expensive operator can consume the budget in a few calls and the
run ends having done almost nothing. The weighting never gets the samples to demote it, because
demoting it requires running it.

### Current plan: [budget-gated-selection](budget-gated-selection.md)

Gate selection on the remaining budget. Start cheap, admit expensive operators as the run
demonstrates it can afford them, and contract again near the end.

### Idea stub: a per-operator activation gate

Give each expensive operator an optional **activation-gate parameter**. This generalizes the plan
above rather than competing with it.

- An **inactive** operator gets a fixed adjusted weight of 0 at each update, and its internal weight
  is reset to `weight_floor`.
- Inactive operators are **excluded** from the computed shifted geometric mean.
- On **activation**, its weight returns to the shifted geometric mean measured at iteration start.

The gate condition is TBD, from some combination of iteration count, estimated computational cost,
measured compute time, and similar.

---

## Every discount here is a RATE, not an exclusion

No mechanism above can starve an operator permanently. Three things running underneath guarantee that
any operator resurfaces once the search stalls:

- **Unproposed operators drift back up.** In `update_weights`, an operator with no proposals in a
  segment is pulled toward the roster's geometric mean rather than left to decay.
- **Total collapse reheats.** When the largest weight falls to 1e-10, every weight is multiplied by
  1e5.
- **A family cannot fall below its floor.** Root families hold a guaranteed share of the draw whatever
  their measured weight says.

And at a plateau nothing scores, so the EMA carries every weight toward uniform on its own. **The
operators discounted hardest during productive search are the ones that come back when it stops** --
which is the moment an unusual move is most likely to be the one that helps.

This bounds the risk of everything above. A discount that turns out to be wrong costs throughput
while the search is working, and corrects itself when it is not.

**The activation gate in section C is the one exception**, since it sets adjusted weight to 0
outright. Whether a gated operator should still resurface at plateau is part of what its gate
condition has to decide.

## References

- [planning/implemented/scoring-rework.md](../implemented/scoring-rework.md) -- resolved mechanisms 2, 3 and 4
  below, though not as originally planned.
- [planning/implemented/hierarchical-magnetism.md](../implemented/hierarchical-magnetism.md) -- supplies the
  sibling-local machinery the rework reused.
- [design/operator_selection/dynamic_penalty.md](../../design/operator_selection/dynamic_penalty.md) --
  the formula that shipped in place of the pre-rework one this file used to describe.
- [design/operator_selection/exploitation_governance.md](../../design/operator_selection/exploitation_governance.md)
  -- `exploit_only` and the manual dividers mechanisms 1 and 4 discuss.
- [planning/implemented/forget-benefit-not-cost.md](../implemented/forget-benefit-not-cost.md) -- mechanism 1's
  original idea, incorporated into the shipped weight/penalty split.
- [planning/experiments/ablations.md](../experiments/ablations.md) -- measurements that would settle several mechanisms here, including
  `explore_reward`.
- [repeated-work-detection.md](repeated-work-detection.md) -- route version stamps that would replace
  mechanism 4's wasted-work half.
- [design/span_reorder/reorder_operators.md](../../design/span_reorder/reorder_operators.md) --
  `EXACT_REORDER_MAX_SPAN`, mechanism 5's cap.
- [design/operator_selection/family_selection.md](../../design/operator_selection/family_selection.md)
  -- the family tree and floors, mechanism 6.
- [budget-gated-selection.md](budget-gated-selection.md) -- the current plan for section C.
- [solver-progress-metric.md](solver-progress-metric.md) -- "how cold is the search," needed by
  section A and any phase-gated mechanism.

## Links to here

- [planning/implemented/forget-benefit-not-cost.md](../implemented/forget-benefit-not-cost.md) -- cites this as
  the hub for mechanisms 3 and 4.
- [planning/README.md](../README.md) -- lists this as the HUB entry in the roadmap table.
- [design/operator_selection/README.md](../../design/operator_selection/README.md) -- design implementation of this plan
- [design/operator_selection/family_selection.md](../../design/operator_selection/family_selection.md) -- design implementation of selection mechanism
- [design/operator_selection/share_floors.md](../../design/operator_selection/share_floors.md)
- [planning/experiments/ablations.md](../experiments/ablations.md)
- [family-generation.md](family-generation.md)
- [repeated-work-detection.md](repeated-work-detection.md)
- [solver-progress-metric.md](solver-progress-metric.md)
