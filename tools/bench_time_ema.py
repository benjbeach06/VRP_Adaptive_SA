"""Quick paired bench for the TIME-BASED weight EMA (`weight_time_constant`).

    .venv1/Scripts/python.exe tools/bench_time_ema.py --runs 5 --seconds 30

Control arm keeps the per-segment `reaction_factor`. Treatment arm decays each operator's weight by
its OWN time share: p = 1 - exp(-segment_time / tau). Same seed, same instance, both arms.

WHAT THIS BENCH CAN AND CANNOT ANSWER
-------------------------------------
It CANNOT answer "is the objective better". The trajectory study measured a noise floor near 8
objective units at 19 seeds on this instance. A short paired bench is far under that, and the
objective column below is printed only so it is not silently hidden. Treat it as UNDERPOWERED.

It CAN answer the mechanism question, because share and weight numbers average over millions of
proposals and resolve from very few runs:

  - Did the expensive operators lose weight relative to the cheap ones?
  - What effective wall-clock half-life did each operator actually experience?

The change exists so that 100 calls of an expensive operator decay it more than 100 calls of a cheap
one. The `wall_half_life` column is the direct readout of that: tau * ln2 / clock_share.
"""
import argparse
import contextlib
import io
import json
import math
import os
import sys


def operator_row(op, wall_seconds: float, tau: float) -> dict:
    """Per-operator numbers needed to judge the redistribution."""
    proposals = op._proposal_count
    applies = op._apply_count
    total_time = op._propose_time_total + op._apply_time_total
    share = (total_time / wall_seconds) if wall_seconds > 0 else 0.0
    return {
        "name": type(op).__name__,
        "proposals": proposals,
        "applies": applies,
        "seconds": total_time,
        "clock_share": share,
        "us_per_call": (total_time / (proposals + applies) * 1e6) if proposals + applies else 0.0,
        "useful": op.num_useful_calls,
        "noop": op.num_noop_calls,
        "invalid": op.num_invalid_calls,
        "improving": op.num_improving_calls,
        "weight": op.weight,
        "penalty": op.penalty,
        "scoring_cost": op.scoring_cost,
        # Wall-clock seconds for this operator's weight to decay by half, given the share it
        # actually took. Infinite share-free operators are reported as None.
        "wall_half_life": (tau * math.log(2.0) / share) if (tau > 0 and share > 0) else None,
    }


def run_one(mod, seed: int, size: int, seconds: float, tau: float) -> dict:
    """One solve. `tau` <= 0 selects the control arm."""
    CM, tune, SimAnnVRPSolver, _path_from = mod
    CM.seed_solver_rng(seed)
    sln = tune.build_instance(size)
    kwargs = tune.solver_kwargs(tune.DEFAULTS)
    solver = SimAnnVRPSolver(sln, max_time=seconds,
                             weight_time_constant=(tau if tau > 0 else -1), **kwargs)
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            solver.make_initial_solution()
            solver.solve(debug_level=0)
    except Exception as exc:                    # a failed run must not lose the pairing
        return {"seed": seed, "objective": float("inf"),
                "error": f"{type(exc).__name__}: {exc}"}

    path = _path_from(log.getvalue())
    iterations = path[-1][2] if path else 0
    return {
        "seed": seed,
        "objective": solver.best_objective,
        "iterations": iterations,
        "plateau_reheats": solver.num_plateau_reheats,
        "operators": [operator_row(op, seconds, tau) for op in solver.operators],
    }


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def summarize(runs: list[dict], tau: float) -> list[dict]:
    """Average each operator's row across seeds. Failed runs carry no operators and drop out."""
    by_name: dict[str, list[dict]] = {}
    for run in runs:
        for row in run.get("operators", []):
            by_name.setdefault(row["name"], []).append(row)
    out = []
    for name, rows in by_name.items():
        share = _mean([r["clock_share"] for r in rows])
        out.append({
            "name": name,
            "clock_share": share,
            "weight": _mean([r["weight"] for r in rows]),
            "penalty": _mean([r["penalty"] for r in rows]),
            "us_per_call": _mean([r["us_per_call"] for r in rows]),
            "improving": _mean([r["improving"] for r in rows]),
            "proposals": _mean([r["proposals"] for r in rows]),
            "wall_half_life": (tau * math.log(2.0) / share) if (tau > 0 and share > 0) else None,
        })
    out.sort(key=lambda r: r["clock_share"], reverse=True)
    return out


def print_arm(label: str, summary: list[dict], top: int) -> None:
    print(f"\n{label}")
    print(f"  {'operator':<38} {'clock%':>7} {'weight':>12} {'penalty':>8} "
          f"{'us/call':>9} {'impr/s':>9} {'half-life':>10}")
    for row in summary[:top]:
        half = row["wall_half_life"]
        half_text = f"{half:10.3f}" if half is not None else f"{'-':>10}"
        impr_per_s = row["improving"] / (row["clock_share"] * 1.0) if row["clock_share"] > 0 else 0.0
        print(f"  {row['name']:<38} {row['clock_share'] * 100:6.2f}% {row['weight']:12.4g} "
              f"{row['penalty']:8.4f} {row['us_per_call']:9.2f} {impr_per_s:9.1f} {half_text}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5, help="paired seeds")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--size", type=int, default=500, help="reference instance is 500 / capacity 400")
    ap.add_argument("--tau", type=float, default=0.019,
                    help="weight_time_constant, in seconds of the operator's OWN time")
    ap.add_argument("--top", type=int, default=10, help="operators shown, by clock share")
    ap.add_argument("--out", default=None, help="optional folder for results.json")
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for p in (root, os.path.join(root, "tools"), os.path.join(root, "tests")):
        sys.path.insert(0, p)

    import SimAnn_VRP_Core_Model as CM
    import tune
    from SimAnn_VRP_Solver import SimAnnVRPSolver
    from ablate_param import _path_from
    mod = (CM, tune, SimAnnVRPSolver, _path_from)

    print(f"time-EMA bench: {args.runs} paired seeds x {args.seconds:g}s, "
          f"n={args.size} capacity {tune.CAPACITY}, tau={args.tau:g}s", flush=True)
    print("OBJECTIVE IS UNDERPOWERED HERE. The noise floor on this instance is about 8 units at "
          "19 seeds.", flush=True)

    control, treatment = [], []
    # Seeds are the OUTER loop, so an interrupted bench still holds complete pairs.
    for seed in range(args.runs):
        c = run_one(mod, seed, args.size, args.seconds, tau=-1.0)
        t = run_one(mod, seed, args.size, args.seconds, tau=args.tau)
        control.append(c)
        treatment.append(t)
        print(f"  seed {seed:3d}  control {c['objective']:10.2f}  "
              f"time-EMA {t['objective']:10.2f}  "
              f"delta {t['objective'] - c['objective']:+8.2f}", flush=True)

    print_arm(f"CONTROL -- per-segment reaction_factor ({args.runs} seeds)",
              summarize(control, tau=-1.0), args.top)
    print_arm(f"TIME-EMA -- tau={args.tau:g}s ({args.runs} seeds)",
              summarize(treatment, tau=args.tau), args.top)

    pairs = [(t["objective"], c["objective"]) for t, c in zip(treatment, control)
             if t["objective"] != float("inf") and c["objective"] != float("inf")]
    if pairs:
        deltas = [t - c for t, c in pairs]
        mean_delta = sum(deltas) / len(deltas)
        spread = math.sqrt(sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)) if len(deltas) > 1 else 0.0
        stderr = spread / math.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
        print(f"\nobjective delta (time-EMA minus control): {mean_delta:+.2f} "
              f"+/- {stderr:.2f} over {len(deltas)} pairs. UNDERPOWERED -- see the header.")
        c_itr = _mean([r.get("iterations") for r in control])
        t_itr = _mean([r.get("iterations") for r in treatment])
        print(f"iterations: control {c_itr:,.0f}  time-EMA {t_itr:,.0f}  "
              f"({(t_itr / c_itr - 1) * 100:+.1f}%)" if c_itr else "")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
            json.dump({"config": {"runs": args.runs, "seconds": args.seconds, "size": args.size,
                                  "tau": args.tau, "capacity": tune.CAPACITY},
                       "control": control, "treatment": treatment}, f, indent=1)
        print(f"\nwrote {os.path.join(args.out, 'results.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
