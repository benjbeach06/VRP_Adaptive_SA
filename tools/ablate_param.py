"""Paired ablation of a single solver parameter, optionally from a deliberately bad start.

    tools/ablate_param.py --param explore_reward --values 0 1e-4 1e-6 1e-8 \
                          --runs 30 --seconds 300 --start dumb

Every arm sees the SAME seeds, and seeds are run BREADTH-FIRST across arms: seed 0 for all arms,
then seed 1 for all arms, and so on. Two reasons. Paired-on-seed removes the shared component of
run-to-run variance, and breadth-first means an interrupted run still has balanced arms rather than
a complete first arm and nothing else.

`--start dumb` uses `make_dumb_initial_solution`, which puts every customer in one route. On a
capacity-25 instance that begins around 1.07M, almost all of it overload penalty, so the solver has
to do real structural work before it can start refining. That is the regime where escaping local
optima matters, and therefore where an exploration mechanism should show up if it does anything.

Reports paired deltas against the FIRST value given, which should be the control.
"""
import argparse
import contextlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import tune                                        # noqa: E402
import SimAnn_VRP_Core_Model as CM                  # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver       # noqa: E402
from run_stamp import solver_stamp


def run_once(param: str, value: float, size: int, seed: int, seconds: float, start: str) -> dict:
    """One solve. Returns objective, overload and reheat count, or inf on failure."""
    CM.seed_solver_rng(seed)
    sln = tune.build_instance(size)
    kwargs = tune.solver_kwargs(tune.DEFAULTS)
    kwargs[param] = value
    try:
        solver = SimAnnVRPSolver(sln, max_time=seconds, **kwargs)
        with contextlib.redirect_stdout(io.StringIO()):
            if start == "dumb":
                solver.make_dumb_initial_solution()
            else:
                solver.make_initial_solution()
            solver.solve(debug_level=0)
        best = solver.best_objective
        if best != best or best == float("inf"):
            return {"objective": float("inf")}
        return {
            "objective": best,
            "final_overload": sln.total_overload(),
            "plateau_reheats": solver.num_plateau_reheats,
        }
    except Exception as exc:
        return {"objective": float("inf"), "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", default="explore_reward")
    ap.add_argument("--values", type=float, nargs="+", required=True,
                    help="first value is the CONTROL that deltas are measured against")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--capacity", type=int, default=25)
    ap.add_argument("--start", choices=["dumb", "nn"], default="dumb")
    ap.add_argument("--out", default="tools/ablate_param_results.json")
    args = ap.parse_args()

    tune.CAPACITY = args.capacity
    arms = args.values
    results: dict[float, list[dict]] = {v: [] for v in arms}

    total = len(arms) * args.runs
    print(f"{args.param}: {arms}")
    print(f"{len(arms)} arms x {args.runs} paired seeds x {args.seconds:g}s, "
          f"n={args.size} capacity={args.capacity}, start={args.start}")
    print(f"{total} runs, estimated {total * args.seconds / 3600:.1f} h\n", flush=True)

    started = time.time()
    for seed in range(args.runs):                       # breadth-first: balanced if interrupted
        row = []
        for value in arms:
            r = run_once(args.param, value, args.size, seed, args.seconds, args.start)
            results[value].append(r)
            row.append(f"{r['objective']:9.2f}" if r["objective"] != float("inf") else "     FAIL")
        done = (seed + 1) * len(arms)
        print(f"  seed {seed:>3}  " + "  ".join(row) +
              f"   [{done}/{total}, {(time.time()-started)/3600:.2f}h]", flush=True)
        Path(args.out).write_text(json.dumps(
            {"_solver": solver_stamp(), "config": vars(args),
             "results": {str(k): v for k, v in results.items()}}, indent=1))

    print("\n--- per arm ---")
    finite = {v: [r["objective"] for r in results[v] if r["objective"] != float("inf")] for v in arms}
    for v in arms:
        vals = finite[v]
        if not vals:
            print(f"  {v:<10g} ALL FAILED")
            continue
        infeasible = sum(1 for r in results[v] if r.get("final_overload", 0) > 0)
        reheats = [r.get("plateau_reheats", 0) for r in results[v] if r["objective"] != float("inf")]
        print(f"  {v:<10g} mean {statistics.fmean(vals):9.2f}  sd {statistics.stdev(vals) if len(vals)>1 else 0:7.2f}  "
              f"min {min(vals):9.2f}  n={len(vals)}  infeasible={infeasible}  "
              f"reheats~{statistics.median(reheats) if reheats else 0:.0f}")

    control = arms[0]
    print(f"\n--- paired vs control ({args.param}={control:g}), negative = better ---")
    for v in arms[1:]:
        pairs = [(a["objective"], b["objective"])
                 for a, b in zip(results[v], results[control])
                 if a["objective"] != float("inf") and b["objective"] != float("inf")]
        if len(pairs) < 2:
            print(f"  {v:<10g} too few paired runs")
            continue
        deltas = [a - b for a, b in pairs]
        mean = statistics.fmean(deltas)
        sem = statistics.stdev(deltas) / len(deltas) ** 0.5
        print(f"  {v:<10g} {mean:+9.2f} +/- {sem:6.2f}   {mean/sem if sem else 0:+5.1f} sigma   "
              f"won {sum(d < 0 for d in deltas)}/{len(deltas)}")

    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
