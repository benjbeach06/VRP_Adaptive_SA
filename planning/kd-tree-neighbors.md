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

**`scipy.spatial.cKDTree`** — `query(points, k=21)` in roughly O(n log n). One dependency, minutes
of work, and the obvious first choice.

**Grid bucketing** — customer coordinates in this generator are integers on a 0-100 grid, so a
uniform cell decomposition with expanding-ring search is straightforward and adds no dependency.
Degrades if the instance clusters heavily, which a real-world instance would.

## Gate

Instance sizes reach roughly 50k customers, or the table build shows up in a profile at all. At
n=5000 it is 0.6 s of a run measured in minutes.
