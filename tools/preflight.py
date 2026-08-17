"""Preflight for long unattended runs. Fails loudly rather than burning the budget.

A tuning or ablation job takes hours and reports plausible-looking numbers whether or not the
instruments it steers by are working. This checks the instruments first, at the shape the job will
actually run, and exits non-zero if any of them is dead or stuck.

    .venv1/Scripts/python.exe tools/preflight.py                    # reference instance
    .venv1/Scripts/python.exe tools/preflight.py --size 500 --capacity 400

Two minutes against a ten-hour job is 0.3% overhead, so run it every time.

WHY THESE CHECKS
    `OperatorStats.improvements` is not a reporting field. `SimAnnVRPSolver.update_weights` reads
    it as `improving_moves`, and `improving_moves == 0` is what advances the plateau counter that
    triggers reheating. A counter that is dead or saturated silently disables reheating, and every
    result measured afterwards describes a solver that is not the one being tuned.

    That is not hypothetical. The counter tested `score > 0`, which the `explore_reward` floor made
    unconditionally true; reheating stopped firing, and a 4.5-hour search plus its validation and
    isolation runs were all void. Saturation is visible in one number: improved / accepts == 1.

ADDING A CHECK
    Every statistic the solver reads back as a CONTROL INPUT belongs here -- not a full oracle,
    just "is this instrument stuck?". Add it when a review finds one, so the suite gets built out
    of real failures instead of guessed ones.
"""
import argparse
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import tune                                          # noqa: E402
import SimAnn_VRP_Core_Model as CM                    # noqa: E402
from SimAnn_VRP_Operators import OperatorStats        # noqa: E402
from SimAnn_VRP_Solver import SimAnnVRPSolver         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", type=int, default=200, help="customers; default is the reference instance")
    ap.add_argument("--capacity", type=int, default=25, help="vehicle capacity; 25 is the reference instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    tune.CAPACITY = args.capacity

    # Count every accept and how many were scored as improvements. Wrapping the real method means
    # this measures the shipped code path, not a reimplementation of it.
    tally = {"accepts": 0, "improved": 0}
    original = OperatorStats.record_accept

    def spy(self, score, improved):
        tally["accepts"] += 1
        tally["improved"] += bool(improved)
        return original(self, score, improved)

    OperatorStats.record_accept = spy

    # solver_kwargs raises if tune.DEFAULTS has drifted from SimAnnVRPSolver.__init__, so this
    # line doubles as the stale-defaults check.
    CM.seed_solver_rng(args.seed)
    sln = tune.build_instance(args.size)
    solver = SimAnnVRPSolver(sln, max_time=args.seconds, **tune.solver_kwargs(tune.DEFAULTS))
    with contextlib.redirect_stdout(io.StringIO()):
        solver.make_initial_solution()
        solver.solve(debug_level=0)

    accepts, improved = tally["accepts"], tally["improved"]
    reheats = solver.num_plateau_reheats
    ratio = improved / accepts if accepts else float("nan")

    print(f"n={args.size} capacity={args.capacity} {args.seconds:g}s seed={args.seed}")
    print(f"  best objective   {solver.best_objective:.2f}")
    print(f"  accepts          {accepts}")
    print(f"  improved         {improved}   (ratio {ratio:.3f})")
    print(f"  plateau reheats  {reheats}")

    failures = []
    if accepts == 0:
        failures.append("no accepts at all -- the solver is not running")
    if improved == 0:
        failures.append("improved never fired -- the improvement counter is dead")
    if improved == accepts:
        failures.append("improved == accepts -- the counter is SATURATED (this is the 2026-08-16 bug)")
    if reheats == 0:
        failures.append(
            "zero plateau reheats -- reheating never fires, so anything that tunes "
            "segment_length or max_plateau_size is measuring a disabled mechanism"
        )

    for failure in failures:
        print(f"  FAIL: {failure}")
    print("\nPREFLIGHT " + ("FAILED" if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
