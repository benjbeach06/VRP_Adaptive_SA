"""
Turn a solver run log into a `solutions/best_<objective>.json` record.

PROVENANCE
----------
Written by Claude (Anthropic) during development assistance; not hand-written by the repository
author. Written because the first three solutions/*.json files were produced ad hoc, and the
2026-09-02 record existed only as a run log -- a number that cannot be rebuilt or re-verified.

    python tools/log_to_solution.py temp/SimAnn_SmallRoutes_9-2-26 --budget 180 --date 2026-09-02

WHAT IT READS
    `SimAnn_VRP.py` prints, after the search, one line per route:
        0, {'Path': ['d0', 83, 95, 45, 134, 'd0'], 'Vehicle': 0, 'Cost': 41.23...}
    then a totals line:
        Total cost: Vehicle use cost 20 + Depot use cost 60 + Travel cost 3301.54... = 3381.54...
    and the periodic progress lines, from which iterations and reheat counts are taken.

WHAT IT VERIFIES, BEFORE WRITING ANYTHING
    The instance is rebuilt here from `numpy_seed`, independently of the run. Then:
      * every customer appears exactly once,
      * no route exceeds vehicle capacity,
      * each route's logged cost equals the cost recomputed from the geometry,
      * travel, vehicle-use cost, depot-use cost and objective agree with the logged totals.
    A solution that fails any check is NOT written. This is the same check that was applied by
    hand to best_3473.64.json.

INSTANCE DUPLICATION -- deliberate
    The instance construction below is a copy of `SimAnn_VRP.build_vrp_model()`'s first lines.
    Importing that module is impossible: it calls build_vrp_model() at import time, which runs a
    full solve. Copying also keeps the verification independent of the solver's own object graph,
    which is the point of a re-verification. If the entry point's instance changes, this script's
    checks fail loudly rather than agreeing with a stale log.
"""
import argparse
import ast
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROUTE_RE = re.compile(r"^\d+, (\{'Path'.*\})\s*$")
TOTAL_RE = re.compile(
    r"^Total cost: Vehicle use cost (\S+) \+ Depot use cost (\S+) \+ "
    r"Travel cost (\S+) = (\S+)\s*$")
PROGRESS_RE = re.compile(
    r"Complete reheats: (\d+), Plateau reheats: (\d+), Iterations: (\d+)")
WEIGHTS_RE = re.compile(r"^op weights:\[(.*)\]\s*$")


def build_instance(numpy_seed: int, num_customers: int) -> tuple[list[dict], list[dict]]:
    """Copy of SimAnn_VRP.build_vrp_model()'s instance construction. See the module docstring."""
    import numpy as np
    np.random.seed(numpy_seed)
    depot_data = [
        {"location": (10, 10), "supply_limit": 35, "vehicle_count": 1},
        {"location": (50, 50), "supply_limit": 35, "vehicle_count": 1},
        {"location": (90, 10), "supply_limit": 35, "vehicle_count": 1},
    ]
    customer_data = [
        {"location": tuple(np.random.randint(0, 100, size=2)),
         "demand": np.random.randint(1, 11)}
        for _ in range(num_customers)
    ]
    depots = [{"dID": i, "location": [int(v) for v in d["location"]],
               "supply_limit": d["supply_limit"], "vehicle_count": d["vehicle_count"]}
              for (i, d) in enumerate(depot_data)]
    customers = [{"cID": i, "location": [int(v) for v in c["location"]],
                  "demand": int(c["demand"])}
                 for (i, c) in enumerate(customer_data)]
    return depots, customers


def parse_log(path: str) -> dict:
    routes: list[dict] = []
    totals: tuple[float, ...] | None = None
    progress: tuple[int, ...] | None = None
    roster: int | None = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            m = ROUTE_RE.match(line)
            if m:
                routes.append(ast.literal_eval(m.group(1)))
                continue
            m = TOTAL_RE.match(line)
            if m:
                totals = tuple(float(g) for g in m.groups())
                continue
            m = PROGRESS_RE.search(line)
            if m:
                progress = tuple(int(g) for g in m.groups())
                continue
            m = WEIGHTS_RE.match(line)
            if m:
                roster = len(ast.literal_eval("[" + m.group(1) + "]"))
    if not routes:
        sys.exit(f"{path}: no route dump found. The run must finish for its routes to print.")
    if totals is None:
        sys.exit(f"{path}: no 'Total cost:' line found.")
    return {"routes": routes, "totals": totals, "progress": progress, "roster": roster}


def dist(a: list[int], b: list[int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def verify(parsed: dict, depots: list[dict], customers: list[dict], capacity: int,
           cost_per_vehicle: float, cost_per_depot: float,
           unit_travel_cost: float) -> tuple[list[dict], dict, int]:
    """Return (route records, cost breakdown, overload). Exits on any failure."""
    depot_loc = {d["dID"]: d["location"] for d in depots}
    cust = {c["cID"]: c for c in customers}
    problems: list[str] = []
    seen: dict[int, int] = {}
    travel = 0.0
    overload = 0
    used_vehicles: set[int] = set()
    used_depots: set[int] = set()
    records: list[dict] = []

    for entry in parsed["routes"]:
        raw = entry["Path"]
        start = int(raw[0][1:])
        end = int(raw[-1][1:])
        path = [int(c) for c in raw[1:-1]]
        vehicle = int(entry["Vehicle"])
        records.append({"vehicle": vehicle, "start_depot": start,
                        "path": path, "end_depot": end})
        if not path:
            continue
        used_vehicles.add(vehicle)
        used_depots.update((start, end))
        points = [depot_loc[start]] + [cust[c]["location"] for c in path] + [depot_loc[end]]
        leg = sum(dist(points[i], points[i + 1]) for i in range(len(points) - 1))
        travel += leg
        if abs(leg - float(entry["Cost"])) > 1e-9:
            problems.append(f"route {len(records) - 1}: logged cost {entry['Cost']} "
                            f"!= recomputed {leg}")
        load = sum(cust[c]["demand"] for c in path)
        if load > capacity:
            overload += load - capacity
            problems.append(f"route {len(records) - 1}: load {load} exceeds capacity {capacity}")
        for c in path:
            seen[c] = seen.get(c, 0) + 1

    missing = sorted(set(cust) - set(seen))
    repeated = sorted(c for (c, n) in seen.items() if n > 1)
    if missing:
        problems.append(f"{len(missing)} customers never visited: {missing[:10]}")
    if repeated:
        problems.append(f"{len(repeated)} customers visited more than once: {repeated[:10]}")

    log_vehicle_cost, log_depot_cost, log_travel, log_objective = parsed["totals"]
    vehicle_cost = len(used_vehicles) * cost_per_vehicle
    depot_cost = len(used_depots) * cost_per_depot
    if abs(travel * unit_travel_cost - log_travel) > 1e-6:
        problems.append(f"travel {travel} != logged {log_travel}")
    if vehicle_cost != log_vehicle_cost:
        problems.append(f"vehicle-use cost {vehicle_cost} != logged {log_vehicle_cost}")
    if depot_cost != log_depot_cost:
        problems.append(f"depot-use cost {depot_cost} != logged {log_depot_cost}")
    total = vehicle_cost + depot_cost + travel * unit_travel_cost
    if abs(total - log_objective) > 1e-6:
        problems.append(f"objective {total} != logged {log_objective}")

    if problems:
        print("VERIFICATION FAILED. Nothing written.", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        sys.exit(1)

    print(f"Verified against a freshly built instance: {len(cust)}/{len(cust)} customers covered "
          f"once, {overload} overload, per-route costs to 1e-9, totals to 1e-6.")
    return records, {"vehicle_use_cost": vehicle_cost, "depot_use_cost": depot_cost,
                     "travel_cost": travel * unit_travel_cost}, overload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--budget", type=float, required=True, help="wall-clock seconds of the run")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD the run was made")
    ap.add_argument("--commit", default="", help="commit the run was made at")
    ap.add_argument("--note", default="")
    ap.add_argument("--customers", type=int, default=200)
    ap.add_argument("--capacity", type=int, default=25)
    ap.add_argument("--numpy-seed", type=int, default=42)
    ap.add_argument("--cost-per-vehicle", type=float, default=10)
    ap.add_argument("--cost-per-depot", type=float, default=20)
    ap.add_argument("--unit-travel-cost", type=float, default=1)
    ap.add_argument("--out", default="", help="defaults to solutions/best_<objective>.json")
    args = ap.parse_args()

    parsed = parse_log(args.log)
    depots, customers = build_instance(args.numpy_seed, args.customers)
    records, breakdown, overload = verify(
        parsed, depots, customers, args.capacity,
        args.cost_per_vehicle, args.cost_per_depot, args.unit_travel_cost)

    objective = sum(breakdown.values())
    complete_reheats, plateau_reheats, iterations = parsed["progress"] or (None, None, None)

    doc = {
        "objective": objective,
        "breakdown": breakdown,
        "total_overload": overload,
        "found": {
            "date": args.date,
            "budget_seconds": args.budget,
            "iterations": iterations,
            "plateau_reheats": plateau_reheats,
            "complete_reheats": complete_reheats,
            "operator_roster_size": parsed["roster"],
            "commit": args.commit,
            "run_log": os.path.relpath(os.path.abspath(args.log), ROOT).replace("\\", "/"),
        },
        "instance": {
            "source": "SimAnn_VRP.py build_vrp_model(), use_pre_refactor_data = True",
            "numpy_seed": args.numpy_seed,
            "num_customers": args.customers,
            "capacity_per_vehicle": args.capacity,
            "cost_per_vehicle": args.cost_per_vehicle,
            "cost_per_depot": args.cost_per_depot,
            "unit_travel_cost": args.unit_travel_cost,
            "depots": depots,
            "vehicles": [{"vID": i, "initial_depot": i, "capacity": args.capacity}
                         for i in range(len(depots))],
        },
        "note": args.note,
        "routes": records,
    }

    out = args.out or os.path.join(ROOT, "solutions", f"best_{objective:.2f}.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1)
        handle.write("\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
