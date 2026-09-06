"""Paired 60 s CVRP A/B for the RandomRouteReassignment removal.

WHY A CUSTOM DRIVER AND NOT bench.py
------------------------------------
bench.py runs one arm end to end. Two arms would then be two blocks about 40 minutes apart, and
machine state is exactly the confound this run is meant to remove. This driver INTERLEAVES: for
each (instance, seed) it runs the baseline and then the treatment back to back, so the two arms
see the same machine within seconds of each other and the pair is a matched pair.

The subprocess command line is byte-identical in shape to the one bench.py builds for an SA job
(run_sa.py, --seconds, --seed, --construction), taken from each arm's OWN tree. run_sa.py resolves
the solver by searching upward from its own location, so the worktree arm imports the worktree's
solver. That was verified before this run, not assumed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = Path(r"C:\Users\Bben6\PycharmProjects\PythonProject")
PY = MAIN / ".venv1" / "Scripts" / "python.exe"

# arm label -> (tree root, commit)
ARMS = {
    "baseline": (MAIN / "_worktrees" / "ab16365", "ab16365"),
    "treatment": (MAIN, "c5eda54"),
}
ORDER = ["baseline", "treatment"]

INSTANCES = ["X-n101-k25", "X-n153-k22", "X-n200-k36", "X-n303-k21",
             "X-n401-k29", "X-n502-k39", "X-n701-k44", "X-n1001-k43"]
SECONDS = 60.0
SEEDS = 5


def bench_dir(tree: Path) -> Path:
    return tree / "pyvrp_benchmarking" / "benchmark"


def run_one(arm: str, name: str, seed: int, log) -> dict | None:
    tree, commit = ARMS[arm]
    bd = bench_dir(tree)
    cmd = [str(PY), str(bd / "run_sa.py"), str(bd / "instances" / "CVRP" / f"{name}.vrp"),
           "--seconds", str(SECONDS), "--seed", str(seed), "--construction", "greedy"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        print(f"  !! {arm} {name} seed {seed} produced no result "
              f"({time.time()-t0:.0f}s)", file=log, flush=True)
        for line in (proc.stderr or proc.stdout).strip().splitlines()[-4:]:
            print(f"     {line}", file=log, flush=True)
        return None
    rec = json.loads(lines[-1])
    rec["arm"] = arm
    rec["solver_commit"] = commit
    return rec


def main() -> None:
    outs = {a: open(HERE / f"results_{a}.jsonl", "w") for a in ORDER}
    log = open(HERE / "run.log", "a")
    n = len(INSTANCES) * SEEDS * len(ORDER)
    print(f"=== paired CVRP A/B started {time.ctime()} ===", file=log, flush=True)
    print(f"{n} runs x {SECONDS:.0f}s -- about {n*SECONDS/60:.0f} min, sequential, interleaved.",
          file=log, flush=True)
    for arm, (tree, commit) in ARMS.items():
        print(f"  arm {arm}: {commit} at {tree}", file=log, flush=True)

    done = 0
    for name in INSTANCES:
        for seed in range(SEEDS):
            for arm in ORDER:
                rec = run_one(arm, name, seed, log)
                done += 1
                if rec is None:
                    continue
                outs[arm].write(json.dumps(rec) + "\n")
                outs[arm].flush()
                # The three invariants every previous benchmark checked by hand.
                bad = []
                if not rec["feasible"]:
                    bad.append("INFEASIBLE")
                if rec["reported_objective"] != rec["cost"]:
                    bad.append(f"objective {rec['reported_objective']} != cost {rec['cost']}")
                if not (SECONDS <= rec["elapsed"] <= SECONDS + 2):
                    bad.append(f"elapsed {rec['elapsed']}")
                flag = ("  ** " + "; ".join(bad)) if bad else ""
                print(f"  [{done}/{n}] {arm:9s} {name} seed {seed}  cost {rec['cost']}{flag}",
                      file=log, flush=True)

    for f in outs.values():
        f.close()
    print(f"=== paired CVRP A/B complete {time.ctime()} ===", file=log, flush=True)
    log.close()


if __name__ == "__main__":
    main()
