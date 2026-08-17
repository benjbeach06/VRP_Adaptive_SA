# Multi-depot VRP solver

A simulated-annealing solver for the multi-depot, multi-vehicle capacitated vehicle routing problem,
written from scratch in Python with no solver dependency.

It differs from the textbook MDVRP in three ways, all of which the model treats as first-class
rather than as post-processing:

- **A route may end at a different depot than it starts from.** Routes are open at both ends.
- **A vehicle runs several routes in sequence.** Each route begins where the previous one ended, so
  a vehicle's day is a chain of routes across depots, not a single loop.
- **Capacity overload is priced, not forbidden.** Infeasible solutions are reachable and carry a
  cost, so the search can cross an infeasible region to reach a better feasible one.

---

## The model

Three node types, defined in `SimAnn_VRP_Core_Model.py`.

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
that a feasible solution always beats an infeasible one, low enough that the search can pass through
infeasibility rather than being walled off from it.

Every mutation has a matching `cost_deltas_if_*` function that prices it in O(1) from the arcs at
its boundary, so the search never recomputes a full objective. Each cached quantity also has a
recompute-from-scratch twin used for verification.

---

## Running it

```bash
python SimAnn_VRP.py
```

`build_vrp_model()` in `SimAnn_VRP.py` defines the instance — 3 depots, 200 customers on a 100×100
integer grid, seed 42, vehicle capacity 25 — and then runs the solver. Edit it to change the
instance.

### Solver options

All keyword-only, on `SimAnnVRPSolver.__init__`.

| option | default | what it does |
|---|---|---|
| `max_time` | `120` | wall-clock budget in seconds; the only termination condition |
| `cooling_factor` | `1 - 1e-4` | temperature multiplier per iteration |
| `initial_temp_factor` | `1e-4` | starting temperature as a fraction of the initial objective. Low, so the run exploits before it explores |
| `max_plateau_size` | `2000` | segments without a new best before a reheat is triggered |
| `plateau_reheat_exponent` | `0.2` | how hard to reheat, as a fractional exponent of the objective at plateau start |
| `segment_length` | `100` | iterations per segment. Operator weights update once per segment |
| `reaction_factor` | `0.01` | how fast operator weights follow recent scores. 0 freezes them |
| `explore_reward` | `1e-6` | score floor for an accepted uphill move, so operators that pay off through exploration can still earn weight |
| `empty_route_cleanup_interval` | `100` | segments between empty-route sweeps |

Reheating is **anchored to the current objective**, not to a fixed temperature. The schedule
therefore self-calibrates to the instance, and the same defaults work across instance sizes without
rescaling.

### Verification

```bash
VRP_FULL_MATRIX=1 python -m unittest discover -s tests
```

```bash
python tools/stress.py --budget-seconds 45
```

`stress.py` runs randomized operator sequences against recompute-from-scratch oracles, and reports
per-operator coverage so a silently dead operator cannot pass by doing nothing. `--inject-delta`
deliberately corrupts a move's price; it must produce findings, or the harness is not watching.

---

## Layout

| file | role |
|---|---|
| `SimAnn_VRP_Core_Model.py` | data model, delta arithmetic, neighbor tables |
| `SimAnn_VRP_BLOperators.py` | move lifecycle: `evaluate` → `apply` → `commit` \| `revert` |
| `SimAnn_VRP_Operators.py` | 20 operators over that lifecycle, plus operand selection |
| `SimAnn_VRP_Solver.py` | annealing schedule, adaptive operator weighting, construction |
| `tools/` | stress, profiling, ablation, tuning |
| `tests/` | unit and contract tests |
| `solutions/` | best-known solutions, with the instance descriptor needed to re-verify them |
| `planning/` | what comes next, and what each item is waiting on |

Operand selection is where most of the performance lives. The same move type accepts 0.00% of
proposals with a randomly chosen destination and 0.46% with a geometrically chosen one.

---

## Further reading

- **[METHODOLOGY.md](METHODOLOGY.md)** — how results here are measured and accepted, the findings
  that changed the design, and the known limitations. Read this one first if you are evaluating the
  engineering rather than the routing.
- **[planning/](planning/README.md)** — the roadmap. One file per item, each stating the problem,
  the measurement motivating it, and the gate that would justify starting. Most are deliberately not
  started, and each records why.
