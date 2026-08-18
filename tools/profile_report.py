"""
Format profile_operators.py output into readable scaling tables.

Reads one or more result JSON files and prints, per operator:
  - median propose / apply cost at each instance size
  - the log-log slope of propose cost against size

READING THE SLOPE
    ~0.0   cost does not depend on instance size. Any problem here is a constant factor.
    ~0.3   cost tracks route COUNT weakly, or the operator is partly size-bound.
    ~1.0   cost is linear in size. This is what actually breaks at scale.

Route LENGTH is nearly constant across sizes on this instance family (capacity 25 against
demands 1-10 caps a route at about 9 stops regardless of n), so a nonzero slope almost always
means the operator touches the route COUNT, not the customers inside one route.

ACTIONABLE PERCENT IS PART OF THE MEASUREMENT, NOT A FOOTNOTE
A low actionable rate means most of the timed calls returned INVALID or NOOP, so the number is
mostly the cost of the REJECTION path. At size 10 there are only about 4 routes, so several
operators cannot find legal operands. Treat any cell under ~60% actionable as a measurement of
early exit, not of work.

USAGE
    python tools/profile_report.py experiment_logs/profile_cold.json
    python tools/profile_report.py experiment_logs/profile_cold.json experiment_logs/profile_warm.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys


def collect(path: str):
    with open(path) as handle:
        data = json.load(handle)

    sizes = sorted({cell["size"] for cell in data["cells"]})
    warms = sorted({cell["warm_seconds_requested"] for cell in data["cells"]})
    names = sorted({name for cell in data["cells"] for name in cell["operators"]})
    return data, sizes, warms, names


def cell_stat(data, name, size, warm, phase, stat):
    values = []
    for cell in data["cells"]:
        if cell["size"] != size or cell["warm_seconds_requested"] != warm:
            continue
        entry = cell["operators"].get(name)
        if entry and entry[phase][stat] is not None:
            values.append(entry[phase][stat])
    return statistics.median(values) if values else None


def actionable(data, name, size, warm):
    values = [c["operators"][name]["actionable_pct"] for c in data["cells"]
              if c["size"] == size and c["warm_seconds_requested"] == warm
              and name in c["operators"]]
    return statistics.median(values) if values else None


def loglog_slope(sizes, values):
    """Least-squares slope of log(cost) against log(size). None when under two usable points."""
    points = [(s, v) for s, v in zip(sizes, values) if v is not None and v > 0 and s > 0]
    if len(points) < 2:
        return None
    xs = [math.log(s) for s, _ in points]
    ys = [math.log(v) for _, v in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if not denom:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def fmt(value, width=9):
    return " " * (width - 1) + "-" if value is None else f"{value:{width}.1f}"


def print_table(data, sizes, warm, names, phase, title):
    print(f"\n{title}  (median microseconds, warm={warm:g}s)")
    header = f"  {'operator':<40}" + "".join(f"{('n=' + str(s)):>10}" for s in sizes) + f"{'slope':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    rows = []
    for name in names:
        values = [cell_stat(data, name, s, warm, phase, "median_us") for s in sizes]
        largest = next((v for v in reversed(values) if v is not None), 0) or 0
        rows.append((largest, name, values))

    for _, name, values in sorted(rows, reverse=True):
        # Derived here rather than read from the JSON's precomputed "scaling" block, which is only
        # written when a run finishes. This way a partial file still reports slopes.
        slope = loglog_slope(sizes, values)
        slope_text = "      -" if slope is None else f"{slope:7.2f}"
        print(f"  {name:<40}" + "".join(fmt(v) for v in values) + " " + slope_text)


def print_actionable(data, sizes, warm, names):
    print(f"\nActionable percent  (warm={warm:g}s) -- cells under 60% time the rejection path")
    header = f"  {'operator':<40}" + "".join(f"{('n=' + str(s)):>10}" for s in sizes)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name in names:
        values = [actionable(data, name, s, warm) for s in sizes]
        flag = " <-- thin" if any(v is not None and v < 60 for v in values) else ""
        print(f"  {name:<40}" + "".join(fmt(v) for v in values) + flag)


def main(paths: list[str]) -> int:
    for path in paths:
        data, sizes, warms, names = collect(path)
        print("=" * 100)
        print(f"{path}")
        print(f"  started {data['started']}, {len(data['cells'])} cells, "
              f"{data['proposals']} proposals per operator per cell, "
              f"clock resolution {data['clock_resolution_s']:g}s")
        if data.get("elapsed_seconds"):
            print(f"  completed in {data['elapsed_seconds']:.0f}s")
        else:
            print("  INCOMPLETE -- this file was read while the run was still going")
        print("=" * 100)

        for warm in warms:
            print_table(data, sizes, warm, names, "propose", "PROPOSE cost")
            print_table(data, sizes, warm, names, "apply", "APPLY cost")
            print_actionable(data, sizes, warm, names)

        findings = data.get("findings") or [f for c in data["cells"] for f in c["findings"]]
        if findings:
            print(f"\n{len(findings)} FINDINGS:")
            for finding in findings[:30]:
                print(f"  - {finding}")
        else:
            print("\nNo findings: every apply/revert round trip restored the solution exactly.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python tools/profile_report.py RESULTS.json [RESULTS2.json ...]")
    raise SystemExit(main(sys.argv[1:]))
