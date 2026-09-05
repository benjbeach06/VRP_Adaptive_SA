"""
Run PyVRP (hybrid genetic search) on a CVRPLIB instance and emit one JSON line.

PyVRP is compiled C++ with a Python front end, so this is not an apples-to-apples
*algorithmic* comparison against a pure-Python solver. It answers the question
that actually matters for a heuristic with no external benchmark: given the same
wall clock on the same machine, how far off is it? Iteration counts are reported
on both sides so the implementation-language gap stays visible.

Runs in its own virtualenv (see setup.sh) because PyVRP ships wheels for
released CPython versions, which may not include whatever the solver needs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cvrplib import read_instance, verify_routes  # noqa: E402

from pyvrp import read, solve, Model, ProblemData  # noqa: E402
from pyvrp.stop import MaxRuntime  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inst = read_instance(args.instance)          # our reader, for verification

    # round_func MUST be given. PyVRP's default is "none", which TRUNCATES
    # (429.857 -> 429); TSPLIB EUC_2D is nint (-> 430). Truncating undercounts by
    # about half a unit per edge, which scores PyVRP BELOW the proven optimum on
    # solved instances and makes the gap column meaningless.
    data = read(args.instance, round_func="round")

    model = Model.from_data(data)

    t0 = time.time()
    res = model.solve(stop=MaxRuntime(args.seconds), seed=args.seed, display=False)
    elapsed = time.time() - t0

    print("feasible:", res.best.is_feasible(), file=sys.stderr)
    print("cost:", res.best.distance(), file=sys.stderr)
    print("routes:", res.best.num_routes(), file=sys.stderr)

    # Verify PyVRP's answer with the same geometry check applied to the SA solver,
    # so neither side is trusted about its own objective.
    #
    # Iterating a Route yields ScheduledActivity, not clients. Each activity carries
    # `idx`, which is ZERO-based within its own kind: depots 0..D-1, clients 0..n-1.
    # `is_client()` is a method, so it must be called -- the bound method alone is
    # always truthy and lets the depot through.
    depot_node = inst["depot"]
    customer_nodes = sorted(k for k in inst["coords"] if k != depot_node)
    node_of = dict(enumerate(customer_nodes))
    routes = [[node_of[a.idx] for a in route if a.is_client()]
              for route in res.best.routes()]
    verified, problems = verify_routes(routes, inst)

    print(json.dumps({
        "solver": "pyvrp",
        "instance": inst["name"],
        "n": inst["n_customers"],
        "capacity": inst["capacity"],
        "seed": args.seed,
        "seconds": args.seconds,
        "elapsed": round(elapsed, 2),
        # distance(), not cost(): the best-known values are pure travel, while
        # cost() adds fixed vehicle cost and any infeasibility penalty.
        "reported_objective": res.best.distance(),
        "cost": verified,          # recomputed from geometry, never PyVRP's own number
        "routes": res.best.num_routes(),
        "iterations": res.num_iterations,
        "feasible": res.is_feasible() and not problems,
        "problems": problems,
    }))


if __name__ == "__main__":
    main()
