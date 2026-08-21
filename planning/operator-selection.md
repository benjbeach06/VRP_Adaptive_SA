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

**n=500 capacity 400, 8 arms x 20 paired seeds, 180s** (`experiment_logs/ablate_greedy_n500.json`,
solver `8ddc893`). Dropping `ReorderShortSpanExactly` gained **24.59 at -4.8 sigma, winning 16 of 20
seeds.** The exact-only arms got monotonically worse as K rose, and K=10 lost every seed.

**Read it as a scoring failure, not an operator failure.** The operator took 74% of wall clock in an
earlier profiled run while producing 7.5 improving moves per second, against 755 for
`ReverseClosestPairTogether`. Its weight was the highest in the roster anyway. **The scoring could
not price a rare large improvement against a common cheap one, so it bought the expensive one.**

Benjamin's reading: the operator is not useful IN ITS CURRENT FORM UNDER THE CURRENT SCORING, and
should be useful at some span sizes once pricing is right. That is a hypothesis, and the ablation
does not test it -- every arm ran under the scoring being replaced.

## The formula every mechanism below acts on

Ported for reference from `Operator.update_stats_for_accept`. **Only ACCEPTED moves are scored** --
a rejection just increments the proposal count.

```python
mean_cost = self.mean_call_time if self.weight_by_time else 1.0
improvement_exponent = 1.5
sign = -1 if improvement < 0 else 1
score = max(explore_reward, sign * abs(improvement) ** improvement_exponent) / max(mean_cost, 1e-9)
```

Scores accumulate into `score_sum`, and `update_weights` folds the segment average into the weight:

```python
average_score = score_sum / num_proposals    # PROPOSALS, so acceptance rate is priced in
weight = (1 - reaction_factor) * weight + reaction_factor * average_score
```

Where each mechanism acts:

| term | mechanism |
|---|---|
| `explore_reward` floor | 2 -- keeps an accepted uphill move from scoring at or below zero |
| `improvement_exponent` | 3 -- currently a literal, not a solver parameter |
| the `mean_cost` divider | 1 would change how it decays; 4 multiplies a per-operator factor alongside it |
| `reaction_factor` in the fold | shares a tuning surface with 3 |

**A note on the floor.** `sign` makes a disimproving move score negative, and `explore_reward` then
raises it to a small positive value. So the floor is what lets an operator paying off through
exploration earn any weight at all -- and it is also why `record_accept` still clamps with
`max(0, score)`, which the floor has made unreachable.

---

## A. Exploit-only against exploratory operators

| mechanism | status |
|---|---|
| `exploit_only` -- restricts an optimizing operator to improving moves | implemented, see [design](../design/operator_selection/exploitation_governance.md) |
| `explore_reward` -- mechanism 2 below | implemented, ablation pending |
| discount random operators once the search is cold | idea |

**Discount random operators once cold.** Random moves are less useful for exploitation. Late in a run
the search is digging for scraps, and a random permutation almost never lands an improving move while
an optimized reorder still might. An operator's weight averages the whole run, so it carries
early-run value into a phase where that value is gone.

Only safe inside families that ALSO hold optimizing operators -- discounting a random operator with no
optimizing sibling removes the family's only move and leaves its share unspent. The family tree makes
that condition expressible.

**This pulls AGAINST `explore_reward`,** whose stated risk is too little exploration at plateau. Both
act at low temperature and in opposite directions. That tension is unresolved and is the clearest
example of why these mechanisms cannot be tuned one at a time.

---

## B. Expensive against cheap operators

### 1. Forget benefit, not average cost

**Own file: [forget-benefit-not-cost](forget-benefit-not-cost.md).** Benefit decays over time; cost
does not. Expensive operators then always run less, even at plateau.

- **RISK:** expensive operators do not get enough share. May need `f(cost)` instead of `cost` as the
  divider; `f` is TBD.
- **BENEFIT:** one global ablation and tuning factor, and it adapts on its own.
- Overlaps mechanism 3.

### 2. `explore_reward` -- implemented, ablation pending

During the high-temperature phase this rewards exploration acceptance, attempting over time to solve
the same problem mechanism 1 attacks directly.

- **RISK:** no exploration at plateau. Expensive operators dominate the clock.
- **BENEFIT:** simple, one global ablation and tuning factor.
- Ablation in [ablations](ablations.md). No separate planning file.

### 3. The improvement exponent should be an explicit solver parameter

**Small TODO: expose it.** It is currently a literal in the score computation.

It most directly sets how long the solver repeats a newly rewarding operator before forgetting it.
**Significant overlap with `reaction_factor`,** which sets how fast weights adapt at all -- the two
share one tuning surface and cannot be searched independently.

### 4. Manual dividers on expensive deterministic operators -- implemented

`exploit_selection_penalty_factor`, sized at solve start. See
[design](../design/operator_selection/exploitation_governance.md).

- **RISK:** the values are non-adaptive magic numbers, or static functions of instance size. Each one
  adds an ablation factor.
- **Desire: replace with something more robust.** Mechanism 1 is the candidate for the PRICING half.
  For the wasted work itself, see
  [repeated-work-detection](repeated-work-detection.md) -- route version stamps that let a
  deterministic operator report NO-OP instead of re-deriving a rejected move.

### 5. Cap the cost instead of discounting the frequency -- implemented

`EXACT_REORDER_MAX_SPAN` bounds an operator's cost so it never needs a discount. The rule already
written down: **discount selection when cost scales with the problem; cap the scale when it does
not.** See [design](../design/span_reorder/reorder_operators.md).

Only available when cost has a bound that does not depend on instance size.

### 6. The family tree and its floors -- implemented

Structural rather than tuned: descent bounds how much of the roster any one operator can capture,
with no factor to set. See [design](../design/operator_selection/family_selection.md).

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

## Related

- [ablations](ablations.md) -- measurements that would settle several of the above.
- [solver-progress-metric](solver-progress-metric.md) -- "how cold is the search" is needed by A, and
  by any gate keyed on run phase.
