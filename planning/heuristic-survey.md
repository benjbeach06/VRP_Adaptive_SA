# Survey the construction and reorder heuristics we never looked at

**Status: not started. Cheap, and it gates any future construction or reorder operator.**

## Why

`farthest_insertion_order` was chosen from a shortlist of four: nearest neighbour, farthest
insertion, greedy edge, Christofides. That shortlist came from one search, not from a survey.

The [DIMACS TSP Challenge results](https://archive.dimacs.rutgers.edu/Challenges/TSP/results.html)
list many more, with normalized result tables per algorithm -- local search families, tour merging,
and hybrid construction schemes among them.

So the current choice is defensible but not informed. It may be right. Nobody has checked.

## Two questions to take to it

1. **What else sits in the cheap-and-accurate corner?** Farthest insertion is the only heuristic
   known here to be both under 15% excess and O(n^2). That claim is about six algorithms, not about
   the field.
2. **Does anything adapt to a FIXED-ENDPOINT path?** This solver reorders a span between two nodes
   that must stay put. Most reported results are for the TOUR problem. An algorithm that is strong
   on tours is not automatically strong here, and one that is weak on tours might be strong.

## Also worth extracting

The exact per-algorithm percentages. The design doc currently cites only the DIMACS ranking,
because two secondary summaries disagreed with each other -- one put Greedy at ~14%, which the
DIMACS grouping contradicts. The primary tables settle it.

## Gate

None. Do it before writing another construction or reorder operator, not after.

Design context: [design/span_reorder/farthest_insertion_order.md](../design/span_reorder/farthest_insertion_order.md).
