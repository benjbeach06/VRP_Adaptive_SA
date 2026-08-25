"""Run an arm and record PER-OPERATOR statistics, not just the objective.

    .venv1/Scripts/python.exe tools/ablate_operator_stats.py --root <worktree> --arm 12 \
        --runs 19 --seconds 300 --size 500 --out <folder>

`ablate_trajectory.py` answers "did this commit solve better". This answers "where did the time go,
and what weight did each operator hold" -- which is the question the scoring rework exists to move.

The motivating case: under the old scoring `ReorderShortSpanExactly` at K=8 held the roster's highest
weight while taking about half the wall clock and producing 20.7 improving moves per second, against
`ReverseClosestPairTogether`'s 666. If the new pricing works, that operator should now be DEMOTED at
K=8 without anyone hand-setting a discount.

Share numbers are averages over millions of proposals, so they resolve from very few runs. The seed
count here is for the OBJECTIVE, which does not.
"""
import argparse
import contextlib
import io
import json
import os
import sys


def operator_row(op) -> dict:
    """Everything needed to judge whether this operator is priced correctly."""
    proposals = op._proposal_count
    applies = op._apply_count
    total_time = op._propose_time_total + op._apply_time_total
    return {
        "name": type(op).__name__,
        "family": [f.name for f in type(op).family],
        "proposals": proposals,
        "applies": applies,
        "seconds": total_time,
        "us_per_call": (total_time / (proposals + applies) * 1e6) if proposals + applies else 0.0,
        "useful": op.num_useful_calls,
        "noop": op.num_noop_calls,
        "invalid": op.num_invalid_calls,
        "improving": op.num_improving_calls,
        "weight": op.weight,
        "penalty": op.penalty,
        "improvement_estimate": op.improvement_estimate,
        "scoring_cost": op.scoring_cost,
        "max_span": getattr(op, "max_span", None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="repo or worktree to run from")
    ap.add_argument("--arm", type=int, default=0)
    ap.add_argument("--runs", type=int, default=19)
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--size", type=int, default=500)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--commit", default="", help="recorded so this folder plots with the others")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    for p in (root, os.path.join(root, "tools"), os.path.join(root, "tests")):
        sys.path.insert(0, p)

    import SimAnn_VRP_Core_Model as CM
    import tune
    from SimAnn_VRP_Solver import SimAnnVRPSolver
    from ablation_arms import apply_arm
    from ablate_param import _path_from        # same per-report capture the other arms use

    os.makedirs(args.out, exist_ok=True)
    label = args.label or f"arm{args.arm}"
    runs = []

    print(f"{label}: {args.runs} seeds x {args.seconds:g}s, n={args.size}, arm {args.arm}",
          flush=True)

    for seed in range(args.runs):
        CM.seed_solver_rng(seed)
        sln = tune.build_instance(args.size)
        kwargs = tune.solver_kwargs(tune.DEFAULTS)
        solver = SimAnnVRPSolver(sln, max_time=args.seconds, **kwargs)
        apply_arm(solver, args.arm)
        log = io.StringIO()
        try:
            with contextlib.redirect_stdout(log):
                solver.make_initial_solution()
                solver.solve(debug_level=0)
            row = {"seed": seed,
                   "objective": solver.best_objective,
                   "overload": sln.total_overload(),
                   "plateau_reheats": solver.num_plateau_reheats,
                   "path": _path_from(log.getvalue()),
                   "operators": [operator_row(op) for op in solver.operators]}
        except Exception as exc:                       # a failed run must not lose the study
            row = {"seed": seed, "objective": float("inf"),
                   "error": f"{type(exc).__name__}: {exc}"}
        runs.append(row)

        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
            json.dump({"commit": args.commit, "label": label, "arm": args.arm,
                       "config": {"size": args.size, "seconds": args.seconds,
                                  "start": "nn", "runs": args.runs, "root": root},
                       "runs": runs}, f, indent=1)
        print(f"  seed {seed:3d}  {row['objective']:10.2f}", flush=True)

    finite = [r["objective"] for r in runs if r["objective"] != float("inf")]
    if finite:
        print(f"\n{label}: mean {sum(finite) / len(finite):.2f} over {len(finite)} runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
