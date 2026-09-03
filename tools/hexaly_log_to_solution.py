"""
Turn a Hexaly run log into a `solutions/best_<objective>.json` record.

PROVENANCE
----------
Written by Claude (Anthropic) during development assistance; not hand-written by the repository
author. This is a COPY of tools/log_to_solution.py, adapted to Hexaly's log format. It is a copy
on purpose: log_to_solution.py belongs to the SimAnn project and must not carry Hexaly's cases.

    python tools/hexaly_log_to_solution.py temp/Hexaly_SmallRoutes_9-2-26 --budget 600 \
        --date 2026-09-02

HOW A HEXALY LOG DIFFERS FROM A SimAnn LOG
    `Hexaly_VRP.py` prints the same per-route lines:
        0, {'Path': ['d1', 137, 48, 119, 142, 53, 69, 'd1'], 'Vehicle': 1, 'Cost': 97.45...}
    but it prints NO `Total cost:` line. Its banner reports only the objective, rounded:
        obj    =      3355.82
    so the objective is checked against that two-decimal value, and the cost breakdown is derived
    from the routes rather than cross-checked. There are no iteration or reheat counters in the
    SimAnn sense; the iteration count is taken from the final progress line instead.

    Hexaly also pads the dump to a fixed route count with empty depot-to-depot routes. Those are
    dropped, exactly as the existing solutions/*.json files hold only real routes.

    ROUTE ORDER IS NOT MEANINGFUL. Hexaly reports routes unordered, so the routes of one vehicle
    are neither consecutive nor chained depot to depot the way SimAnn_VRP.py's output is. A
    warm-start loader must order the routes per vehicle itself before loading such a file.
    Benjamin verified by hand that a feasible ordering exists per vehicle.

WHAT IT VERIFIES, BEFORE WRITING ANYTHING
    The instance is rebuilt here from `numpy_seed`, independently of the run. Then:
      * every customer appears exactly once,
      * no route exceeds vehicle capacity,
      * each route's logged cost equals the cost recomputed from the geometry,
      * the objective rebuilt from the routes agrees with the one rounded value Hexaly prints.
    A solution that fails any check is NOT written.

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
# The objective, rounded to two decimals, from Hexaly's end-of-run banner.
OBJECTIVE_RE = re.compile(r"^\s*obj\s+=\s+(\S+)\s*$")
# A progress line: "[178 sec, 6553305 itr]:      3355.82"
PROGRESS_RE = re.compile(r"^\[\s*(\d+) sec,\s*(\d+) itr\]:\s+(\S+)\s*$")


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
    """Collect the route dump, the rounded objective, and the progress trace."""
    routes: list[dict] = []
    rounded_objective: float | None = None
    progress: list[tuple[int, int, float]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            m = ROUTE_RE.match(line)
            if m:
                routes.append(ast.literal_eval(m.group(1)))
                continue
            m = PROGRESS_RE.match(line)
            if m:
                progress.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
                continue
            m = OBJECTIVE_RE.match(line)
            if m:
                rounded_objective = float(m.group(1))
    if not routes:
        sys.exit(f"{path}: no route dump found. The run must finish for its routes to print.")
    if rounded_objective is None:
        sys.exit(f"{path}: no 'obj = ' line found. Without it there is nothing to check the "
                 f"routes against.")
    return {"routes": routes, "rounded_objective": rounded_objective, "progress": progress}


def first_reached(progress: list[tuple[int, int, float]],
                  objective: float) -> tuple[int | None, int | None]:
    """Seconds and iterations at which the final objective was first printed."""
    for (seconds, iterations, value) in progress:
        if abs(value - objective) < 0.005:
            return seconds, iterations
    return None, None


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
        if not path:
            continue                                  # Hexaly's padding. See the module docstring.
        records.append({"vehicle": vehicle, "start_depot": start,
                        "path": path, "end_depot": end})
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

    vehicle_cost = len(used_vehicles) * cost_per_vehicle
    depot_cost = len(used_depots) * cost_per_depot
    total = vehicle_cost + depot_cost + travel * unit_travel_cost
    # Half of the last printed place is the tightest check a two-decimal log supports.
    rounded = parsed["rounded_objective"]
    if abs(total - rounded) > 0.005:
        problems.append(f"objective {total} != logged {rounded} (rounded to 2 decimals)")

    if problems:
        print("VERIFICATION FAILED. Nothing written.", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        sys.exit(1)

    print(f"Verified against a freshly built instance: {len(cust)}/{len(cust)} customers covered "
          f"once, {overload} overload, per-route costs to 1e-9, objective to the log's 2 "
          f"printed decimals.")
    return records, {"vehicle_use_cost": vehicle_cost, "depot_use_cost": depot_cost,
                     "travel_cost": travel * unit_travel_cost}, overload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--budget", type=float, required=True, help="the run's time limit, seconds")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD the run was made")
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
    seconds, iterations = first_reached(parsed["progress"], parsed["rounded_objective"])
    total_iterations = parsed["progress"][-1][1] if parsed["progress"] else None

    doc = {
        "objective": objective,
        "breakdown": breakdown,
        "total_overload": overload,
        "found": {
            "solver": "Hexaly_VRP.py",
            "date": args.date,
            "budget_seconds": args.budget,
            "first_reached_seconds": seconds,
            "first_reached_iterations": iterations,
            "iterations": total_iterations,
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
        "route_order_is_meaningless": True,
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
