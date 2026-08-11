"""
Ablation harness: iterations/sec for a given operator roster, averaged over several RNG seeds.

usage: ablate.py <label> <roster> <seconds> <seed> [<seed> ...]
  roster = all | nodispose
"""
import sys, os, io, contextlib, time

ROOT = r"C:\Users\Bben6\PycharmProjects\PythonProject"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import SimAnn_VRP_Core_Model as CM
from SimAnn_VRP_Core_Model import *          # noqa: F403
from SimAnn_VRP_Solver import SimAnnVRPSolver

label, roster, seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
seeds = [int(s) for s in sys.argv[4:]]

DISPOSE = {"DisposeOfEmptyRoutes", "DisposeOfTrivialRoutes"}


def build():
    np.random.seed(42)
    depots = [Depot(i, loc, 35, 1) for i, loc in enumerate([(10, 10), (50, 50), (90, 10)])]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(200)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(3):
        sln.add_vehicle(Vehicle(initial_depot=depots[i], i=i, capacity=25))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


rates, costs = [], []
for seed in seeds:
    CM.seed_solver_rng(seed)
    sln = build()
    solver = SimAnnVRPSolver(sln)
    solver.max_time = seconds
    if roster == "nodispose":
        solver.operators = [op for op in solver.operators if type(op).__name__ not in DISPOSE]

    count = [0]
    original_choose = solver.choose_operator
    def counting_choose():
        count[0] += 1
        return original_choose()
    solver.choose_operator = counting_choose

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        solver.make_initial_solution()
        started = time.perf_counter()
        solver.solve(debug_level=0)
        wall = time.perf_counter() - started

    rates.append(count[0] / wall)
    costs.append(solver.best_objective)

mean_rate = sum(rates) / len(rates)
print(f"{label:28} roster={roster:10} "
      f"mean {mean_rate:9,.0f} it/s   per-seed: {', '.join(f'{r:,.0f}' for r in rates)}"
      f"   best_obj: {min(costs):.1f}")
