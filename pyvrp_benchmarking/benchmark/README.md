# Benchmarks for VRP_Adaptive_SA

Three harnesses, in increasing order of how much they tell you:

| harness | problem | reference | verdict |
|---|---|---|---|
| `run_sa.py` + `report.py` | single-depot CVRP (a *restriction* of this model) | CVRPLIB X-series best-known | ~5.9% off BKS, flat in *n* |
| `run_sa_mdvrp.py` + `report_mdvrp.py` | generated multi-depot chaining instances | PyVRP | wins on large instances, **but see the caveat below** |
| `run_sa_mdvrpi.py` + `report_mdvrpi.py` | **MDVRPI** — the published problem this model actually solves | Crevier et al. (2007) | **+5.9% worse, on a relaxation. Read this one first.** |

**The caveat on the middle row.** Those instances were generated to exercise this model's
features, and this model has no duration constraint, so neither do they. The comparison is
sound for the problem as posed; the problem as posed is the easy one. It is kept for the
mechanism it shows (long vehicle chains vs. fleet size), not as evidence of quality.

**Start with `mdvrpi.py`.** That is the real benchmark, and the solver cannot currently run it:
MDVRPI caps rotation duration at `D`, counting travel + service + docking, and this model has
no notion of time (`planning/vehicle-time-limits.md`, "Status: not started"). What was run is
the relaxation with `D` dropped, which lower-bounds the true optimum, and it still came out
5.9% above the 2007 published values on 8 of 10 instances while overshooting `D` by up to 83%.
Implement the time limits and `run_sa_mdvrpi.py` will score honestly with no further work.

---

# CVRPLIB benchmark

`RESULTS.md` lists "no external benchmark" as the project's most important gap:

> Every number here is the solver measured against itself. Whether it is 2% or 20% off a
> commercial solver is unknown, and it is the thing a reader should most want to know.

This closes it. It runs the solver and [PyVRP](https://github.com/PyVRP/PyVRP) on the same
CVRPLIB instances under the same wall-clock budget on the same machine, and reports both
against published best-known solutions.

```bash
./benchmark/setup.sh
python benchmark/bench.py --seconds 60 --seeds 3    # ~30 min
python benchmark/report.py
```

---

## Why this comparison is legitimate

CVRPLIB's CVRP is a *restriction* of this repo's model, not a different problem:

| model feature | under single-depot CVRP |
|---|---|
| route may end at a different depot | one depot, so every route is closed — degenerate |
| a vehicle chains several routes | with one depot, a chain of *k* routes is indistinguishable from *k* independent CVRP routes |
| capacity priced, not forbidden | still priced; the returned solution is *verified* feasible, not assumed |
| `cost_per_depot`, `cost_per_vehicle` | set to 0 — CVRP minimises travel distance only |

So the benchmark exercises the routing engine, the operator roster and the annealing schedule
under exactly the conditions the best-known solutions were computed for. What it does **not**
exercise is the three features that make this model unusual — inter-depot route chaining,
open-ended routes, and priced overload.

**Correction.** An earlier version of this file, and `RESULTS.md`, claimed no standard
benchmark exists for that combination. That is wrong. The problem has a name and a
literature: it is the **multi-depot VRP with inter-depot routes (MDVRPI)**, defined by
Crevier, Cordeau & Laporte, *EJOR* 176(2):756–773, 2007. Their formulation has vehicles
performing chained "rotations" through intermediate depots, with capacity penalised during
search and hard in the final solution — the same problem this model solves, minus the fixed
vehicle and depot costs, which are a mild generalisation. They publish 12 generated instances
plus 10 adapted from the Cordeau MDVRP set, and there is later exact (branch-and-price) work.
Benchmarking against those instances is the measurement that would actually settle where this
solver stands. See `mdvrp.py` for the generated-instance harness in the meantime.

### Two things that would otherwise invalidate the numbers

**Distance convention.** CVRPLIB's `EUC_2D` is `nint(hypot)` — rounded to the nearest integer.
The solver uses raw float `hypot`. Comparing a float objective against integer-matrix
best-knowns is meaningless, so `run_sa.py` replaces the module-level `dist` with the TSPLIB
rounding. `Node.distance` resolves `dist` from its own module globals, so the replacement
covers every objective and delta computation without editing the solver source.

**Trusting a solver about its own objective.** Both sides' route lists are re-verified from raw
geometry by `cvrplib.verify_routes` — coverage, capacity, and distance recomputed from the
`.vrp` file. The `cost` field in the results is that recomputed number, never the solver's own.
If they disagree, the report shows it. (They have not so far: `reported_objective == cost` on
every run.)

---

## Files

| file | role |
|---|---|
| `setup.sh` | two virtualenvs + instance download |
| `cvrplib.py` | TSPLIB reader, `EUC_2D`, independent verifier — imports no solver |
| `run_sa.py` | this repo's solver on one instance → one JSON line |
| `run_pyvrp.py` | PyVRP on one instance → one JSON line |
| `bench.py` | sequential driver over instances × seeds → `results.jsonl` |
| `report.py` | table of gaps to best-known |
| `compat_patch.py` | makes the solver importable on 3.12/3.13 (see below) |

Two virtualenvs because the solver and PyVRP have different Python floors. They never talk to
each other — each appends JSON lines to the same file.

`bench.py` runs everything **sequentially**. Two solvers competing for cores would make a
wall-clock-budgeted comparison meaningless, which is the entire measurement.

---

## Reading the output

```
instance           n      BKS    PyVRP   gap%    iters   SA mean    gap%  SA best   bgap%  spread%
X-n101-k25       101    27591    27591   0.00   77,834     29061    5.33    28990    5.07     0.63
...
mean gap to BKS                          0.58                       5.66             5.07
```

`report.py` headlines the **mean** gap across seeds, not the best. Best-of-*k* on a stochastic
solver is a biased estimate — the same argmax-selection problem `METHODOLOGY.md` already
rejects for parameter tuning. Best and seed spread are shown next to it so the noise stays
visible.

`iters` is reported for PyVRP so the implementation-language gap stays in view. PyVRP is
compiled C++; this solver is pure Python. A wall-clock comparison is the right question for
"how good is this solver," but it is not an algorithmic comparison, and the iteration counts
are what let a reader separate the two.

---

## Python versions

The solver currently requires **Python 3.14**: class-body annotations like `route: Route | None`
are forward references that only became lazy under PEP 649.

`setup.sh` detects this. If the solver won't import on the interpreter it picked, it applies
`compat_patch.py --apply`, which prepends `from __future__ import annotations` (Python 3.7+) to
the four solver modules — the same effect, no behavioural change, one line per file.

```bash
python benchmark/compat_patch.py --check     # status, changes nothing
python benchmark/compat_patch.py --revert    # undo
```

Both directions are idempotent. Override the interpreters with
`SA_PYTHON=... PYVRP_PYTHON=... ./benchmark/setup.sh`.

After the patch the floor is **3.12**, set by PEP 695 generic syntax — `class Move[Ops: tuple]`,
`class OperatorBL[Ops: tuple]`, `class Operator[Ops: tuple]`, `class BestOfCandidates[Ops: tuple]`,
and two `defaultdict` helpers. These are load-bearing, not dead code, so 3.12 is a real floor
unless they are rewritten with `TypeVar`/`Generic`. `setup.sh` will tell you if the interpreter
it found is too old.

---

## Options worth knowing

```bash
# smaller/faster sanity run
python benchmark/bench.py --instances X-n101-k25 X-n200-k36 --seconds 20 --seeds 2

# the shipped SimAnn_VRP.py uses make_dumb_initial_solution; compare constructors
python benchmark/bench.py --construction dumb --only sa --seconds 60

# a single run, verbose (the solver's own stats report goes to stdout above the JSON)
benchmark/venv-sa/bin/python benchmark/run_sa.py \
    benchmark/instances/CVRP/X-n101-k25.vrp --seconds 30 --seed 0
```

`--vehicles` sets fleet size, defaulting to `ceil(total demand / capacity) + 2`. Since a vehicle
may run several routes, this is not a limit on the number of routes.

Instances come from the [PyVRP/Instances](https://github.com/PyVRP/Instances) mirror of the
Uchoa et al. X-series, which ships best-known solutions alongside each `.vrp`.
