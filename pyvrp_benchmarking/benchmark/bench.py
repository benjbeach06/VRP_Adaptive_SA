"""
Benchmark driver: run both solvers over a set of CVRPLIB instances and append
one JSON line per run to results.jsonl.

Runs are strictly sequential. Two solvers competing for cores would make a
wall-clock-budgeted comparison meaningless, which is the whole measurement here.

Usage
-----
    python benchmark/bench.py --seconds 60 --seeds 3
    python benchmark/bench.py --instances X-n101-k25 X-n502-k39 --seconds 30
    python benchmark/bench.py --only sa            # skip PyVRP
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTANCE_DIR = HERE / "instances" / "CVRP"
RESULTS = HERE / "results.jsonl"

# A size ladder rather than a random sample: the interesting question is how the
# gap scales with n, since a pure-Python solver loses iterations as n grows.
DEFAULT_INSTANCES = [
    "X-n101-k25", "X-n153-k22", "X-n200-k36", "X-n303-k21",
    "X-n401-k29", "X-n502-k39", "X-n701-k44", "X-n1001-k43"
]


def venv_python(name: str, override: str | None) -> Path:
    """Interpreter for one side of the comparison.

    The two-venv split exists because the solver and PyVRP can need different
    Python versions. One interpreter that satisfies both is fine, and --python
    says so explicitly rather than relying on the silent fallback below.
    """
    if override:
        return Path(override)
    exe = "python.exe" if sys.platform == "win32" else "python"
    p = HERE / name / ("Scripts" if sys.platform == "win32" else "bin") / exe
    return p if p.exists() else Path(sys.executable)


def run(cmd: list[str], label: str) -> dict | None:
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # The solver prints a long stats report to stdout; the JSON is the last line.
    lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        print(f"  !! {label} produced no result ({time.time()-t0:.0f}s)", file=sys.stderr)
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-4:]
        for line in tail:
            print(f"     {line}", file=sys.stderr)
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        print(f"  !! {label}: could not parse result line", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--seeds", type=int, default=5,
                    help="seeds for the SA solver (wall-clock termination makes it "
                         "stochastic even at a fixed seed, so >1 is not optional)")
    ap.add_argument("--pyvrp-seeds", type=int, default=1)
    ap.add_argument("--instances", nargs="*", default=DEFAULT_INSTANCES)
    ap.add_argument("--only", choices=["sa", "pyvrp", "both"], default="both")
    ap.add_argument("--construction", choices=["greedy", "dumb"], default="greedy")
    ap.add_argument("--append", action="store_true",
                    help="append to results.jsonl instead of truncating")
    ap.add_argument("--vehicles", type=int, default=None,
                    help="fleet size for the SA solver (default: run_sa.py's own, "
                         "ceil(demand/capacity)+2). One depot makes a vehicle's route "
                         "chain indistinguishable from that many one-route vehicles, so "
                         "this changes the search, not the objective.")
    ap.add_argument("--out", default=None,
                    help="results file (default: results.jsonl). Give each arm of a "
                         "comparison its own file -- report.py groups by instance and "
                         "solver, so two arms in one file would be averaged together.")
    ap.add_argument("--python", default=None,
                    help="one interpreter for both solvers, instead of venv-sa "
                         "and venv-pyvrp (default: those venvs, else this one)")
    args = ap.parse_args()

    if not INSTANCE_DIR.exists():
        sys.exit(f"no instances at {INSTANCE_DIR} -- run benchmark/setup.sh first")

    py_sa = venv_python("venv-sa", args.python)
    py_pv = venv_python("venv-pyvrp", args.python)
    print(f"solver interpreter : {py_sa}", file=sys.stderr)
    print(f"pyvrp  interpreter : {py_pv}", file=sys.stderr)

    mode = "a" if args.append else "w"
    n_runs = len(args.instances) * (
        (args.seeds if args.only in ("sa", "both") else 0)
        + (args.pyvrp_seeds if args.only in ("pyvrp", "both") else 0))
    est = n_runs * args.seconds / 60
    print(f"{n_runs} runs x {args.seconds:.0f}s -- about {est:.0f} min, sequential.",
          file=sys.stderr)

    results = Path(args.out) if args.out else RESULTS
    with open(results, mode) as out:
        for name in args.instances:
            vrp = INSTANCE_DIR / f"{name}.vrp"
            if not vrp.exists():
                print(f"  !! missing {vrp}", file=sys.stderr)
                continue

            jobs: list[tuple[str, list[str]]] = []
            if args.only in ("sa", "both"):
                for seed in range(args.seeds):
                    jobs.append((f"sa {name} seed {seed}", [
                        str(py_sa), str(HERE / "run_sa.py"), str(vrp),
                        "--seconds", str(args.seconds), "--seed", str(seed),
                        "--construction", args.construction]
                        + (["--vehicles", str(args.vehicles)] if args.vehicles else [])))
            if args.only in ("pyvrp", "both"):
                for seed in range(args.pyvrp_seeds):
                    jobs.append((f"pyvrp {name} seed {seed}", [
                        str(py_pv), str(HERE / "run_pyvrp.py"), str(vrp),
                        "--seconds", str(args.seconds), "--seed", str(seed)]))

            for label, cmd in jobs:
                print(f"  {label} ...", file=sys.stderr, flush=True)
                rec = run(cmd, label)
                if rec is None:
                    continue
                out.write(json.dumps(rec) + "\n")
                out.flush()
                flag = "" if rec.get("feasible") else "  INFEASIBLE"
                print(f"    cost {rec['cost']}{flag}", file=sys.stderr)

    print(f"\nwrote {results}\n  python {shlex.quote(str(HERE / 'report.py'))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
