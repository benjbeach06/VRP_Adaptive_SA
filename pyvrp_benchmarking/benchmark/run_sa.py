"""
Run the SimAnn VRP solver on a CVRPLIB instance and emit one JSON line.

WHY THIS IS A FAIR COMPARISON
-----------------------------
CVRPLIB's CVRP is exactly the special case of this repo's model with:

  * one depot        -- every route then starts and ends at the same depot, so
                        "a route may end at a different depot" degenerates to
                        the usual closed route;
  * cost_per_depot   = 0  (one depot, always used);
  * cost_per_vehicle = 0  -- the CVRP objective is pure travel distance;
  * a vehicle owning a *chain* of routes is, under one depot, indistinguishable
    from that many independent CVRP routes. So multi-trip is not an extra
    feature here, it is just how the fleet is represented.

Capacity is still priced rather than forbidden, so the returned solution is
verified feasible from raw geometry afterwards instead of being assumed so.
An infeasible result is reported as infeasible, not silently scored.

Distances use the TSPLIB EUC_2D convention, applied by replacing the module
level `dist` function -- no edit to the solver source. `Node.distance` resolves
`dist` from its own module globals, so the replacement covers every objective
and delta computation.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The solver modules sit at the repo root. This directory was meant to be dropped
# directly under it, but it also runs from a subdirectory, so search upward for the
# root rather than assuming it is the parent.
ROOT = next(p for p in HERE.parents if (p / "SimAnn_VRP_Core_Model.py").exists())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from cvrplib import read_instance, euc_2d, verify_routes  # noqa: E402

import SimAnn_VRP_Core_Model as CM  # noqa: E402

# Install the TSPLIB rounding convention before any distance is computed or cached.
CM.dist = euc_2d
if hasattr(CM.dist, "cache_clear"):
    CM.dist.cache_clear()

from SimAnn_VRP_Core_Model import Customer, Depot, Vehicle, FullSolution  # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver  # noqa: E402


def build_solution(inst: dict, num_vehicles: int):
    """Map a CVRPLIB instance onto the repo's FullSolution.

    Customers are indexed 0..n-1 in ascending instance-node order; `node_of`
    maps back so verification can be done against the original file.
    """
    depot_node = inst["depot"]
    customer_nodes = sorted(k for k in inst["coords"] if k != depot_node)
    node_of = dict(enumerate(customer_nodes))

    depot = Depot(dID=0, location=inst["coords"][depot_node],
                  supply_limit=-1, vehicle_count=-1)
    customers = [
        Customer(cID=i, location=inst["coords"][n], demand=inst["demands"][n])
        for i, n in node_of.items()
    ]

    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots([depot])
    for v in range(num_vehicles):
        sln.add_vehicle(Vehicle(initial_depot=depot, i=v, capacity=inst["capacity"]))
    sln.set_objectives(unit_travel_cost=1, cost_per_vehicle=0, cost_per_depot=0)
    return sln, node_of


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instance", help="path to a CVRPLIB .vrp file")
    ap.add_argument("--seconds", type=float, default=60.0,
                    help="wall-clock budget for solve() (default 60)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--vehicles", type=int, default=None,
                    help="fleet size (default: ceil(total demand / capacity) + 2 slack). "
                         "A vehicle may run several routes, so this is not a route limit.")
    ap.add_argument("--construction", choices=["greedy", "dumb"], default="greedy",
                    help="greedy = make_initial_solution (documented default); "
                         "dumb = make_dumb_initial_solution (what SimAnn_VRP.py ships)")
    args = ap.parse_args()

    inst = read_instance(args.instance)
    lower_bound_k = math.ceil(sum(inst["demands"].values()) / inst["capacity"])
    k = args.vehicles or (lower_bound_k + 2)

    CM.solver_rng.seed(args.seed)
    sln, node_of = build_solution(inst, k)
    solver = SimAnnVRPSolver(sln, max_time=args.seconds)

    t0 = time.time()
    if args.construction == "greedy":
        solver.make_initial_solution()
    else:
        solver.make_dumb_initial_solution()
    construct_s = time.time() - t0
    initial_objective = sln.solution_cost()

    solver.solve()
    elapsed = time.time() - t0

    best_objective, best_sln = solver.get_best_snapshot()

    routes = [[node_of[v.cID] for v in r.path] for r in best_sln.all_routes if list(r.path)]
    verified, problems = verify_routes(routes, inst)

    print(json.dumps({
        "solver": "simann_sa",
        "instance": inst["name"],
        "n": inst["n_customers"],
        "capacity": inst["capacity"],
        "seed": args.seed,
        "seconds": args.seconds,
        "elapsed": round(elapsed, 2),
        "construction": args.construction,
        "construct_seconds": round(construct_s, 3),
        "vehicles_allowed": k,
        "min_vehicles": lower_bound_k,
        "initial_objective": initial_objective,
        "reported_objective": best_objective,
        "cost": verified,          # the number that gets compared; recomputed from geometry
        "routes": len(routes),
        "feasible": not problems,
        "problems": problems,
    }))


if __name__ == "__main__":
    main()
