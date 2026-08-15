"""
Per-operator cost profiling across instance sizes.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
----------------------------------------
This measures the COST of one operator call, isolated from how often the solver chooses to make
that call. It deliberately does NOT use weighted selection: adaptive weights differ per instance
size, so a solver-driven measurement would blend cost scaling with selection dynamics and neither
could be read off the result. Every operator here gets the same number of proposals.

For "where does wall time actually go", multiply the cost here by the call counts the solver
already prints at the end of a run. The two measurements answer different questions.

WHY THE EXISTING STATS ARE NOT ENOUGH
-------------------------------------
Operator.mean_apply_time is (apply + the propose that produced the move) / applies. That is
correct for the scoring model, which prices a whole accepted move, but it hides how much of an
expensive operator is pricing versus mutation. This tool times propose, apply and revert
separately.

STATE
-----
Each proposal is applied and then reverted, so the solution is unchanged at the end of a cell and
every operator in that cell sees the same state. The invariant is checked, not assumed: a
structural signature is taken before and after each operator's loop, and a mismatch is reported as
a finding rather than silently skewing the next operator's numbers.

MEASUREMENT FLOOR
-----------------
perf_counter here resolves to 100ns (verified, despite the stale ~15ms comment in
SimAnn_VRP_Operators.py). Timing a 4us call therefore carries a few percent of granularity error,
which is why medians are reported alongside means and why --inject-cost exists: it spins a known
number of microseconds inside one operator's selection so you can confirm the harness sees a cost
it was told to expect. A profiler that cannot detect an injected cost cannot be trusted to detect
a real one.

USAGE
    python tools/profile_operators.py --sizes 10,100,1000,5000 --seeds 3 --proposals 20000
    python tools/profile_operators.py --sizes 100 --proposals 2000 --inject-cost RandomCustomerSwap:50
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import SimAnn_VRP_Core_Model as CM
from SimAnn_VRP_Core_Model import Customer, Depot, FullSolution, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver

RESERVOIR = 4000


def build_instance(num_customers: int, vehicles: int = 3) -> FullSolution:
    """Same construction tune.py uses, so sizes stay comparable with the tuning numbers."""
    np.random.seed(42)
    depots = [Depot(i, loc, 35, 1) for i, loc in enumerate([(10, 10), (50, 50), (90, 10)])]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(num_customers)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(vehicles):
        sln.add_vehicle(Vehicle(initial_depot=depots[i % len(depots)], i=i, capacity=25))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def structural_signature(sln: FullSolution) -> tuple:
    """
    Cheap from-scratch description of solution shape.

    Used to prove apply/revert round trips left the state where they found it. Route CONTENTS are
    included, not only counts -- a swap that reverted into the wrong position would keep every
    count identical.
    """
    routes = []
    for route in sln.all_routes:
        routes.append((
            route.start_depot.dID,
            tuple(customer.cID for customer in route.path),
            route.end_depot.dID,
        ))
    routes.sort()
    return (len(routes), tuple(routes))


@dataclass
class Samples:
    """Running stats plus a bounded reservoir, so medians survive without keeping every sample."""
    count: int = 0
    total: float = 0.0
    reservoir: list[float] = field(default_factory=list)
    _seen: int = 0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self._seen += 1
        if len(self.reservoir) < RESERVOIR:
            self.reservoir.append(value)
        else:
            j = random.randrange(self._seen)
            if j < RESERVOIR:
                self.reservoir[j] = value

    def summary(self) -> dict:
        if not self.count:
            return {"count": 0, "mean_us": None, "median_us": None, "p90_us": None}
        ordered = sorted(self.reservoir)
        return {
            "count": self.count,
            "mean_us": self.total / self.count * 1e6,
            "median_us": statistics.median(ordered) * 1e6,
            "p90_us": ordered[min(len(ordered) - 1, int(0.90 * len(ordered)))] * 1e6,
        }


def spin(microseconds: float) -> None:
    """Busy-wait. sleep() cannot resolve microseconds, and we want CPU time, not a yield."""
    target = microseconds / 1e6
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < target:
        pass


def profile_cell(size: int, seed: int, warm_seconds: float, proposals: int,
                 inject: tuple[str, float] | None, verbose: bool) -> dict:
    """One (size, seed, state) cell: every operator gets `proposals` proposals on one solution."""
    CM.seed_solver_rng(seed)
    sln = build_instance(size)
    solver = SimAnnVRPSolver(sln, max_time=max(warm_seconds, 1))

    t0 = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        solver.make_initial_solution()
    build_seconds = time.perf_counter() - t0

    warm_actual = 0.0
    if warm_seconds > 0:
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            solver.solve(debug_level=0)
        warm_actual = time.perf_counter() - t0

    operators = solver.operators
    if inject:
        target_name, micros = inject
        matches = [op for op in operators if type(op).__name__ == target_name]
        if not matches:
            raise SystemExit(f"--inject-cost names an operator not in the roster: {target_name}")
        victim = matches[0]
        original = victim._operand_selection_impl

        def slowed(*args, **kwargs):
            spin(micros)
            return original(*args, **kwargs)

        victim._operand_selection_impl = slowed

    routes = list(sln.all_routes)
    lengths = sorted(len(r.path) for r in routes) or [0]
    cell = {
        "size": size,
        "seed": seed,
        "warm_seconds_requested": warm_seconds,
        "warm_seconds_actual": round(warm_actual, 3),
        "build_seconds": round(build_seconds, 4),
        "objective": sln.solution_cost(),
        "num_routes": len(routes),
        "route_len_median": lengths[len(lengths) // 2],
        "route_len_max": lengths[-1],
        "proposals_requested": proposals,
        "operators": {},
        "findings": [],
    }

    for op in operators:
        name = type(op).__name__
        before = structural_signature(sln)

        propose_s, apply_s, revert_s = Samples(), Samples(), Samples()
        kinds = {"VALID": 0, "NOOP": 0, "INVALID": 0}
        errors: dict[str, int] = {}

        loop_t0 = time.perf_counter()
        for _ in range(proposals):
            try:
                t0 = time.perf_counter()
                move = op.propose()
                propose_s.add(time.perf_counter() - t0)
            except Exception as exc:  # surfaced, never swallowed -- see tune.py FAILURES
                key = f"propose {type(exc).__name__}: {exc}"
                errors[key] = errors.get(key, 0) + 1
                continue

            kinds[move.kind.name] = kinds.get(move.kind.name, 0) + 1
            if not move.is_actionable:
                continue

            try:
                if not move.already_applied:
                    t0 = time.perf_counter()
                    op.apply(move)
                    apply_s.add(time.perf_counter() - t0)
                if move.already_applied:
                    t0 = time.perf_counter()
                    op.revert(move)
                    revert_s.add(time.perf_counter() - t0)
            except Exception as exc:
                key = f"apply/revert {type(exc).__name__}: {exc}"
                errors[key] = errors.get(key, 0) + 1
        loop_seconds = time.perf_counter() - loop_t0

        after = structural_signature(sln)
        if before != after:
            cell["findings"].append(
                f"{name}: solution changed across its proposal loop, so later operators in this "
                f"cell saw a different state (routes {before[0]} -> {after[0]})")

        total = sum(kinds.values())
        cell["operators"][name] = {
            "evaluates_by_applying": bool(getattr(op.base_operator, "_evaluates_by_applying", False)),
            "propose": propose_s.summary(),
            "apply": apply_s.summary(),
            "revert": revert_s.summary(),
            "kinds": kinds,
            "actionable_pct": (100.0 * kinds["VALID"] / total) if total else 0.0,
            "loop_seconds": round(loop_seconds, 3),
            "errors": errors,
        }
        if errors:
            for key, n in errors.items():
                cell["findings"].append(f"{name}: {n} x {key}")

        if verbose:
            summary = cell["operators"][name]
            print(f"    {name:38} propose {summary['propose']['median_us'] or 0:8.2f}us  "
                  f"apply {summary['apply']['median_us'] or 0:8.2f}us  "
                  f"actionable {summary['actionable_pct']:5.1f}%", flush=True)

    return cell


def scaling_table(cells: list[dict], sizes: list[int], warm: float) -> list[dict]:
    """Median propose cost per operator per size, plus a log-log slope across the size range."""
    rows = []
    names = sorted({name for cell in cells for name in cell["operators"]})
    for name in names:
        row = {"operator": name, "by_size": {}}
        points = []
        for size in sizes:
            matching = [c["operators"][name] for c in cells
                        if c["size"] == size and c["warm_seconds_requested"] == warm
                        and name in c["operators"]]
            medians = [m["propose"]["median_us"] for m in matching if m["propose"]["median_us"]]
            actionable = [m["actionable_pct"] for m in matching]
            if medians:
                value = statistics.median(medians)
                row["by_size"][str(size)] = {
                    "propose_median_us": round(value, 3),
                    "actionable_pct": round(statistics.median(actionable), 1) if actionable else 0.0,
                }
                points.append((size, value))
        if len(points) >= 2:
            xs = [math.log(s) for s, _ in points]
            ys = [math.log(v) for _, v in points]
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            denom = sum((x - mx) ** 2 for x in xs)
            row["loglog_slope"] = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom, 3) if denom else None
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", default="10,100,1000,5000")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--proposals", type=int, default=20000)
    parser.add_argument("--warm-seconds", default="0",
                        help="Comma-separated solve budgets before profiling. 0 = straight off "
                             "make_initial_solution.")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "profile_results.json"))
    parser.add_argument("--inject-cost", default=None, metavar="OPERATOR:MICROSECONDS",
                        help="Harness self-check: spin N microseconds inside one operator's "
                             "operand selection and confirm the report shows it.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    warms = [float(w) for w in args.warm_seconds.split(",") if w.strip()]
    inject = None
    if args.inject_cost:
        target, _, micros = args.inject_cost.partition(":")
        inject = (target, float(micros))

    started = time.time()
    results = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sizes": sizes, "seeds": args.seeds, "proposals": args.proposals,
        "warm_seconds": warms, "inject_cost": args.inject_cost,
        "clock_resolution_s": time.get_clock_info("perf_counter").resolution,
        "cells": [],
    }

    total_cells = len(sizes) * len(warms) * args.seeds
    done = 0
    for warm in warms:
        for size in sizes:
            for seed in range(args.seeds):
                done += 1
                if not args.quiet:
                    print(f"[{done}/{total_cells}] size={size} seed={seed} warm={warm}s "
                          f"(elapsed {time.time() - started:.0f}s)", flush=True)
                cell = profile_cell(size, seed, warm, args.proposals, inject, not args.quiet)
                results["cells"].append(cell)
                # Written after every cell: a killed or misjudged run still leaves usable data.
                with open(args.out, "w") as handle:
                    json.dump(results, handle, indent=1)

    results["scaling"] = {str(w): scaling_table(results["cells"], sizes, w) for w in warms}
    results["elapsed_seconds"] = round(time.time() - started, 1)
    findings = [f for cell in results["cells"] for f in cell["findings"]]
    results["findings"] = findings
    with open(args.out, "w") as handle:
        json.dump(results, handle, indent=1)

    print(f"\nWrote {args.out} in {results['elapsed_seconds']}s across {len(results['cells'])} cells.")
    if findings:
        print(f"{len(findings)} FINDINGS:")
        for finding in findings[:20]:
            print(f"  - {finding}")
    else:
        print("No findings: every apply/revert round trip restored the solution exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
