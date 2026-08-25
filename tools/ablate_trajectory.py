"""Ablate a SEQUENCE OF COMMITS against each other, not values of one parameter.

    .venv1/Scripts/python.exe tools/ablate_trajectory.py --runs 19 --seconds 300 --size 500

`ablate_param.py` varies a parameter inside one code version. This varies the code version itself:
each arm is a git worktree pinned to a checkpoint commit, running the identical solver call.

**Seeds are the OUTER loop.** Every arm runs seed 0 before any arm runs seed 1, so an interrupted
study still has every arm at the same seed count and stays paired. Finishing one arm at a time would
leave the last arms with no data at all.

Each arm's runs are appended to its own `results.json` after every completed run, so a crash loses
at most one run.

Arms are defined in ARMS below. Each is one PERFORMANCE stage; a stage that cannot change behaviour
is squashed into its successor and does not get an arm.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worktrees import ensure as ensure_worktree     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# label -> commit. Order is chronological; the first is the baseline the rest are read against.
ARMS = [
    ("01_pre_stage1", "8d89ad1"),
    ("02_stage1_magnetism", "c539a1e"),
    ("03_stage2_no_penalty_factor", "30c6b07"),
    ("04_stages34_dynamic_penalty", "6e89e5b"),
    ("05_stage5_valid_cost", "fbe7b9d"),
    ("06_stages67_head", "6940351"),
]

RUNNER = (
    "import json,sys;"
    "sys.path.insert(0,r'{root}');"
    "sys.path.insert(0,r'{root}/tools');"
    "sys.path.insert(0,r'{root}/tests');"
    "from ablate_param import run_once;"
    "from ablation_arms import apply_arm;"
    "r=run_once('ablation_arm',0.0,{size},{seed},{seconds},'nn',apply_arm);"
    "print('@@RESULT@@'+json.dumps(r))"
)


def one_run(python: str, root: str, size: int, seed: int, seconds: float) -> dict:
    code = RUNNER.format(root=root.replace("\\", "/"), size=size, seed=seed, seconds=seconds)
    out = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=seconds + 600)
    for line in out.stdout.splitlines():
        if line.startswith("@@RESULT@@"):
            return json.loads(line[len("@@RESULT@@"):])
    return {"objective": float("inf"), "error": (out.stderr or out.stdout)[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=19)
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--size", type=int, default=500)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    python = sys.executable
    out_root = args.out or os.path.join(
        ROOT, "experiment_logs", "ablations", "2026-08-22_scoring_rework_trajectory")
    os.makedirs(out_root, exist_ok=True)

    roots = {label: ensure_worktree(commit, note=f"{os.path.basename(out_root)} :: {label}")
             for label, commit in ARMS}
    for label, _ in ARMS:
        os.makedirs(os.path.join(out_root, label), exist_ok=True)

    results = {label: [] for label, _ in ARMS}
    total = args.runs * len(ARMS)
    done = 0
    started = time.time()
    print(f"{len(ARMS)} arms x {args.runs} paired seeds x {args.seconds:g}s, n={args.size}",
          flush=True)
    print(f"estimated {total * args.seconds / 3600:.1f} h of solve time", flush=True)

    for seed in range(args.runs):                    # seeds OUTER, so arms stay balanced
        row = []
        for label, commit in ARMS:
            r = one_run(python, roots[label], args.size, seed, args.seconds)
            results[label].append(dict(r, seed=seed))
            with open(os.path.join(out_root, label, "results.json"), "w", encoding="utf-8") as f:
                json.dump({"commit": commit, "label": label,
                           "config": {"size": args.size, "seconds": args.seconds,
                                      "start": "nn", "runs": args.runs},
                           "runs": results[label]}, f, indent=1)
            done += 1
            row.append(f"{r['objective']:10.2f}" if r["objective"] != float("inf") else "       inf")
        elapsed = (time.time() - started) / 3600
        print(f"  seed {seed:3d}  " + " ".join(row) +
              f"   [{done}/{total}, {elapsed:.2f}h]", flush=True)

    print("\n--- per arm ---", flush=True)
    base = [r["objective"] for r in results[ARMS[0][0]]]
    for label, _ in ARMS:
        vals = [r["objective"] for r in results[label] if r["objective"] != float("inf")]
        if not vals:
            print(f"  {label:<32} no finite results", flush=True)
            continue
        mean = sum(vals) / len(vals)
        pairs = [(a["objective"], b) for a, b in zip(results[label], base)
                 if a["objective"] != float("inf") and b != float("inf")]
        deltas = [a - b for a, b in pairs]
        note = ""
        if len(deltas) > 1:
            m = sum(deltas) / len(deltas)
            var = sum((d - m) ** 2 for d in deltas) / (len(deltas) - 1)
            sem = (var / len(deltas)) ** 0.5
            note = (f"   vs baseline {m:+8.2f} +/- {sem:5.2f}"
                    f"   {m / sem if sem else 0:+5.1f} sigma   won {sum(d < 0 for d in deltas)}/{len(deltas)}")
        print(f"  {label:<32} mean {mean:9.2f}  n={len(vals)}{note}", flush=True)

    print(f"\nwritten under {out_root}", flush=True)
    print("worktrees left in place for re-runs; remove with: "
          ".venv1/Scripts/python.exe tools/worktrees.py clean", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
