"""
Run the SimAnn VRP solver on a multi-depot chaining instance (see mdvrp.py).

This is the solver's home ground: several depots, vehicles running chains of
routes across them, routes free to end at a depot other than their start, and a
fixed cost per vehicle used.

Capacity is priced here as everywhere in this model, but the instances are
generated with slack and the result is *verified* feasible against a hard
capacity so it can be compared with PyVRP, which cannot price it. An infeasible
result is reported infeasible, never silently scored.
"""
from __future__ import annotations

import argparse
import json
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

from mdvrp import load, evaluate, euc_2d  # noqa: E402

import SimAnn_VRP_Core_Model as CM  # noqa: E402

CM.dist = euc_2d                    # integer matrix, identical on both sides
if hasattr(CM.dist, "cache_clear"):
    CM.dist.cache_clear()

from SimAnn_VRP_Core_Model import Customer, Depot, Vehicle, FullSolution  # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver  # noqa: E402


def build(inst: dict):
    depots = [Depot(dID=i, location=tuple(loc), supply_limit=-1, vehicle_count=-1)
              for i, loc in enumerate(inst["depots"])]
    customers = [Customer(cID=i, location=tuple(c["loc"]), demand=c["demand"])
                 for i, c in enumerate(inst["customers"])]

    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)

    # A generous fleet spread evenly over the depots. The cap is deliberately
    # non-binding: cost_per_vehicle, not the fleet size, should decide how many
    # get used, and `evaluate` checks the cap was never reached.
    vid = 0
    for d in depots:
        for _ in range(inst["vehicles_per_depot"]):
            sln.add_vehicle(Vehicle(initial_depot=d, i=vid, capacity=inst["capacity"]))
            vid += 1

    sln.set_objectives(unit_travel_cost=inst["unit_travel_cost"],
                       cost_per_vehicle=inst["cost_per_vehicle"],
                       cost_per_depot=0)
    return sln


def extract(sln) -> list[list[dict]]:
    """Read the vehicle -> chain-of-routes structure out of the solution."""
    itineraries = []
    for vehicle in sln.vehicles:
        itin = []
        for route in vehicle.routes:
            itin.append({
                "start": route.start_depot.dID,
                "end": route.end_depot.dID,
                "visits": [v.cID for v in route.path],
            })
        itineraries.append(itin)
    return itineraries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inst = load(args.instance)
    CM.solver_rng.seed(args.seed)
    sln = build(inst)
    solver = SimAnnVRPSolver(sln, max_time=args.seconds)

    t0 = time.time()
    solver.make_initial_solution()
    construct_s = time.time() - t0
    solver.solve()
    elapsed = time.time() - t0

    reported, best = solver.get_best_snapshot()
    ev = evaluate(extract(best), inst)

    print(json.dumps({
        "solver": "simann_sa",
        "instance": inst["name"],
        "n": len(inst["customers"]),
        "depots": len(inst["depots"]),
        "seed": args.seed,
        "seconds": args.seconds,
        "elapsed": round(elapsed, 2),
        "construct_seconds": round(construct_s, 3),
        # The solver keeps its loop counter local to solve(), so the move count is
        # summed off the operator roster instead. One "iteration" here is a single
        # move proposal, which is NOT the same unit as a PyVRP HGS generation.
        "iterations": sum(op.num_invalid_calls + op.num_noop_calls + op.num_useful_calls
                          for op in solver.operators),
        "reported_objective": reported,
        "cost": ev["cost"],
        "travel": ev["travel"],
        "vehicles_used": ev["vehicles_used"],
        "trips": ev["trips"],
        "fleet_cap": ev["fleet_cap"],
        # How much the chaining/open-route freedom actually got used:
        "cross_depot_trips": sum(
            1 for it in extract(best) for t in it if t["visits"] and t["start"] != t["end"]),
        "feasible": not ev["problems"],
        "problems": ev["problems"],
    }))


if __name__ == "__main__":
    main()
