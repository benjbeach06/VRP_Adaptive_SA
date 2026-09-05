"""
Run this repository's solver on the Crevier et al. MDVRPI benchmark.

IMPORTANT — THIS IS A RELAXATION, NOT THE BENCHMARK
---------------------------------------------------
MDVRPI constrains the duration of each rotation to D, counting travel + per-customer
service time + a docking time at each intermediate depot. This model implements no
notion of time at all (`planning/vehicle-time-limits.md`: "Status: not started"), so
what runs here is MDVRPI *with the duration constraint dropped* -- a strict
relaxation of the published problem.

That makes the comparison one-directional but still informative:

  * the relaxation's optimum is a LOWER BOUND on the true MDVRPI optimum, so a cost
    below the published value is expected and says nothing on its own;
  * a cost ABOVE the published value means the solver loses to Crevier et al. (2007)
    while solving an easier problem, which would be decisive;
  * the measured duration overshoot says how far the returned solutions sit from the
    feasible region, i.e. how much the missing constraint would actually cost.

Capacity, coverage and the vehicle limit m ARE enforced and verified. The objective
is pure travel duration, matching the paper (cost_per_vehicle and cost_per_depot are
set to zero). Distances are real-valued, matching the Cordeau/Crevier convention --
not the integer TSPLIB rounding used by the CVRPLIB harness.
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

from mdvrpi import evaluate, dist  # noqa: E402

import SimAnn_VRP_Core_Model as CM  # noqa: E402

CM.dist = dist                       # real-valued Euclidean, per the paper
if hasattr(CM.dist, "cache_clear"):
    CM.dist.cache_clear()

from SimAnn_VRP_Core_Model import Customer, Depot, Vehicle, FullSolution  # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver  # noqa: E402


def build(inst: dict, vehicles: int):
    depots = [Depot(dID=i, location=tuple(loc), supply_limit=-1, vehicle_count=-1)
              for i, loc in enumerate(inst["depots"])]
    customers = [Customer(cID=i, location=tuple(c["loc"]), demand=c["demand"])
                 for i, c in enumerate(inst["customers"])]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    # m vehicles total, spread round-robin over the depots. The paper's m is the
    # fleet size; it does not state a per-depot allocation, so this is an assumption
    # and --vehicles lets it be varied.
    for v in range(vehicles):
        sln.add_vehicle(Vehicle(initial_depot=depots[v % len(depots)], i=v,
                                capacity=inst["capacity"]))
    # Pure travel objective, matching the paper.
    sln.set_objectives(unit_travel_cost=1, cost_per_vehicle=0, cost_per_depot=0)
    return sln


def extract(sln) -> list[list[dict]]:
    return [[{"start": r.start_depot.dID, "end": r.end_depot.dID,
              "visits": [v.cID for v in r.path]} for r in vehicle.routes]
            for vehicle in sln.vehicles]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--vehicles", type=int, default=None,
                    help="override the fleet size (default: m from Table 7)")
    args = ap.parse_args()

    inst = json.loads(Path(args.instance).read_text())
    fleet = args.vehicles or inst["num_vehicles"]

    CM.solver_rng.seed(args.seed)
    sln = build(inst, fleet)
    solver = SimAnnVRPSolver(sln, max_time=args.seconds)

    t0 = time.time()
    solver.make_initial_solution()
    solver.solve()
    elapsed = time.time() - t0

    reported, best = solver.get_best_snapshot()
    ev = evaluate(extract(best), inst)
    pub = inst["published_best"]

    print(json.dumps({
        "solver": "simann_sa_relaxed",
        "instance": inst["name"], "source": inst["source"],
        "n": len(inst["customers"]), "depots": len(inst["depots"]),
        "fleet": fleet, "seed": args.seed, "seconds": args.seconds,
        "elapsed": round(elapsed, 2),
        # The solver keeps its loop counter local to solve(), so the move count is
        # summed off the operator roster instead. One "iteration" here is a single
        # move proposal, which is NOT the same unit as a PyVRP HGS generation.
        "iterations": sum(op.num_invalid_calls + op.num_noop_calls + op.num_useful_calls
                          for op in solver.operators),
        "reported_objective": round(reported, 2),
        "cost": round(ev["cost"], 2),
        "published_best": pub,
        "vs_published_pct": round(100 * (ev["cost"] - pub) / pub, 2),
        "vehicles_used": ev["vehicles_used"],
        "capacity_and_coverage_ok": ev["capacity_and_coverage_ok"],
        "problems": ev["problems"][:5],
        # The relaxation's tell: how far outside the true feasible region it lands.
        "duration_ok": ev["duration_ok"],
        "num_duration_violations": len(ev["duration_violations"]),
        "worst_over_pct": ev["worst_over_pct"],
        "duration_violations": ev["duration_violations"][:8],
    }))


if __name__ == "__main__":
    main()
