# Test suite

**Provenance:** this suite was written and maintained independently by Claude (Anthropic) while
providing development assistance on this project. It is not hand-written by the repository author.

Two design decisions in it came from the repository author, with the implementation by Claude:
routing all randomness through a single **owned, seeded generator** instead of the process-wide
`random` module — which is what actually made solves reproducible — and requiring every test to
fix its own seed, so the suite holds under arbitrary ordering and partial runs. (That generator
was first `np.random.default_rng`; it later became a `random.Random` instance, because numpy's
Generator costs 6-8x more per scalar draw and the solver only ever draws scalars. The design
point — one owned stream, isolated from anything else in the process — is what mattered.)

## Running

From the repository root:

```
python -m unittest discover -s tests
```

Individual modules or classes (run from inside `tests/`, so sibling modules import cleanly):

```
python -m unittest test_solver_end_to_end.SolverDeterminism
```

The exhaustive operator sweeps are reduced by default so the suite finishes in ~10 seconds. For
the full sweep (tens of thousands of operand combinations):

```
VRP_FULL_MATRIX=1 python -m unittest discover -s tests
```

Every test reseeds all random streams in `setUp` (see `SeededTestCase`), so cases are independent
of execution order, of how many ran before them, and of whether the whole suite or a single test
is running.

## Why these tests look the way they do

The solver maintains a lot of state incrementally — depot usage counters, per-route loads, a
doubly-linked visit list, a per-vehicle route chain, and a running objective. Crucially, almost
every cached quantity has a **recompute-from-scratch counterpart**: `depot_num_uses` vs
`depot_usage_breakdown()`, `current_load` vs `recompute_current_load()`, the running
`curr_objective` vs `solution_cost()`. That makes oracle-style testing unusually cheap, and it is
how every bug encoded here was originally found.

The dominant defect shape in this codebase is **correct abstraction, wrong wiring**: the right
helper existing a few lines above the call site that used the wrong one. Those are invisible to
code review and to any test that only checks end results, which is why the contract tests compare
*term by term* and assert an *exact* revert round-trip rather than just a final cost.

## Layout

| File | What it covers |
|---|---|
| `_harness.py` | Instance builders, the invariant oracles, solution fingerprinting, the deterministic clock, and `SeededTestCase`. |
| `test_core_model_regressions.py` | One test per historical bug. Each docstring states the defect, so a reintroduction fails with an explanation rather than a bare assertion. |
| `test_operator_contracts.py` | The four properties every operator must satisfy, over exhaustive operand matrices plus randomised operands drawn from the real selection logic. |
| `test_solver_end_to_end.py` | Full solves at `debug_level=3` (the solver verifying itself as it runs), objective-drift checks, and reproducibility. |

## The operator contract

Every `OperatorBL` must satisfy four properties, each catching a different bug class:

1. **`evaluate()` is pure** — an operator that mutates while pricing corrupts the search and
   breaks best-of-k selection outright.
2. **Deltas match ground truth, term by term** — "improvement off by 27.78" is a search;
   "`travel_distance` wrong, other four exact" is a location.
3. **Invariants hold after apply** — cached state must still agree with a fresh recomputation.
4. **`revert()` restores exactly** — structural *and* cost identity. This is the only property
   that catches revert-only defects, which never manifest on the accepted-move path and so are
   invisible to every other check.

## Notes for future work

`debug_level=3` makes the solver check itself during a run: accepted moves are verified against a
recomputed cost, and **rejected** moves are force-applied, checked, reverted and re-checked. The
rejected-move round-trip is the valuable half — it is what caught `CombineRoutes` failing to
restore a route's end depot.

Wall-clock termination makes a run depend on machine speed and on any instrumentation added while
debugging, so a bug reproducible in a clean run can vanish the moment it is measured. The
`deterministic_clock` helper substitutes a fixed tick per call, making a run a pure function of
its seed. Combined with the solver's single shared generator (`solver_rng` in the core model),
results are reproducible within a process, across processes, and across `PYTHONHASHSEED` values.
