"""
Multi-depot / route-chaining instances: generator, format, and a shared evaluator.

THE SETTING
-----------
This is the problem this repo's model was actually built for, rather than the
single-depot CVRP restriction used in the CVRPLIB harness:

  * several depots;
  * a vehicle runs a *chain* of routes -- each route begins at the depot where
    the previous one ended, so a vehicle's day crosses depots;
  * a route may end at a depot other than the one it started from;
  * a fixed cost is charged per vehicle used, so the solver trades routing cost
    against fleet size.

Capacity is a hard constraint here and `cost_per_depot` is 0 -- not because the
model can't price them, but because PyVRP cannot express either, and a benchmark
where the two solvers optimise different objectives measures nothing. Those two
features stay outside the comparison; see `MDVRP_RESULTS.md`.

Objective (both solvers, identical):

    unit_travel_cost * total_distance  +  cost_per_vehicle * vehicles_used

Distances are integer-rounded (TSPLIB `EUC_2D` convention) so both sides
arithmetic on exactly the same matrix and totals are exact.

THE SOLUTION FORMAT
-------------------
A solution is a list of vehicle itineraries. Each itinerary is a list of trips;
each trip is `{"start": depot_idx, "end": depot_idx, "visits": [customer_idx]}`.
Consecutive trips must chain (`trip[i].end == trip[i+1].start`). Both solvers
emit this, and `evaluate` scores it without trusting either.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path


def euc_2d(a, b) -> int:
    """TSPLIB EUC_2D: nint(euclidean), half away from zero."""
    return int(math.hypot(b[0] - a[0], b[1] - a[1]) + 0.5)


# --------------------------------------------------------------------- generate
def generate(name: str, *, num_customers: int, num_depots: int, capacity: int,
             cost_per_vehicle: int, vehicles_per_depot: int, seed: int,
             grid: int = 1000, cluster: bool = True) -> dict:
    """Generate a multi-depot instance.

    Depots are spread around the grid rather than placed randomly, so that a
    route ending at a *different* depot is genuinely useful -- on a single
    cluster of co-located depots the chaining feature has nothing to exploit
    and the instance would not test what it claims to.

    `cluster=True` seeds customers around a handful of centres. Uniform points
    make depot assignment nearly arbitrary; clustered ones give the multi-depot
    structure something to get right or wrong.
    """
    rng = random.Random(seed)

    # Depots on a circle inscribed in the grid: maximally spread, deterministic.
    cx = cy = grid / 2
    r = grid * 0.34
    depots = [(round(cx + r * math.cos(2 * math.pi * i / num_depots)),
               round(cy + r * math.sin(2 * math.pi * i / num_depots)))
              for i in range(num_depots)]

    customers = []
    if cluster:
        n_centres = max(3, num_customers // 40)
        centres = [(rng.uniform(0, grid), rng.uniform(0, grid)) for _ in range(n_centres)]
        spread = grid * 0.075
        for _ in range(num_customers):
            ox, oy = centres[rng.randrange(n_centres)]
            x = min(grid, max(0, round(rng.gauss(ox, spread))))
            y = min(grid, max(0, round(rng.gauss(oy, spread))))
            customers.append({"loc": [x, y], "demand": rng.randint(1, 10)})
    else:
        for _ in range(num_customers):
            customers.append({"loc": [rng.randrange(grid + 1), rng.randrange(grid + 1)],
                              "demand": rng.randint(1, 10)})

    return {
        "name": name,
        "depots": [list(d) for d in depots],
        "customers": customers,
        "capacity": capacity,
        "cost_per_vehicle": cost_per_vehicle,
        "unit_travel_cost": 1,
        "vehicles_per_depot": vehicles_per_depot,
        "seed": seed,
        "clustered": cluster,
    }


def save(inst: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(inst, indent=1))


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------- evaluate
def evaluate(itineraries: list[list[dict]], inst: dict) -> dict:
    """Score a solution from raw geometry. Trusts neither solver's bookkeeping.

    Returns {cost, travel, vehicles_used, trips, problems}. A non-empty
    `problems` means the solution is invalid and its cost is meaningless.
    """
    depots = [tuple(d) for d in inst["depots"]]
    custs = [tuple(c["loc"]) for c in inst["customers"]]
    dem = [c["demand"] for c in inst["customers"]]
    cap = inst["capacity"]
    n = len(custs)

    problems: list[str] = []
    seen: set[int] = set()
    travel = 0
    used = 0
    trips = 0

    for v, itin in enumerate(itineraries):
        nonempty = [t for t in itin if t["visits"]]
        if not nonempty:
            continue
        used += 1

        # Chaining: each trip must start where the previous one ended.
        for a, b in zip(itin, itin[1:]):
            if a["end"] != b["start"]:
                problems.append(
                    f"vehicle {v}: trip ends at depot {a['end']} but next starts at {b['start']}")

        for t in itin:
            if not t["visits"]:
                continue
            trips += 1
            load = sum(dem[c] for c in t["visits"])
            if load > cap:
                problems.append(f"vehicle {v}: trip load {load} > capacity {cap}")
            pts = ([depots[t["start"]]] + [custs[c] for c in t["visits"]]
                   + [depots[t["end"]]])
            travel += sum(euc_2d(p, q) for p, q in zip(pts, pts[1:]))
            for c in t["visits"]:
                if c in seen:
                    problems.append(f"customer {c} visited more than once")
                seen.add(c)

    if len(seen) != n:
        problems.append(f"covered {len(seen)} of {n} customers")

    fleet_cap = len(depots) * inst["vehicles_per_depot"]
    if used > fleet_cap:
        problems.append(f"used {used} vehicles, fleet is {fleet_cap}")

    return {
        "cost": travel * inst["unit_travel_cost"] + used * inst["cost_per_vehicle"],
        "travel": travel,
        "vehicles_used": used,
        "trips": trips,
        "fleet_cap": fleet_cap,
        "problems": problems,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="generate the MDVRP instance set")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "instances" / "MDVRP"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # A size/shape ladder. Capacity is set so a vehicle needs several trips to
    # clear its share -- that is what makes route chaining load-bearing rather
    # than decorative. vehicles_per_depot is deliberately generous so the fleet
    # cap never binds and cost_per_vehicle alone decides how many are used.
    SPEC = [
        # name                 n     depots  cap   fixed  veh/depot
        ("md-n100-d3",        100,   3,      60,   200,   6),
        ("md-n200-d3",        200,   3,      60,   200,   10),
        ("md-n200-d5",        200,   5,      60,   200,   8),
        ("md-n400-d4",        400,   4,      80,   250,   14),
        ("md-n600-d5",        600,   5,      80,   250,   18),
        ("md-n1000-d6",      1000,   6,     100,   300,   22),
    ]
    for i, (name, n, d, cap, fixed, vpd) in enumerate(SPEC):
        inst = generate(name, num_customers=n, num_depots=d, capacity=cap,
                        cost_per_vehicle=fixed, vehicles_per_depot=vpd, seed=1000 + i)
        save(inst, out / f"{name}.json")
        total = sum(c["demand"] for c in inst["customers"])
        print(f"{name:<14} n={n:<5} depots={d}  cap={cap:<4} fixed={fixed:<4} "
              f"total demand={total:<6} min trips={math.ceil(total/cap)}")
