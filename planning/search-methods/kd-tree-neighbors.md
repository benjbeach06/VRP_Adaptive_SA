# k-d tree for the neighbor tables

**Status:** deferred. Not needed at current instance sizes.

## Problem

`FullSolution.build_neighbor_tables` is O(n^2). It computes every pairwise distance, then takes the
k smallest per row with `np.argpartition`.

## Measured

| n | build time |
|---|---|
| 500 | 0.011 s |
| 1000 | 0.037 s |
| 5000 | 0.607 s |

It runs once per solution. For comparison, `make_initial_solution` costs 7.8 s at n=5000, so the
table is currently about 13x cheaper than the construction step it accelerates.

## Why not now

The quadratic is at C speed inside numpy, chunked so peak memory stays near 20 MB rather than the
200 MB a full n=5000 matrix would take. Replacing it changes the complexity class but not the
wall time anyone notices below roughly 50k customers.

An incremental sorted-top-k insert in Python is strictly worse, not better: same O(n^2 log k) work
with the interpreter's constant factor on top, which is around 100x numpy's.

## Options, when it is time

**`scipy.spatial.cKDTree`** — `query(points, k=21)` in roughly O(n log n). The obvious first choice,
and scipy 1.18 is already installed and working on this Python 3.14 environment. Smoke-tested at
n=2000, k=20: **0.0041 s** including tree construction, against 0.037 s for the current numpy path
at n=1000. So the crossover is already below current instance sizes and this is mostly a matter of
wiring it in behind the same `nearest_indices` signature.

The reason it is still not done is that the table is built ONCE per solution and costs 0.6 s at the
largest size anyone runs here. Swapping it in is a correctness risk against a bit-identical
construction guarantee (see the tie-breaking rules in `nearest_indices`) for a saving nothing
currently notices.

**Grid bucketing** — customer coordinates in this generator are integers on a 0-100 grid, so a
uniform cell decomposition with expanding-ring search is straightforward and adds no dependency.
Degrades if the instance clusters heavily, which a real-world instance would.

## Gate

Instance sizes reach roughly 50k customers, or the table build shows up in a profile at all. At
n=5000 it is 0.6 s of a run measured in minutes.

**If it is swapped in, the tie rule must survive.** `nearest_indices` orders ties by index, which is
what keeps `make_initial_solution` bit-identical to the linear scan it replaced. `cKDTree.query`
makes no such guarantee, so a k-d tree path needs its own tie normalization and the construction
signature test in `tools/` re-run before it is trusted.

## References

*(none yet)*

## Links to here

- [planning/README.md](../README.md)
