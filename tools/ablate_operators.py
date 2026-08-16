"""
One-factor-at-a-time operator ablation, tied to problem size.

DESIGN

Every variant differs from the baseline roster in EXACTLY ONE way -- one operator removed, or one
operator's k changed. Nothing is varied jointly, so a difference is attributable.

Three deliberate choices, all of them about the noise floor rather than the operators:

1. BREADTH-FIRST OVER SEEDS. Seed 0 runs for every cell, then seed 1, and so on. The design stays
   balanced at every moment, so killing the run early costs replication rather than whole
   conditions. Depth-first would leave the last variants with no data at all.

2. ONE INSTANCE PER (size, seed), SHARED BY EVERY VARIANT. Variants are compared against the
   baseline on the SAME problem, which removes instance-to-instance variance from the comparison
   entirely. Only the solver trajectory differs.

3. REPLICATION OVER RUN LENGTH. This solver terminates on wall clock, so a fixed seed does not fix
   the trajectory: iteration count moves with machine load. A paired 60s A/B in this project could
   not separate a 15-unit difference across five seeds. More seeds is the only lever that helps.

WHAT IS NOT ABLATED

SplitRandomRoute, CombineRandomRoutes and ChangeRandomEndDepot are excluded on Benjamin's call:
they exist to repair infeasible or badly-shaped solutions, not to improve good ones. A run that
starts from a feasible greedy construction never exercises the case they are for, so a zero in
their acceptance column says "did not help here", not "useless". Ablating them would measure the
wrong thing.

USAGE
    python tools/ablate_operators.py --budget-hours 8
    python tools/ablate_operators.py --budget-hours 0.2 --sizes 50 --smoke
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import statistics
import sys
import time
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import SimAnn_VRP_Core_Model as CM
import SimAnn_VRP_Operators as OPS
from SimAnn_VRP_Core_Model import Customer, Depot, FullSolution, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver

# Excluded from ablation -- see module docstring.
REPAIR_OPERATORS = {"SplitRandomRoute", "CombineRandomRoutes", "ChangeRandomEndDepot"}

# k settings to try, per BestOfCandidates operator. The baseline value is skipped automatically.
K_SWEEP = {
    "CustomerBestOfkSwapInRandomRoute": (5, 10, 40),
    "CustomerBestOfkNeighborSwapInRandomRoute": (2, 10, 20),
}

# Candidate generators, so a k change reaches BOTH the generator's own cap and BestOfCandidates.k.
# Setting only the latter would silently cap a 20-candidate generator instead of widening it.
K_SOURCES = {
    "CustomerBestOfkSwapInRandomRoute": OPS.random_intra_route_swap_pairs,
    "CustomerBestOfkNeighborSwapInRandomRoute": OPS.neighbor_intra_route_swap_pairs,
}

NEIGHBOR_DRAW_SWEEP = (4, 16)

# Longer budgets for bigger instances; they need more iterations to say anything.
SECONDS_FOR_SIZE = {50: 10.0, 500: 15.0, 5000: 40.0}
DEFAULT_SECONDS = 20.0


def build_instance(num_customers: int, seed: int, capacity: int) -> FullSolution:
    """One instance per (size, seed). Every variant in that cell sees exactly this problem."""
    np.random.seed(10_000 + seed)
    depots = [Depot(i, loc, 35, 1) for i, loc in enumerate([(10, 10), (50, 50), (90, 10)])]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(num_customers)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(3):
        sln.add_vehicle(Vehicle(initial_depot=depots[i], i=i, capacity=capacity))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def baseline_roster_names() -> list[str]:
    probe = SimAnnVRPSolver(build_instance(10, 0, 400), max_time=1)
    return [type(op).__name__ for op in probe.operators]


def build_variants(roster: list[str]) -> list[dict]:
    """Every entry is baseline plus at most one change."""
    variants: list[dict] = [{"name": "baseline", "kind": "baseline"}]

    for name in roster:
        if name not in REPAIR_OPERATORS:
            variants.append({"name": f"drop:{name}", "kind": "drop", "operator": name})

    for name, values in K_SWEEP.items():
        if name not in roster:
            continue
        for k in values:
            variants.append({"name": f"k:{name}={k}", "kind": "k", "operator": name, "k": k})

    for draws in NEIGHBOR_DRAW_SWEEP:
        variants.append({"name": f"draws={draws}", "kind": "draws", "draws": draws})

    return variants


@contextlib.contextmanager
def neighbor_draws(value: int | None):
    """NEIGHBOR_ROUTE_DRAWS is module state, so it must be restored even when a run raises."""
    if value is None:
        yield
        return
    original = OPS.NEIGHBOR_ROUTE_DRAWS
    OPS.NEIGHBOR_ROUTE_DRAWS = value
    try:
        yield
    finally:
        OPS.NEIGHBOR_ROUTE_DRAWS = original


def run_cell(variant: dict, size: int, seed: int, seconds: float, capacity: int) -> dict:
    CM.seed_solver_rng(seed)
    sln = build_instance(size, seed, capacity)

    with neighbor_draws(variant.get("draws")):
        solver = SimAnnVRPSolver(sln, max_time=seconds, max_plateau_size=1800)

        if variant["kind"] == "drop":
            solver.operators = [op for op in solver.operators
                                if type(op).__name__ != variant["operator"]]
            assert len(solver.operators) > 0
        elif variant["kind"] == "k":
            target = next(op for op in solver.operators
                          if type(op).__name__ == variant["operator"])
            target.k = variant["k"]
            target.candidate_source = partial(K_SOURCES[variant["operator"]], k=variant["k"])

        started = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
            initial = sln.solution_cost()
            solver.solve(debug_level=0)
        wall = time.perf_counter() - started

    return {"variant": variant["name"], "size": size, "seed": seed,
            "objective": solver.best_objective, "initial": initial,
            "operators": len(solver.operators), "wall": round(wall, 2)}


def summarize(results: list[dict]) -> dict:
    """Per (variant, size): mean objective, and the paired delta against baseline."""
    by_key: dict[tuple[str, int], dict[int, float]] = {}
    for row in results:
        by_key.setdefault((row["variant"], row["size"]), {})[row["seed"]] = row["objective"]

    summary = []
    sizes = sorted({size for _, size in by_key})
    for size in sizes:
        base = by_key.get(("baseline", size), {})
        for (variant, cell_size), values in sorted(by_key.items()):
            if cell_size != size or variant == "baseline":
                continue
            # Paired on seed: the same instance and the same construction, so the only difference
            # is the roster. Unpaired means comparing across instances, which is far noisier.
            shared = sorted(set(values) & set(base))
            deltas = [values[s] - base[s] for s in shared]
            if not deltas:
                continue
            mean = statistics.fmean(deltas)
            sd = statistics.stdev(deltas) if len(deltas) > 1 else float("nan")
            sem = sd / len(deltas) ** 0.5 if len(deltas) > 1 else float("nan")
            summary.append({
                "size": size, "variant": variant, "n": len(deltas),
                "mean_delta_vs_baseline": round(mean, 3),
                "sem": round(sem, 3) if sem == sem else None,
                "sigma": round(mean / sem, 2) if sem == sem and sem > 0 else None,
                "baseline_mean": round(statistics.fmean(base[s] for s in shared), 2),
            })
    return {"paired_deltas": summary, "sizes": sizes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budget-hours", type=float, default=8.0)
    parser.add_argument("--sizes", default="50,500,5000")
    parser.add_argument("--capacity", type=int, default=400)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "ablation_results.json"))
    parser.add_argument("--smoke", action="store_true",
                        help="One seed, 2s per run, to prove every variant is constructible.")
    args = parser.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    roster = baseline_roster_names()
    variants = build_variants(roster)
    deadline = time.time() + args.budget_hours * 3600

    print(f"{len(variants)} variants x {len(sizes)} sizes = {len(variants) * len(sizes)} cells")
    print(f"roster of {len(roster)}; not ablated: {sorted(REPAIR_OPERATORS)}")
    per_round = sum(2.0 if args.smoke else SECONDS_FOR_SIZE.get(s, DEFAULT_SECONDS)
                    for s in sizes) * len(variants)
    print(f"~{per_round / 60:.1f} min per seed-round, budget {args.budget_hours:g}h "
          f"-> about {int(args.budget_hours * 3600 / per_round)} seeds\n")

    results: list[dict] = []
    failures: dict[str, int] = {}
    seed = 0
    stop = False

    while not stop:
        round_started = time.time()
        for size in sizes:
            seconds = 2.0 if args.smoke else SECONDS_FOR_SIZE.get(size, DEFAULT_SECONDS)
            for variant in variants:
                if time.time() >= deadline:
                    stop = True
                    break
                try:
                    results.append(run_cell(variant, size, seed, seconds, args.capacity))
                except Exception as exc:
                    key = f"{variant['name']} @ {size}: {type(exc).__name__}: {exc}"
                    failures[key] = failures.get(key, 0) + 1
                # Written every run: an overnight job that dies at hour 7 keeps its first 7 hours.
                with open(args.out, "w") as handle:
                    json.dump({"variants": [v["name"] for v in variants], "sizes": sizes,
                               "capacity": args.capacity, "seconds_for_size": SECONDS_FOR_SIZE,
                               "roster": roster, "not_ablated": sorted(REPAIR_OPERATORS),
                               "seeds_completed": seed, "failures": failures,
                               "results": results, "summary": summarize(results)},
                              handle, indent=1)
            if stop:
                break

        print(f"seed {seed} done in {(time.time() - round_started) / 60:.1f} min, "
              f"{len(results)} runs, {(deadline - time.time()) / 60:.0f} min left", flush=True)
        seed += 1
        if args.smoke and seed >= 1:
            break

    print(f"\n{len(results)} runs over {seed} seed-rounds -> {args.out}")
    if failures:
        print(f"{sum(failures.values())} FAILURES:")
        for key, count in list(failures.items())[:15]:
            print(f"  {count}x {key}")
    else:
        print("no failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
