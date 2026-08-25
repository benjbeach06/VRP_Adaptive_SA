"""Two-arm ablation: the ORIGINAL scoring-rework stage-1 commit against a TUNED, time-based HEAD.

    .venv1/Scripts/python.exe tools/ablate_tuned_vs_stage1.py \
        --params experiment_logs/tuning/2026-08-23_chosen_center.json \
        --runs 15 --seconds 300 --size 500

Grounds tonight's entire trajectory -- rework stages 2-7, the time-based EMA and schedule
conversion, and the 8-hour parameter search -- against where the scoring rework started. Not a
parameter-only comparison: STAGE1 arm is a real code checkout at c539a1e, run at that commit's own
tune.py DEFAULTS (the same machinery tools/ablate_trajectory.py's "02_stage1_magnetism" arm already
used and validated). TUNED arm is a worktree pinned to the commit that landed tonight's schedule
conversion, run with the chosen center-of-good-region params from tools/pick_tuned_center.py.

Seeds are the OUTER loop, so an interrupted study still has both arms at the same seed count.
Each arm's runs are appended to its own results.json after every run.

Reads the tune's chosen params from a JSON FILE (--params), never inline -- see
tools/pick_tuned_center.py, which builds that file. Never argmin: the file records which trial and
what bucket it came from.
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAGE1_COMMIT = "c539a1e"

STAGE1_RUNNER = (
    "import json,sys;"
    "sys.path.insert(0,r'{root}');"
    "sys.path.insert(0,r'{root}/tools');"
    "sys.path.insert(0,r'{root}/tests');"
    "from ablate_param import run_once;"
    "from ablation_arms import apply_arm;"
    "r=run_once('ablation_arm',0.0,{size},{seed},{seconds},'nn',apply_arm);"
    "print('@@RESULT@@'+json.dumps(r))"
)

TUNED_RUNNER = (
    "import contextlib,io,json,sys;"
    "sys.path.insert(0,r'{root}');"
    "sys.path.insert(0,r'{root}/tools');"
    "import SimAnn_VRP_Core_Model as CM;"
    "import tune;"
    "from SimAnn_VRP_Solver import SimAnnVRPSolver;"
    "from ablate_param import _path_from;"
    "params={params_json};"
    "CM.seed_solver_rng({seed});"
    "sln=tune.build_instance({size});"
    "kwargs=tune.solver_kwargs(params);"
    "solver=SimAnnVRPSolver(sln,max_time={seconds},**kwargs);"
    "log=io.StringIO();"
    "ctx=contextlib.redirect_stdout(log);"
    "ctx.__enter__();"
    "solver.make_initial_solution();"
    "solver.solve(debug_level=0);"
    "ctx.__exit__(None,None,None);"
    "best=solver.best_objective;"
    "r={{'objective': best if (best==best and best!=float('inf')) else float('inf'),"
    "'final_overload': sln.total_overload(),"
    "'plateau_reheats': solver.num_plateau_reheats,"
    "'path': _path_from(log.getvalue())}};"
    "print('@@RESULT@@'+json.dumps(r))"
)


def one_run(python: str, code: str, seconds: float) -> dict:
    out = subprocess.run([python, "-c", code], capture_output=True, text=True,
                         timeout=seconds + 600)
    for line in out.stdout.splitlines():
        if line.startswith("@@RESULT@@"):
            return json.loads(line[len("@@RESULT@@"):])
    return {"objective": float("inf"), "error": (out.stderr or out.stdout)[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True, nargs="+",
                    help="one or more JSON param files; each becomes its own tuned_<stem> arm, "
                         "all pinned to the SAME tuned commit")
    ap.add_argument("--tuned-commit", default=None,
                    help="commit to pin every tuned arm to; default is HEAD right now")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--size", type=int, default=500)
    ap.add_argument("--out", default=None)
    ap.add_argument("--worktrees", default=None)
    args = ap.parse_args()

    tuned_params: dict[str, dict] = {}
    for path in args.params:
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            tuned_params[f"tuned_{stem}"] = json.load(f)

    tuned_commit = args.tuned_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()

    python = sys.executable
    out_root = args.out or os.path.join(
        ROOT, "experiment_logs", "ablations", "2026-08-23_tuned_vs_stage1")
    wt_root = args.worktrees or os.path.join(out_root, "_worktrees")
    os.makedirs(out_root, exist_ok=True)
    os.makedirs(wt_root, exist_ok=True)

    arms = [("post_stage1", STAGE1_COMMIT)] + [(label, tuned_commit) for label in tuned_params]
    roots = {}
    for label, commit in arms:
        path = os.path.join(wt_root, label)
        if not os.path.isdir(path):
            subprocess.run(["git", "worktree", "add", "--detach", path, commit],
                           cwd=ROOT, capture_output=True, text=True, check=True)
        roots[label] = path
        os.makedirs(os.path.join(out_root, label), exist_ok=True)

    results = {label: [] for label, _ in arms}
    total = args.runs * len(arms)
    done = 0
    started = time.time()
    print(f"{len(arms)} arms: post_stage1 ({STAGE1_COMMIT}) vs "
          f"{', '.join(tuned_params)} (all {tuned_commit[:10]}) -- "
          f"{args.runs} paired seeds x {args.seconds:g}s, n={args.size}", flush=True)
    for label, p in tuned_params.items():
        print(f"  {label}: {p}", flush=True)
    print(f"estimated {total * args.seconds / 3600:.2f} h of solve time", flush=True)

    for seed in range(args.runs):                    # seeds OUTER, so arms stay paired
        row = []
        for label, commit in arms:
            root = roots[label]
            if label == "post_stage1":
                code = STAGE1_RUNNER.format(root=root.replace("\\", "/"),
                                            size=args.size, seed=seed, seconds=args.seconds)
            else:
                code = TUNED_RUNNER.format(root=root.replace("\\", "/"),
                                           size=args.size, seed=seed, seconds=args.seconds,
                                           params_json=json.dumps(tuned_params[label]))
            r = one_run(python, code, args.seconds)
            results[label].append(dict(r, seed=seed))
            with open(os.path.join(out_root, label, "results.json"), "w", encoding="utf-8") as f:
                json.dump({"commit": commit, "label": label,
                           "config": {"size": args.size, "seconds": args.seconds,
                                      "runs": args.runs,
                                      "params": tuned_params.get(label)},
                           "runs": results[label]}, f, indent=1)
            done += 1
            row.append(f"{r['objective']:10.2f}" if r["objective"] != float("inf") else "       inf")
        elapsed = (time.time() - started) / 3600
        print(f"  seed {seed:3d}  " + "  ".join(row) + f"   [{done}/{total}, {elapsed:.2f}h]",
              flush=True)

    print("\n--- summary ---", flush=True)
    base = [r["objective"] for r in results["post_stage1"]]
    finite_base = [b for b in base if b != float("inf")]
    print(f"  post_stage1  mean {sum(finite_base) / len(finite_base):9.2f}  n={len(finite_base)}")
    for label in tuned_params:
        vals = [r["objective"] for r in results[label]]
        finite = [v for v in vals if v != float("inf")]
        note = ""
        if finite:
            print(f"  {label:<24} mean {sum(finite) / len(finite):9.2f}  n={len(finite)}")
        pairs = [(t, b) for t, b in zip(vals, base) if t != float("inf") and b != float("inf")]
        if len(pairs) > 1:
            deltas = [t - b for t, b in pairs]        # negative = tuned is BETTER
            m = sum(deltas) / len(deltas)
            var = sum((d - m) ** 2 for d in deltas) / (len(deltas) - 1)
            sem = (var / len(deltas)) ** 0.5
            won = sum(d < 0 for d in deltas)
            print(f"    {label} minus post_stage1: {m:+8.2f} +/- {sem:5.2f}   "
                  f"{m / sem if sem else 0:+5.1f} sigma   {label} won {won}/{len(deltas)}")

    print(f"\nwritten under {out_root}", flush=True)
    print("worktrees left in place for re-runs; remove with: git worktree remove <path> --force",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
