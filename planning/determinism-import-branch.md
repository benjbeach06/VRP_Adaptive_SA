# Determinism by import-time branch

**Status: not started. Small, isolated. Operator selection is the test case.**

## The rule this applies

Determinism is for correctness, never performance. It should cost nominally. Where it costs more
than nominal, it becomes optional -- and the branch is taken **once at import**, never per call.

Python has no preprocessor, but module import runs once:

```python
if os.environ.get("VRP_DETERMINISTIC"):
    def _pick(...): ...      # deterministic
else:
    def _pick(...): ...      # fast
```

A module constant checked inside the function is NOT the same thing. CPython does not fold module
globals, so it costs a lookup and a branch on every call.

`if __debug__:` with `-O` is true build-time elimination, but `-O` also strips every `assert`, and
asserts carry the oracle checks here. It would disable verification at the same time.

## The test case: operator selection

`set_deterministic_weighting` sets `weight_by_time = not deterministic` on every operator. Then
`update_stats_for_accept` reads that attribute on every accepted move to decide whether mean cost is
measured or forced to 1.

That is a per-call attribute read on a hot path, for a decision that never changes during a run and
exists only for determinism. It is exactly the shape the import-time branch is for.

## Why this is a good first case

- The decision is determinism-only. No production behaviour depends on it.
- It is one attribute and two call sites.
- The test suite already exercises both paths, so a regression shows immediately.
- If the pattern is wrong, the blast radius is small enough to back out.

## Second case: route selection under determinism

`choose_random_nonempty_route` sets empty routes aside with a swap-remove and re-adds them at the
end, so `all_routes` comes back permuted. **That is a design choice, not a defect.** Its original
callers only need a non-empty route, and paying `undo_remove` bookkeeping for an ordering they never
read would tax the common path.

`choose_random_nonempty_route_ordered` exists for callers that DO need order preserved -- currently
the operators whose revert is checked for an exact structural round-trip.

**Under determinism, every caller needs the ordered version.** Operands are drawn positionally, so a
permuted RouteSet changes which route a later draw returns, and a run stops being a pure function of
its seed.

So this is the same import-time branch, applied to a second site: bind `choose_random_nonempty_route`
to the ordered implementation when the deterministic build is selected, and to the fast one
otherwise. Callers keep one name and pay nothing in the fast build.

## Default deterministic

When the flag exists, the DETERMINISTIC build is the default and the flag buys speed. A
default-fast build makes every bug report unreproducible, which costs more than it saves.

## Gate

None. Do it when there is an hour to verify it properly.

Memory: `feedback-determinism-costs-nothing`.

## References

*(none yet)*

## Links to here

- [README.md](README.md)
- [family-generation.md](family-generation.md)
