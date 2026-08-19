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
from run_stamp import solver_stamp, stamp_header      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", type=int, default=200, help="customers; default is the reference instance")
    ap.add_argument("--capacity", type=int, default=25, help="vehicle capacity; 25 is the reference instance")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--allow-dirty", action="store_true",
                    help="run even though solver modules are uncommitted (the result is unciteable)")
    args = ap.parse_args()

    # A result is only citeable if its solver version is. An uncommitted solver module means the
    # recorded SHA does not describe the code that ran, and no later reader can recover what did.
    stamp = solver_stamp()
    print(stamp_header(stamp))
    if stamp["solver_dirty"] and not args.allow_dirty:
        print("\n  FAIL: solver modules are uncommitted --")
        for f in stamp["solver_dirty_files"]:
            print(f"    {f}")
        print("  Commit them, or pass --allow-dirty and treat the result as throwaway.")
        print("\nPREFLIGHT FAILED")
        return 1

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

    # Both signals need a run long enough to produce them. The starting temperature is
    # initial_temp_factor = 1e-4 of the objective, so EARLY acceptances are nearly all downhill and
    # improved == accepts is the correct reading, not saturation. Reheats need a plateau to exist at
    # all. Judging either on a short run reports a defect that is not there, which costs more trust
    # than the check is worth.
    MIN_ACCEPTS = 1000
    MIN_SECONDS_FOR_REHEAT = 30.0

    failures, skipped = [], []
    if accepts == 0:
        failures.append("no accepts at all -- the solver is not running")
    elif improved == 0:
        failures.append("improved never fired -- the improvement counter is dead")
    elif accepts < MIN_ACCEPTS:
        skipped.append(f"saturation check needs >= {MIN_ACCEPTS} accepts, saw {accepts} "
                       f"-- run longer to judge it")
    elif improved == accepts:
        failures.append("improved == accepts -- the counter is SATURATED (this is the 2026-08-16 bug)")

    if args.seconds < MIN_SECONDS_FOR_REHEAT:
        skipped.append(f"reheat check needs >= {MIN_SECONDS_FOR_REHEAT:g}s, ran {args.seconds:g}s")
    elif reheats == 0:
        failures.append(
            "zero plateau reheats -- reheating never fires, so anything that tunes "
            "segment_length or max_plateau_size is measuring a disabled mechanism"
        )

    for s in skipped:
        print(f"  SKIPPED: {s}")

    for failure in failures:
        print(f"  FAIL: {failure}")
    # A skipped check is not a passed check. Saying so keeps a short smoke run from reading like a
    # full verification.
    verdict = "FAILED" if failures else ("PASSED, but checks were SKIPPED" if skipped else "PASSED")
    print("\nPREFLIGHT " + verdict)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
