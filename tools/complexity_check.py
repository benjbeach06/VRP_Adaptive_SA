"""Measure the empirical growth order of a core subalgorithm by doubling n until time runs out.

    tools/complexity_check.py                       # every registered case
    tools/complexity_check.py --case farthest_insertion --budget 30

Asserting a complexity class from reading code is how you end up shipping an O(n^3) inner loop that
looked quadratic. This measures it: run at n, double n, run again, and read the RATIO of successive
times. For O(n^k) that ratio converges to 2^k -- 2 for linear, 4 for quadratic, 8 for cubic -- and
the estimate log2(t(2n)/t(n)) reads off k directly.

Inputs GROW rather than being regenerated: the case builds customers [n, 2n) and appends them, so
the sequence at 2n contains the sequence at n. That keeps the instance family fixed as n changes,
so a ratio reflects the algorithm and not a change of problem.

ADDING A CASE
    Register a builder (n -> input) and a runner (input -> None). Keep the runner free of setup
    work; anything O(n) done inside it that is not part of the algorithm shows up as a lower-order
    term and flattens the estimate.
"""
import argparse
import math
import random
import statistics
import threading
import _thread
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CASES: dict[str, tuple] = {}

# Read on ABORT ONLY, by walking the KeyboardInterrupt traceback into the algorithm's own frame.
# Nothing runs during a normal call, and no measured function is edited -- the harness owns all of
# this. The cost is a name coupling: rename a local in the algorithm and progress reporting stops.
# It degrades to silence rather than to a wrong number, and this table is where you fix it.
#
# work_exponent converts progress-by-COUNT into progress-by-WORK. Get it from the cost of one
# outer pass, not from a guess.
#
# Farthest insertion: pass i scans `seq` (i entries) AND `remaining` (n-i entries). The two sum to
# roughly n, so cost per pass is FLAT and work is linear in passes completed. Exponent 1.
#
# This was first written as 2, on the reasoning that the seq scan grows -- which ignored that the
# remaining scan shrinks by the same amount. The error was caught by report_abort's cross-check:
# progress said 1007s, extrapolation from k said 76.5s, and the truth was ~92s. Keep that check.
PROGRESS = {
    "farthest_insertion": {
        "frame": "farthest_insertion_order",
        "total": lambda loc: len(loc["points"]),
        "left": lambda loc: len(loc["remaining"]),
        "work_exponent": 1,
    },
}

MIN_ABORT_SECONDS = 2.0     # below this the estimate is timer noise


def case(name):
    def register(fn):
        CASES[name] = fn
        return fn
    return register


# --------------------------------------------------------------------------------------------
# IMPORTS the real function rather than copying it. A copy is free to drift from the algorithm it
# claims to measure, and then the measurement describes code nobody runs.
#
# This checks a HELPER, not a whole operator. Whole-operator checks need constructed FullSolution
# instances of each size, which is a larger job -- see the note at the bottom of this file.
# --------------------------------------------------------------------------------------------
from SimAnn_VRP_Operators import farthest_insertion_order      # noqa: E402


@case("farthest_insertion")
def farthest_insertion(points):
    return farthest_insertion_order(points, (0.0, 0.0), (100.0, 100.0))


def report_abort(name, n, elapsed, rows):
    """Estimate how far an aborted run got, from the algorithm's own locals."""
    print(f"\n  ABORTED at n={n:,} after {elapsed:.2f}s")
    if elapsed < MIN_ABORT_SECONDS:
        print(f"  (under {MIN_ABORT_SECONDS:g}s -- too short to estimate)")
        return

    spec = PROGRESS.get(name)
    if spec is None:
        print("  no PROGRESS entry for this case; cannot estimate")
        return

    frame = None
    tb = sys.exc_info()[2]
    while tb is not None:
        if tb.tb_frame.f_code.co_name == spec["frame"]:
            frame = tb.tb_frame
        tb = tb.tb_next
    if frame is None:
        print(f"  frame {spec['frame']!r} not on the traceback; cannot estimate")
        return

    try:
        loc = frame.f_locals
        total, left = spec["total"](loc), spec["left"](loc)
    except KeyError as exc:
        print(f"  local {exc} missing -- PROGRESS table is stale for this algorithm")
        return

    done = total - left
    by_count = done / total if total else 0.0
    by_work = by_count ** spec["work_exponent"]
    print(f"  placed {done:,}/{total:,}  = {by_count:.1%} by count, {by_work:.1%} by work")
    if by_work > 0:
        measured = elapsed / by_work
        print(f"  projected total: {measured:,.1f}s   ESTIMATE, from measured progress")
        if len(rows) >= 3:
            ks = [math.log2(rows[i][1] / rows[i - 1][1]) for i in range(2, len(rows))]
            k = sum(ks) / len(ks)
            extrapolated = rows[-1][1] * 2 ** k
            print(f"  extrapolated from k={k:.2f}: {extrapolated:,.1f}s")
            gap = measured / extrapolated if extrapolated else float("nan")
            verdict = "consistent" if 0.5 <= gap <= 2.0 else "DISAGREE -- k may not hold at this n"
            print(f"  ratio {gap:.2f}x -- {verdict}")


def grow(points, target, rng):
    """Extend the point list to `target`, keeping every point already generated."""
    while len(points) < target:
        points.append((rng.uniform(0, 100), rng.uniform(0, 100)))
    return points


def measure(name, fn, budget, start_n, seed):
    rng = random.Random(seed)
    points, n = [], start_n
    rows = []
    spent = 0.0

    print(f"\n=== {name} ===")
    print(f"  {'n':>8} {'seconds':>12} {'ratio':>8} {'implied k':>10}")
    while spent < budget:
        grow(points, n, rng)
        subject = list(points)

        # Abort the size in progress when the budget runs out, rather than letting it finish.
        # At quadratic growth the last size costs about 4x everything before it, so a "30s" run
        # would otherwise take two minutes. The watchdog raises KeyboardInterrupt in the main
        # thread, which report_abort turns into a progress estimate read from the algorithm's own
        # frame -- so the aborted size still yields a projected runtime instead of nothing.
        watchdog = threading.Timer(max(budget - spent, 0.01), _thread.interrupt_main)
        watchdog.daemon = True
        watchdog.start()

        t0 = time.perf_counter()
        try:
            fn(subject)
        except KeyboardInterrupt:
            report_abort(name, n, time.perf_counter() - t0, rows)
            break
        finally:
            watchdog.cancel()
        dt = time.perf_counter() - t0
        spent += dt

        ratio = dt / rows[-1][1] if rows else float("nan")
        k = math.log2(ratio) if rows and ratio > 0 else float("nan")
        rows.append((n, dt))
        print(f"  {n:>8,} {dt:>12.4f} {ratio:>8.2f} {k:>10.2f}"
              + ("" if rows[:-1] else "   (baseline)"))
        n *= 2

    # The number of doublings is dynamic: keep going while budget remains, and stop when it runs
    # out. The loop condition is checked BEFORE each size, so the final size can overshoot -- a
    # single call cannot be interrupted partway. Predicting the next cost and stopping early
    # instead was the first version, and it wasted most of the budget: a 60s run used 24s and
    # discarded a doubling it could have afforded most of.

    if len(rows) >= 3:
        # Ignore the first two points: at small n the timer resolution and constant overhead
        # dominate, which biases k downward.
        ks = [math.log2(rows[i][1] / rows[i - 1][1]) for i in range(2, len(rows))]
        print(f"\n  implied k over the last {len(ks)} doubling(s): "
              f"{', '.join(f'{k:.2f}' for k in ks)}")
        print(f"  mean k = {sum(ks)/len(ks):.2f}   -> O(n^{round(sum(ks)/len(ks), 1)})")
        report_memory_artifact(rows, ks)
    else:
        print("\n  too few doublings inside the budget to estimate k")
    return rows


def report_memory_artifact(rows, ks):
    """
    Separate a real higher-order term from cache pressure, and say so when they are confused.

    This tool reports WALL TIME, so it charges the algorithm for the memory hierarchy. Past some
    size the working set outgrows cache, the cost PER OPERATION rises, and k appears to climb while
    the operation count is still exactly quadratic.

    The test: normalize each time by n^k using the MEDIAN k, which the drifting tail cannot move.
    If the operation count really is n^k, that normalized cost is flat. A rise means each operation
    got slower, not that there are more of them.

    Measured example: farthest insertion at n=4096/8192/16384 gave 257/282/342 ns per n^2 unit, a
    33% rise, while the operation count could not have changed. k read 2.28 and the algorithm was
    O(n^2).
    """
    stable_k = statistics.median(ks)
    normalized = [(n, 1e9 * t / n ** stable_k) for n, t in rows[1:]]

    print(f"\n  cost per n^{stable_k:.2f} unit (flat = the exponent is real):")
    for n, cost in normalized:
        print(f"    {n:>8,}  {cost:>8.1f} ns")

    baseline = min(cost for _, cost in normalized)
    worst_n, worst = max(normalized, key=lambda pair: pair[1])
    rise = worst / baseline if baseline else 1.0

    if rise >= 1.15 and worst_n == normalized[-1][0]:
        flat_to = max((n for n, cost in normalized if cost <= baseline * 1.05), default=0)
        print(f"\n  TODO(memory-artifact): the cost column is FLAT to n={flat_to:,}, then rises")
        print(f"    {rise - 1:.0%} by n={worst_n:,}. So k is trustworthy up to n={flat_to:,} and")
        print(f"    OVERSTATED beyond it. The operation count did not change; each operation got")
        print(f"    slower, because the working set outgrew cache.")
        print(f"    MORE TIME RESOLVES THIS. Raise --budget and read the shape of the rise:")
        print(f"      a STEP that flattens again  -> a cache tier boundary, k is fine")
        print(f"      a CONTINUOUS climb          -> a real higher-order term, k is real")
        print(f"    One doubling past the rise usually decides it. Counting operations instead of")
        print(f"    timing them, or a machine with more cache, settle it without the wait.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=sorted(CASES), action="append")
    ap.add_argument("--budget", type=float, default=30.0, help="seconds per case")
    ap.add_argument("--start-n", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    for name in (args.case or sorted(CASES)):
        measure(name, CASES[name], args.budget, args.start_n, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --------------------------------------------------------------------------------------------
# LATER: whole-operator complexity checks.
#
# This file measures HELPERS -- pure functions over plain data. That is cheap, because the input
# at size n is just a longer list.
#
# Measuring a whole Operator is a bigger job. Each size needs a constructed FullSolution with a
# plausible route structure, not a random one: operand selection reads route lengths, neighbour
# tables and depot assignments, so an unrealistic instance measures an unrealistic code path. The
# instance build must also stay outside the timed region, and it is itself superlinear.
#
# Worth doing once several helpers are covered here and the harness has earned trust.
# --------------------------------------------------------------------------------------------
