# `farthest_insertion_order`

**Code:** `SimAnn_VRP_Operators.py`
**Used by:** [reorder_operators.md](reorder_operators.md)

## What it does

Orders a set of points between two **fixed** endpoints. Returns indices into the input.

This is the Hamiltonian path problem with both ends fixed, solved approximately.

## The algorithm

Start with the path `[left, right]`. Then repeat until every point is placed:

1. Take the unplaced point **farthest** from the current partial path.
2. Insert it where it costs least: `min` over consecutive `a,b` of `d(a,v) + d(v,b) - d(a,b)`.

## Why farthest insertion, and not the alternatives

The first version was nearest-neighbour, matching construction. It has a known failure: committing
to the locally cheapest step strands outliers, and the path pays for them at the end with one long
jump.

Farthest-first places the points most likely to be stranded while the path is still short and
flexible. Cheapest-detour placement considers **both** neighbours of the gap, so the path closes
from either end instead of only extending forward.

The DIMACS TSP Challenge groups construction heuristics on random uniform Euclidean instances by
excess over the Held-Karp lower bound:

| excess | heuristics | cost |
|---|---|---|
| **under 15%** | **Farthest Insertion**, Christofides | O(n^2) / O(n^3) |
| over 15% | Nearest Neighbour, Greedy, Nearest Insertion, Cheapest Insertion | O(n^2) / O(n^2 log n) |

**Farthest insertion is the only heuristic that is both under 15% and O(n^2).** Christofides is the
other one under 15%, and its cube is the perfect matching -- at n=70 that alone is ~343k operations. Greedy edge additionally needs an edge
sort and union-find, for a bucket it does not even beat farthest insertion into.

So the choice is not a close trade. It is the only option in the cheap-and-accurate corner.

**Citation:** [DIMACS TSP Challenge results](https://archive.dimacs.rutgers.edu/Challenges/TSP/results.html).
The underlying study is Johnson & McGeoch, *The Traveling Salesman Problem: A Case Study in Local
Optimization*.

**Not verified:** exact percentages. Secondary summaries give roughly 25% for nearest neighbour and
1.16x optimal for farthest insertion, but one of those summaries put Greedy at ~14%, which the
DIMACS grouping contradicts. Only the ranking above is used here. The per-algorithm figures sit in
linked DIMACS data tables that have not been opened.

**The page lists many more algorithms than the six above** -- whole families this design never
considered. The choice here was made from a shortlist, not from a survey. Surveying them is
[planning/search-methods/heuristic-survey.md](../../planning/search-methods/heuristic-survey.md).

## References

- [reorder_operators.md](reorder_operators.md)
- [planning/search-methods/heuristic-survey.md](../../planning/search-methods/heuristic-survey.md)

## Links to here

- [design/README.md](../README.md) -- design folder index
- [farthest_insertion_ops.md](farthest_insertion_ops.md)
- [planning/problem-model/asymmetric-distances.md](../../planning/problem-model/asymmetric-distances.md)
- [planning/search-methods/heuristic-survey.md](../../planning/search-methods/heuristic-survey.md)
