# Guaranteed share per family

**Code:** `SimAnn_VRP_Solver.py` -- `FAMILY_FLOOR`, `apply_share_floors`

Each root family is guaranteed a minimum share of the draw, whatever its measured weight says.
Called once per segment from `refresh_family_tree`, over the root's children only.

## Why a floor, and why only at the root

Adaptive weighting decides allocation from measured payoff. That is right when the measurement is
trustworthy and wrong when a family is starved before it can demonstrate anything.

A floor states that the prior is more trustworthy than the measurement, for a bounded fraction of the
budget. Intra-route and inter-route work carry the solve, so most of a run belongs to them.

| family | floor |
|---|---|
| `INTRA_ROUTE` | 0.25 |
| `INTER_ROUTE` | 0.25 |
| `FULL_ROUTE` | 0.02 |
| `CHANGE_NUM_ROUTES` | 0.01 |
| `CHANGE_END_DEPOT` | 0.01 |

Floors sum to 0.54, leaving 0.46 for weighting to allocate. **Below the root, weight decides alone.**
A weak operator inside a strong family gets nothing, which is what the floors are not for.

`FULL_ROUTE` sits above the other two small families deliberately: whole-route reassignment is more
generally useful than splitting and combining, and it becomes far more so once vehicle distances are
gated. See [planning/vehicle-time-limits.md](../../planning/vehicle-time-limits.md).

## Proportional, not equal-absolute

Clamping a family to its floor takes share from the others. Two rules could do that, and they give
different answers.

**Equal-absolute** drains every surplus family by the same amount, lowest surplus dropping out first.
It is the minimum-Euclidean projection. **Proportional** reduces each surplus family by the same
factor, so ratios between unclamped families survive unchanged.

Proportional is used. Weights are EMAs spanning orders of magnitude, so subtracting a constant
distorts small families far harder than large ones, and Euclidean distance is not the metric these
weights live in. **The ratio between two unclamped families is what their relative weight MEANS**, so
the rule that preserves it is the correct one.

The difference is not cosmetic. Two families at 0.40 and 0.10 donating 0.06 between them come out at
4.00:1 under proportional and 13.00:1 under equal-absolute.

## The clamped set is unique, so scan order does not matter

Clamping is iterative: taking share from the pool can pull a second family under its own floor, which
pulls a third, and so on.

The naive repeat-until-stable loop is correct because **clamping one family only ever lowers the
threshold for the others.** Clamping `j` changes family `i`'s test from `F*w_i < L_i*P` to
`(F-L_j)*w_i < L_i*(P-w_j)`, and the second fires whenever the first does exactly when
`F*w_j < P*L_j` -- which is the condition that clamped `j`. So the clamped set is a fixed point
reached from any scan order.

## Why the naive loop and not the sorted one

Sorting by `w/L` makes the clamped set a prefix and finds it in one pass, O(n log n) against the
loop's O(n^2).

**n is the number of ROOT families -- five.** The loop is at most 25 comparisons, run once per
segment, inside a function that already takes a logarithm per operator. The sorted version would
allocate several sequences of length five to save microseconds per second, and it carries more places
to be wrong.

Revisit only if root families ever number in the dozens, which the tree exists to prevent.

## One precondition removes every degenerate branch

`sum(floors) < 1`, asserted where the table is defined rather than per call.

**That precondition alone guarantees the pool is never empty at the end.** Suppose every family
clamps, and take the last one, `k`. At that moment the pool holds only `w_k`, so its test reads
`free_share < L_k`. Substituting `free_share = 1 - sum of the other floors` gives `1 < sum(floors)`,
contradicting the precondition. So at least one family always stays unclamped, and the final division
needs no guard.

Total weight collapse is the only other route to an empty pool, and `update_weights` already prevents
it: `reheat = 1e5` fires when the largest weight falls to 1e-10.

## Verification

Tested against an oracle twin that brute-forces all `2^n` clamp subsets and returns the feasible one.
Feasibility requires that every unclamped family clears its floor AND every clamped one genuinely
needed clamping, which makes the answer unique and the twin a real check rather than a second
opinion.

Both rejected implementations fail the suite: a single-pass version violates a floor on the cascade
case, and equal-absolute moves the preserved ratio from 4.00 to 13.00.

The cascade case in the tests was found by search. Hand-built examples all clamp everything on the
first pass, so they never exercise the loop -- which is worth knowing before trusting an example
someone wrote by eye.

- [family_selection.md](family_selection.md) -- the tree these floors sit on top of.
- [planning/operator-selection.md](../../planning/operator-selection.md) -- every discount in the
  selection machinery is a rate rather than an exclusion, and the floors are one of three mechanisms
  that guarantee it.

## References

- [planning/operator-selection.md](../../planning/operator-selection.md)
- [family_selection.md](family_selection.md)
- [planning/vehicle-time-limits.md](../../planning/vehicle-time-limits.md)

## Links to here

- [design/README.md](../README.md) -- design folder index
- [README.md](README.md) -- reading guide for operator selection folder
- [family_selection.md](family_selection.md) -- projection mechanism for this family tree
