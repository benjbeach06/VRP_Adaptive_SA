"""Print the operator family tree, and what each operator would be drawn at.

    .venv1/Scripts/python.exe tools/family_tree.py [--draws 400000]

Design docs quote counts and shares that drift as operators are added, so they carry a roster
stamp and tell the reader to re-measure. This is the re-measurement.

Two columns matter. `equal-w` is the share every operator gets when all weights are equal, which
is the plateau state -- it shows what TREE POSITION alone is worth, with the floors active. `flat`
is what a single draw over the roster would have given the same operator. The gap between them is
the allocation change the tree makes.
"""
import argparse
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from _harness import random_instance                       # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver, FAMILY_FLOOR  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=400_000)
    ap.add_argument("--customers", type=int, default=200)
    ap.add_argument("--vehicles", type=int, default=40)
    ap.add_argument("--capacity", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260819)
    args = ap.parse_args()

    sln = random_instance(seed=args.seed, n_customers=args.customers,
                          n_vehicles=args.vehicles, capacity=args.capacity)
    solver = SimAnnVRPSolver(sln)
    solver.make_initial_solution()

    # Equal weights: the plateau state, where tree position is the only thing deciding.
    for op in solver.operators:
        solver.adj_weights[op] = 1.0
    solver.refresh_family_tree()

    counts = collections.Counter(solver.choose_operator() for _ in range(args.draws))
    share = {op: counts[op] / args.draws * 100 for op in solver.operators}
    flat = 100 / len(solver.operators)

    paths = {op: op.family for op in solver.operators}
    kids = collections.defaultdict(set)
    for path in paths.values():
        for d in range(len(path)):
            kids[path[:d]].add(path[:d + 1])

    print(f"{len(solver.operators)} operators, {len(kids[()])} root families, "
          f"{args.draws:,} draws at equal weight")
    print(f"{'':<44}{'ops':>5}{'equal-w':>10}{'floor':>8}")

    def show(prefix, indent=0):
        for child in sorted(kids[prefix], key=lambda c: c[-1].value):
            members = [op for op, p in paths.items() if p[:len(child)] == child]
            total = sum(share[op] for op in members)
            floor = f"{FAMILY_FLOOR[child[0]]:>7.2f}" if len(child) == 1 else ""
            print(f"{'  ' * indent + child[-1].name:<44}{len(members):>5}{total:>9.2f}%{floor}")
            if kids[child]:
                show(child, indent + 1)
            else:
                for op in sorted(members, key=lambda o: -share[o]):
                    name = type(op).__name__
                    print(f"{'  ' * (indent + 1) + name:<44}{'':>5}{share[op]:>9.2f}%")

    show(())
    print(f"\nflat selection would give every operator {flat:.2f}%")
    print(f"floors sum to {sum(FAMILY_FLOOR.values()):.2f}")


if __name__ == "__main__":
    main()
