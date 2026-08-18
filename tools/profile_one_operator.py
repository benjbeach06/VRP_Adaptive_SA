"""
Profile ONE operator under pyinstrument, with the roster isolated in code.

Isolating in code rather than by commenting out the roster keeps SimAnn_VRP.py untouched and
makes the isolation a checked fact: the driver asserts the surviving roster is exactly the
requested operator before it starts sampling.

WHY ISOLATION MATTERS FOR READING THE TREE
pyinstrument labels a frame with a class name, but methods defined on a base class are shared by
every subclass -- Operator.propose, OperatorBL.evaluate. In a full-roster profile those frames
carry ONE arbitrary subclass's name while covering the work of many, so a subtree can appear to
belong to an operator that never ran. With exactly one operator in the roster that ambiguity is
gone: anything in the tree belongs to the operator under study.

USAGE
    python tools/profile_one_operator.py CustomerBestOfkSwapInRandomRoute
    python tools/profile_one_operator.py SwapRouteTailsAtSharedDepot --seconds 30
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pyinstrument import Profiler

import SimAnn_VRP_Core_Model as CM
from SimAnn_VRP_Core_Model import Customer, Depot, FullSolution, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver


def build_benjamins_instance() -> FullSolution:
    """The instance from SimAnn_VRP.py, rebuilt here so profiling never edits that file."""
    np.random.seed(42)
    depot_data = [((10, 10), 35), ((50, 50), 35), ((90, 10), 35)]
    depots = [Depot(i, loc, limit, 1) for i, (loc, limit) in enumerate(depot_data)]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(200)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(3):
        sln.add_vehicle(Vehicle(initial_depot=depots[i], i=i, capacity=25))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operator")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.0005)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--all-operators", action="store_true",
                        help="Do not isolate. Profiles the whole roster; base-class frames then "
                             "carry one arbitrary subclass name, so read labels with care.")
    args = parser.parse_args()

    CM.seed_solver_rng(args.seed)
    sln = build_benjamins_instance()
    solver = SimAnnVRPSolver(sln, max_time=args.seconds, max_plateau_size=1800)

    available = [type(op).__name__ for op in solver.operators]
    if args.operator not in available:
        print(f"'{args.operator}' is not in the roster. Available:")
        for name in available:
            print(f"  {name}")
        return 1

    if not args.all_operators:
        solver.operators = [op for op in solver.operators
                            if type(op).__name__ == args.operator]
        # Checked, not assumed. Every conclusion below depends on this being true.
        surviving = [type(op).__name__ for op in solver.operators]
        assert surviving == [args.operator], f"isolation failed, roster is {surviving}"
        print(f"Roster isolated to {surviving[0]} (of {len(available)} available)")
    else:
        print(f"Profiling the FULL roster of {len(available)} operators")

    solver_output = io.StringIO()
    profiler = Profiler(interval=args.interval)

    t0 = time.perf_counter()
    profiler.start()
    with contextlib.redirect_stdout(solver_output):
        solver.make_initial_solution()
        solver.solve(debug_level=0)
    profiler.stop()
    wall = time.perf_counter() - t0

    stem = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"profile_{args.operator}")
    tree = profiler.output_text(unicode=False, color=False, show_all=False)
    with open(stem + ".txt", "w", encoding="utf-8") as handle:
        handle.write(tree)
    with open(stem + ".html", "w", encoding="utf-8") as handle:
        handle.write(profiler.output_html())

    print(tree)
    print(f"wall {wall:.1f}s   best objective {solver.best_objective:.2f}")

    op = solver.operators[0] if not args.all_operators else None
    if op is not None:
        proposals = op._proposal_count
        print(f"{args.operator}: {proposals} proposals, "
              f"{op.mean_propose_time * 1e6:.1f}us each under the sampler")
        print("Compare that against the uninstrumented baseline in experiment_logs/profile_cold.json. "
              "A sampling profiler should barely move it; a large gap means the profile is "
              "measuring itself.")
    print(f"\nhtml -> {stem}.html\ntext -> {stem}.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
