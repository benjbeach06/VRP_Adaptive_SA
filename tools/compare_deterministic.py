"""
Cross-commit behavioral equivalence check: does a change alter the search at all?

    python tools/compare_deterministic.py 4cbb636
    python tools/compare_deterministic.py 4cbb636 --iterations 8000 --customers 200

Runs one fixed-ITERATION deterministic solve in a worktree at <commit> and another in the current
tree, then compares objective and full fingerprint field by field.

WHY FIXED ITERATIONS, NOT WALL CLOCK
------------------------------------
The solver terminates on time, so anything that makes a proposal slower buys fewer iterations and
changes the whole random walk. A refactor would then look like a behavior change for a reason that
has nothing to do with behavior. deterministic_clock swaps in a fake clock, so the budget is a
fixed number of iterations and added per-call cost cannot move the trajectory. Anything that
differs after that is semantic.

WHY SUBPROCESSES
----------------
Both checkouts define the same module names. Importing them into one process would give whichever
loaded first, silently comparing a tree against itself.

WHAT "IDENTICAL" IS WORTH
-------------------------
For a pure refactor -- moving a computation without changing its value -- identical is the correct
result and anything else is a defect. That covers the raw-delta accounting rollout: each step moves
one objective term from the L3 aggregators to the processor, and the sum must not move.

WHICH FIELDS DIFFER TELLS YOU WHICH LAYER BROKE
-----------------------------------------------
best_objective and curr_objective track the INCREMENTALLY PRICED value. solution_cost and
fingerprint track the SOLUTION THAT ACTUALLY EXISTS. So:

    price fields differ, solution fields match   -> a PRICING bug. The moves were mis-valued but
                                                    performed correctly. This is the dual-truth
                                                    failure the raw-delta refactor exists to remove.
    solution fields differ                       -> the search took a different path, either from a
                                                    mutation bug or from a mis-price large enough to
                                                    flip an accept/reject decision.

Verified 2026-08-28 by making the processor contribute 1e-9 per move: it surfaced as +4.21e-7 in
the price fields with the solution fields untouched. A detector that has never been seen to fire is
not evidence of anything, so re-run that probe if this tool is ever substantially changed.

KNOWN ORDERING HAZARDS -- WHY A COMPARISON CAN DIFFER FOR NO SEMANTIC REASON
----------------------------------------------------------------------------
RouteSet reorders on add and remove BY DESIGN. Swap-with-last is what makes its operations O(1),
and the container was chosen precisely because order usually does not matter. A permuted set is a
different random trajectory, not a wrong answer.

The ONE reason order is preserved anywhere is to make deterministic testing possible. So a method
that changes ordering across apply-and-revert, IN A WAY THAT CAN REACH SELECTION, is not a
correctness defect -- it is a place that can defeat this tool. Catalogue them here as they turn up.

  depot_route_starts     ACCEPTED HAZARD, by design since the raw-delta refactor. start_depot_changes
                         passes through FullSolution.apply_accounting raw: the sink removes the route
                         from the initial depot's RouteSet and adds it to the final one. RouteSet is
                         swap-with-last, so a revert re-adds at the end and does NOT restore the slot.
                         Reaches selection: routes_sharing_depot hands the live set to rand_choice
                         (Operators.py ~1238), so one apply/revert of a single ChangeEndDepot
                         permutes a depot's set (measured 2026-08-28). A position-carrying inverse
                         was considered and rejected -- it would run during pricing, and core
                         performance is never traded for determinism.

  all_routes             PROTECTED, deliberately. remove() returns the displaced index and
                         undo_remove() puts it back, and fingerprint() includes this set's ORDER in
                         solution identity. This is the standard the others are measured against.

  vehicle.routes         REORDERS THE SAME WAY, but does not reach selection today. Its only
                         positional accessor is Vehicle.route_at, and nothing calls it (audited
                         2026-08-28). It becomes a hazard the moment anything draws from this set
                         positionally.

Two caveats before treating a difference as a bug:
  * FLOAT SUMMATION ORDER. If a term is accumulated in a different order than before, results can
    differ in the last bits without anything being wrong. Compare the magnitude against the ~8-unit
    noise floor before concluding anything; a genuine semantic break is not subtle.
  * A STEP THAT ADDS A TERM. Step 4 of the refactor adds end-depot usage tracking, which is a new
    objective term. That step SHOULD differ, and identical output would mean it did nothing.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROBE = r'''
import json, os, sys
root = os.path.abspath(sys.argv[1])
sys.path.insert(0, os.path.join(root, "tests"))
sys.path.insert(0, root)
from _harness import fingerprint, random_instance, run_solver, seed_everything

seed, iterations, customers, vehicles, capacity = (int(a) for a in sys.argv[2:7])
seed_everything(seed)
sln = random_instance(seed=seed, n_customers=customers, n_vehicles=vehicles, capacity=capacity)
solver, _ = run_solver(sln, max_time=10.0, debug_level=0, iterations=iterations,
                       deterministic_weighting=True)
print("<<<RESULT>>>" + json.dumps({
    "best_objective": round(solver.best_objective, 9),
    "curr_objective": round(solver.curr_objective, 9),
    "solution_cost": round(sln.solution_cost(), 9),
    "fingerprint": fingerprint(sln),
}, default=str))
'''


def probe(root: str, args) -> dict:
    """Run one solve inside `root`, in its own process, and return the result dict."""
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, root, str(args.seed), str(args.iterations),
         str(args.customers), str(args.vehicles), str(args.capacity)],
        capture_output=True, text=True, cwd=root)
    if completed.returncode != 0:
        sys.exit(f"probe failed in {root}:\n{completed.stdout}\n{completed.stderr}")

    marker = "<<<RESULT>>>"
    # Marked rather than "last line": the solver prints regardless of debug level, and a bare
    # tail would silently parse a progress line as the result.
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):])
    sys.exit(f"probe in {root} produced no result line:\n{completed.stdout}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("commit", help="baseline commit to compare the current tree against")
    parser.add_argument("--iterations", type=int, default=4000)
    parser.add_argument("--customers", type=int, default=120)
    parser.add_argument("--vehicles", type=int, default=14)
    parser.add_argument("--capacity", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260828)
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from worktrees import ensure
    baseline_root = ensure(args.commit, note="compare_deterministic baseline")

    print(f"baseline : {args.commit}  ({baseline_root})")
    print(f"current  : {ROOT}")
    print(f"budget   : {args.iterations} iterations, n={args.customers}, "
          f"vehicles={args.vehicles}, capacity={args.capacity}, seed={args.seed}\n")

    baseline, current = probe(baseline_root, args), probe(ROOT, args)

    differences = []
    for key in ("best_objective", "curr_objective", "solution_cost", "fingerprint"):
        same = baseline[key] == current[key]
        print(f"  {key:16s} {'MATCH' if same else 'DIFFER'}")
        if not same:
            differences.append(key)

    print(f"\n  baseline best: {baseline['best_objective']}")
    print(f"  current  best: {current['best_objective']}")

    if not differences:
        print("\nIDENTICAL. For a pure refactor this is the correct result.")
        return 0

    delta = current["best_objective"] - baseline["best_objective"]
    print(f"\nDIFFERS in: {', '.join(differences)}   (best objective moved {delta:+.9f})")
    print("Before calling it a defect, rule out float summation order -- see this file's header.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
