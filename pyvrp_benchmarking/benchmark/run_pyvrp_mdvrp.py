"""
Run PyVRP on a multi-depot chaining instance (see mdvrp.py).

MAPPING THE MODEL
-----------------
PyVRP turns out to express this repo's structure almost exactly:

  * `reload_depots` lets a vehicle empty and reload at a depot mid-route, so one
    PyVRP "route" is a chain of trips -- the same object as a vehicle owning an
    ordered list of routes in this repo's model. `Route.trips()` recovers the
    chain, each `Trip` carrying its own start and end depot.
  * `start_depot` / `end_depot` are per vehicle *type*, not per vehicle, so
    "a route may end at a different depot than it started from" is expressed by
    enumerating one vehicle type per (start, end) depot pair. With D depots that
    is D^2 types; the solver then picks which to use.
  * `fixed_cost` is charged per vehicle used, matching `cost_per_vehicle`.

Two things do NOT map, and are therefore excluded from the instances rather than
fudged: priced (rather than forbidden) capacity overload, and a per-depot usage
cost. PyVRP can express neither.

Distances go through the same integer matrix as the SA side: PyVRP is given an
explicit distance matrix built by `mdvrp.euc_2d`, not coordinates, so there is
no possibility of the two sides rounding differently.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdvrp import load, evaluate, euc_2d  # noqa: E402

from pyvrp import Model  # noqa: E402
from pyvrp.stop import MaxRuntime  # noqa: E402


def build(inst: dict):
    m = Model()
    # PyVRP >= 0.13 separates geometry from role: a Location is registered first,
    # then add_depot/add_client claim it. Depot.location is an index, not a point,
    # so add_edge takes the Location objects rather than the depots and clients.
    depot_locs = [m.add_location(x=loc[0], y=loc[1]) for loc in inst["depots"]]
    client_locs = [m.add_location(x=c["loc"][0], y=c["loc"][1])
                   for c in inst["customers"]]
    depots = [m.add_depot(loc) for loc in depot_locs]
    for loc, c in zip(client_locs, inst["customers"]):
        m.add_client(loc, delivery=c["demand"])
    locs = depot_locs + client_locs

    # One vehicle type per (start, end) depot pair, each able to reload anywhere.
    # num_available is the per-depot fleet: the cap is intentionally slack on
    # both sides, so fixed_cost decides the fleet size rather than the bound.
    for s in depots:
        for e in depots:
            m.add_vehicle_type(
                num_available=inst["vehicles_per_depot"],
                capacity=inst["capacity"],
                start_depot=s, end_depot=e,
                reload_depots=depots,
                fixed_cost=inst["cost_per_vehicle"],
                unit_distance_cost=inst["unit_travel_cost"],
            )

    # Explicit integer matrix -- identical arithmetic to the SA side.
    profile = m.profiles[0] if m.profiles else m.add_profile()
    for a in locs:
        for b in locs:
            m.add_edge(a, b, distance=euc_2d((a.x, a.y), (b.x, b.y)), profile=profile)

    return m, len(depots)


def extract(res) -> list[list[dict]]:
    """PyVRP Route (a chain of trips) -> the shared itinerary format.

    `Route.trips()` is gone in PyVRP 0.14; the chain is read from the schedule.
    Each activity carries the index of the trip it OPENS, so a route running k
    trips has k+1 depot activities: trip i starts at depot activity i and ends at
    depot activity i+1. Reading a trip's end as the last depot inside its own span
    instead returns its start depot, which silently converts every reload at a
    different depot into a chaining error.

    Activity `idx` is zero-based within its own kind -- depots 0..D-1, clients
    0..n-1 -- which is already the indexing `evaluate` expects.
    """
    itineraries = []
    for route in res.best.routes():
        opens_trip: dict[int, int] = {}
        visits: dict[int, list[int]] = defaultdict(list)
        for act in route.schedule():
            if act.is_depot():
                opens_trip[act.trip] = act.idx
            else:
                visits[act.trip].append(act.idx)
        itineraries.append([
            {"start": opens_trip[i], "end": opens_trip[i + 1], "visits": visits[i]}
            for i in range(route.num_trips())
        ])
    return itineraries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inst = load(args.instance)
    m, num_depots = build(inst)

    t0 = time.time()
    res = m.solve(stop=MaxRuntime(args.seconds), seed=args.seed, display=False)
    elapsed = time.time() - t0

    itineraries = extract(res)
    ev = evaluate(itineraries, inst)

    print(json.dumps({
        "solver": "pyvrp",
        "instance": inst["name"],
        "n": len(inst["customers"]),
        "depots": num_depots,
        "seed": args.seed,
        "seconds": args.seconds,
        "elapsed": round(elapsed, 2),
        "reported_objective": res.cost(),
        "cost": ev["cost"],
        "travel": ev["travel"],
        "vehicles_used": ev["vehicles_used"],
        "trips": ev["trips"],
        "fleet_cap": ev["fleet_cap"],
        "cross_depot_trips": sum(1 for it in itineraries for t in it
                                 if t["visits"] and t["start"] != t["end"]),
        "iterations": res.num_iterations,
        "feasible": res.is_feasible() and not ev["problems"],
        "problems": ev["problems"],
    }))


if __name__ == "__main__":
    main()
