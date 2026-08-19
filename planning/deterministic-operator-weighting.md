# Weighting for DETERMINISTIC operators

**Status: not started. Exposed by the farthest-insertion operators.**

## The problem

Adaptive weighting treats every proposal as an independent draw. That is true for a random
operator: propose `RandomCustomerSwap` twice on the same route and you get two different moves.

It is **false** for a deterministic one. `ReorderRandomRouteByFarthestInsertion` computes a pure
function of the route it is given. Proposing it twice on an unchanged route returns the SAME
permutation, which was already rejected. The second call is guaranteed waste, and it is expensive
waste -- these are the O(k^2) operators.

Weighting cannot see this. It measures cost per accepted move, so a deterministic operator that
keeps re-proposing rejected moves simply looks bad, slowly, after paying for every repeat.

## How much of the roster this touches

| operator | deterministic given the route? |
|---|---|
| `ReorderRandomRouteByFarthestInsertion` | **fully** -- route in, one answer out |
| `ReorderLongRouteByFarthestInsertion` | **fully**, and it re-draws the same long routes most often |
| `ReorderSpanByFarthestInsertion` | partly -- the span is random, the rebuild is not |

The weighted variant is the worst case. It deliberately keeps selecting the longest routes, so it
repeats itself more than uniform selection would.

## Options, none chosen

- **Dirty flag per route.** A deterministic operator skips a route unchanged since its last
  proposal on it. Exact, and needs a per-route version counter the operator can read.
- **Discount the weight by operand-space coverage.** A deterministic operator over R routes has
  only R distinct proposals. Once it has tried most of them, its expected value collapses. This
  generalizes past routes to any operator with a small operand space.
- **Cooldown.** Cheapest to build, crudest: a deterministic operator cannot be proposed again for N
  segments. Does not distinguish a changed route from an unchanged one.

The dirty flag is the honest fix. The coverage discount is the interesting one, because it states
the underlying quantity -- **how much of what this operator CAN propose has it already proposed** --
which the current scoring has no representation of at all.

## PREFERRED: a weight multiplier

**Reduce the frequency rather than prevent the repeat.** A deterministic operator carries a
multiplier applied when its weight is evaluated -- on the order of `1e-2`.

Random activation is fine. The goal is not to make a repeat impossible; it is to stop paying for one
on most draws. A deterministic operator that fires a hundredth as often still gets its chance
whenever the route HAS changed, and the wasted repeats fall by the same factor.

This is cheaper than the alternatives and needs no per-route state:

- no version counter on `Route`
- no operand-space bookkeeping
- no interaction with `commit`/`revert`

**Implementation.** Selection walks cumulative weights, so applying the multiplier per draw would
cost a multiply per operator per proposal. A mirrored `adj_operator_weights` array avoids that:
maintain it alongside `weight`, and refresh it in `update_weights`, which already touches every
operator once per segment. Selection then reads the adjusted array directly and costs nothing extra.

**Design TBD -- the multiplier's source is not decided.** Three candidates:

| source | note |
|---|---|
| **fixed constant** | simplest. One number, tuned once or hand-set. Cannot adapt to instance shape. |
| **computed at solve start** | scale with route count -- with R routes there are only R distinct proposals, so the right discount plausibly depends on R. Static within a run. |
| **adaptive** | derive it from observed repeat rate. Most correct, most machinery, and it re-introduces the coverage question above. |

Start with fixed. It is one constant and it makes the effect measurable, which decides whether the
other two are worth building.

## Note on the interaction with reheats

A route changes constantly early in a run, so repetition is rare then. It becomes common exactly
when the search is stuck, which is when these operators are most wanted. So the defect bites hardest
at the moment the operator is most valuable.

## Gate

None on correctness -- this wastes time, it does not produce wrong answers. Do it before trusting
any ablation of the deterministic operators, since their measured value is currently depressed by
repeat proposals they should never have made.

Related: [operator-scoring](operator-scoring.md), [budget-gated-selection](budget-gated-selection.md).
Design context: [design/span_reorder/reorder_operators.md](../design/span_reorder/reorder_operators.md).
