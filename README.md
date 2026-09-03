# Multi-depot VRP solver

A simulated-annealing solver for the **multi-depot vehicle routing problem with inter-depot
routes**, written from scratch in Python with no solver dependency.

A vehicle does not run one loop out of one depot. It runs a *chain* of routes across depots, and
each route may end somewhere other than where it started. That is the MDVRPI of Crevier, Cordeau
and Laporte (*EJOR* 176(2), 2007), and it is the problem this solver is built for.

Three properties make it different from the textbook MDVRP. All three are first-class in the model
rather than repaired afterward:

- **A route may end at a different depot than it starts from.** Routes are open at both ends.
- **A vehicle runs several routes in sequence.** Each route begins where the previous one ended, so
  a vehicle's day is a chain across depots.
- **Capacity overload is priced, not forbidden.** Infeasible solutions are reachable and carry a
  cost, so the search can cross an infeasible region to reach a better feasible one.

---

## Where it stands

| comparison | result                                                     |
|---|------------------------------------------------------------|
| **CVRPLIB X-instances vs published best-known** | **4.3% mean gap**, best of 5 seeds, n = 101 to 1001, 600 s |
| **vs Hexaly**, own multi-depot instance, 500 customers | **3.32%** behind a converged Hexaly solve                  |
| iteration throughput vs Hexaly | **~20-30x fewer** iterations per second                    |

The most obvious gap is throughput, not search quality per iteration. For context, Hexaly with 10 minutes improves to 1830.. The full tables, and the measurements that did
*not* survive checking, are in **[RESULTS.md](RESULTS.md)**.

---

## Quickstart

**Python 3.14 is a hard requirement**, not a preference. The model uses PEP 695 generics
(`class Foo[T]`) and relies on PEP 649 deferred annotation evaluation for forward references
throughout the core model. On 3.13 the import fails with a `NameError` that looks like a code
defect.

```bash
python -m pip install numpy
python SimAnn_VRP.py
```

That solves the built-in instance for 60 seconds and prints the routes, the per-vehicle distances,
and the objective broken into its terms.

`build_vrp_model()` in [SimAnn_VRP.py](SimAnn_VRP.py) defines that instance: 3 depots on a 100x100
integer grid at seed 42, one vehicle per depot, with the customer count and vehicle capacity set at
the top of the function. It is a scratch driver, so treat the values checked in there as an example
rather than a specification. `RESULTS.md` names the shapes the measurements were taken at.

### Solving your own instance

```python
from SimAnn_VRP_Core_Model import FullSolution, Depot, Customer, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver

sln = FullSolution()
sln.set_customers([Customer(cID=i, location=(x, y), demand=d) for i, (x, y, d) in enumerate(...)])
sln.set_depots([Depot(dID=i, location=(x, y), supply_limit=35, vehicle_count=1) for ...])
sln.add_vehicle(Vehicle(initial_depot=depots[0], i=0, capacity=400))
sln.set_objectives(unit_travel_cost=1, cost_per_vehicle=10, cost_per_depot=20)

solver = SimAnnVRPSolver(sln, max_time=60)
solver.make_initial_solution()      # greedy nearest-neighbor construction
solver.solve()

objective, best = solver.get_best_snapshot()
```

Customer and depot IDs must be dense and zero-based. The solver asserts this on construction,
because several indices are plain arrays keyed by ID.

### Dependencies

| package | needed for |
|---|---|
| `numpy` | the solver itself — neighbor tables and instance generation |
| `optuna` | `tools/tune*.py` only |
| `matplotlib` | `tools/plot_*.py` and `tools/compare_runs.py` only |
| `pyinstrument` | `tools/profile_one_operator.py` only |
| `hexaly` | `Hexaly_VRP.py` only; needs its own license |

Only `numpy` is required to run or test the solver.

---

## The model

Three node types, defined in [SimAnn_VRP_Core_Model.py](SimAnn_VRP_Core_Model.py).

| | fields |
|---|---|
| `Customer` | `cID`, `location`, `demand` |
| `Depot` | `dID`, `location`, `supply_limit`, `vehicle_count` |
| `Vehicle` | `vID`, `initial_depot`, `capacity` |

A `Route` is a doubly-linked chain of customer visits with a start depot and an end depot. A
`Vehicle` owns an ordered list of routes. A `FullSolution` owns the customers, depots, vehicles and
all cached objective terms.

### Objective

Minimized. Every term is a separate knob, so any one of them can be switched off by setting it to
zero.

```
  unit_travel_cost         x  total euclidean distance
+ cost_per_vehicle         x  vehicles used
+ cost_per_depot           x  depots used
+ unit_overload_penalty    x  total units of overload
+ vehicle_overload_penalty x  vehicles overloaded
```

Set with `FullSolution.set_objectives`. The last two default to `1000` and `100000` — high enough
that a feasible solution always beats an infeasible one, low enough that the search can pass
through infeasibility rather than being walled off from it.

### How a move gets priced

This is the decision the whole solver rests on. Every mutation has a matching `cost_deltas_if_*`
function that prices it in **O(1) from the arcs at its boundary**, so the search never recomputes a
full objective. A proposal that is rejected costs only that arithmetic.

Pricing produces a `RawDeltaRecord` — what structurally changed, per route, and nothing else. A
single `AccountingProcessor` turns that into objective terms and cached-state updates, and a single
sink on `FullSolution` applies them. Reverting subtracts the same record. Nothing else in the model
writes accounting.

Every cached quantity also has a recompute-from-scratch twin used for verification. Most real bugs
here surfaced as a disagreement between the fast path and the slow one. See
[design/raw_delta_accounting/](design/raw_delta_accounting/README.md).

---

## Solver options

All keyword-only, on `SimAnnVRPSolver.__init__`. Defaults shown are the shipped ones.

| option | default | what it does |
|---|---|---|
| `max_time` | `120` | wall-clock budget in seconds; the only termination condition |
| `initial_temp_factor` | `1e-4` | starting temperature as a fraction of the initial objective. Low, so the run exploits before it explores |
| `plateau_reheat_exponent` | `0.5561` | how hard to reheat, as a fractional exponent of the objective at plateau start |
| `segment_length` | `123` | iterations between operator-weight updates. A pure sampling rate in time mode |
| `reaction_factor` | `0.01` | how fast operator weights follow recent scores. 0 freezes them |
| `weight_time_constant` | `1.937` | time constant of the weight EMA, in seconds of that operator's own time |
| `explore_reward` | `1e-5` | score floor for an accepted uphill move, so operators that pay off through exploration can still earn weight |
| `Bayes_magnet` | `1-0.002156` | how strongly an unproposed operator is pulled toward its siblings |
| `empty_route_cleanup_interval` | `100` | segments between empty-route sweeps |

**The schedule runs on one clock, and it is wall clock by default.** Cooling and plateau detection
read the same clock, so they can never disagree about units. Each mode keeps its own pair of
parameters, so neither is ever silently inactive:

| `time_based_schedule` | cooling | plateau |
|---|---|---|
| `True` (default) | `cooling_rate_per_second = 2.322` | `max_plateau_seconds = 0.343` |
| `False` | `cooling_factor = 1 - 1e-4` | `max_plateau_size = 1500` segments |

Iteration mode reproduces the pre-2026-08-23 solver exactly, and is what
`set_deterministic_weighting()` selects.

**Reheating is anchored to the current objective**, not to a fixed temperature. The schedule
therefore self-calibrates to the instance, and the same defaults work across instance sizes without
rescaling. See [design/schedule/time_based_schedule.md](design/schedule/time_based_schedule.md).

### Operators

24 of them, in [SimAnn_VRP_Operators.py](SimAnn_VRP_Operators.py), over an
`evaluate -> apply -> commit | revert` lifecycle. They are arranged in a family tree, and selection
descends it one level at a time rather than drawing from a flat roster.

An operator's draw probability is `weight x penalty`. **Weight** is an EMA of score per proposal
and decays. **Penalty** is a plain cost ratio, recomputed from measured wall-clock cost and never
decayed. So benefit is forgotten and cost is not, which is what keeps an expensive operator from
drifting back to an equal share at plateau. See
[design/operator_selection/](design/operator_selection/README.md).

**Operand selection is where most of the performance lives.** The same move type accepts far fewer
proposals with a randomly chosen destination than with a geometrically chosen one — 0.00% against
0.30% on relocate.

---

## Verification

```bash
VRP_FULL_MATRIX=1 python -m unittest discover -s tests
```

```bash
python tools/stress.py --budget-seconds 45
```

`stress.py` runs randomized operator sequences against the recompute-from-scratch oracles, and
reports per-operator coverage so a silently dead operator cannot pass by doing nothing.

```bash
python tools/stress.py --budget-seconds 45 --inject-delta 0.5 --out /tmp/injected.json
```

`--inject-delta` deliberately corrupts a move's price. **It must produce findings.** A clean run
means nothing until the detector has been shown to fire. Pass `--out`, or it overwrites the
committed `tools/stress_results.json`.

```bash
python tools/compare_deterministic.py <commit>
```

Fixed-iteration cross-commit equivalence. Use it to show a refactor changed nothing.

---

## Layout

| file | role |
|---|---|
| `SimAnn_VRP_Core_Model.py` | data model, delta arithmetic, neighbor tables |
| `SimAnn_VRP_Accounting.py` | the processor: raw structural deltas to objective terms |
| `SimAnn_VRP_BLOperators.py` | move lifecycle: `evaluate` → `apply` → `commit` \| `revert` |
| `SimAnn_VRP_Operators.py` | 24 operators over that lifecycle, plus operand selection |
| `SimAnn_VRP_Solver.py` | annealing schedule, adaptive operator weighting, construction |
| `tools/` | stress, profiling, ablation, tuning, doc linking |
| `tests/` | unit and contract tests |
| `solutions/` | best-known solutions, with the instance descriptor needed to re-verify them |
| `design/` | why the code is shaped the way it is |
| `planning/` | what comes next, and the gate each item is waiting on |

---

## Further reading

- **[RESULTS.md](RESULTS.md)** — every measurement, including the ones that did not survive
  checking: benchmark gaps, best-known solutions, operator ablation, the 39x construction speedup,
  and two parameter searches that both found nothing. Start here if you want to know what the
  solver does.
- **[METHODOLOGY.md](METHODOLOGY.md)** — how those measurements get accepted or rejected, the
  pre-launch routine for long runs, and the provenance of the code. Start here if you are
  evaluating the engineering rather than the routing.
- **[design/](design/README.md)** — why each mechanism is shaped the way it is, one folder per
  feature area.
- **[planning/](planning/README.md)** — the roadmap. One file per item, each stating the problem,
  the measurement motivating it, and the gate that would justify starting. Most are deliberately
  not started, and each records why.
