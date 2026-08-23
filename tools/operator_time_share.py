"""Turn the per-operator `print_stats` blocks at the end of a solver run log into a time-share table.

    .venv1/Scripts/python.exe tools/operator_time_share.py temp/SimAnn_TimeBasedEMA

`SimAnn_VRP.py` prints one block per operator when a solve finishes. Those blocks carry MEAN times
and counts, never totals, so the totals here are reconstructed.

TWO LOG FORMATS, detected per block:

- **Current.** `Average propose time` is `_propose_time_total / _proposal_count`, so it covers
  EVERY proposal including invalid and noop. propose time = that mean x Total proposals, and the
  accounting is complete.
- **Older**, up to 2026-08-23. `Average valid propose time` is over `Useful` only, so invalid and
  noop time is missing entirely and the shares are of accounted time alone. The script says so in
  its output rather than presenting a share it cannot support.

ONE CORRECTION APPLIED IN BOTH FORMATS. `_apply_time_total` accumulates `dt + _last_propose_time`,
and that proposal is already in the propose total, so a naive sum double counts it once per apply.
The `seconds` column subtracts `applies x mean propose time` to remove it. That estimate uses the
OVERALL mean proposal time, while the true value is the mean over accepted proposals only, so it is
an approximation. `raw_seconds` keeps the uncorrected figure for comparison.
"""
import argparse
import re
import sys

BLOCK = re.compile(
    r"Stats for operator (?P<name>\w+):\s*\n"
    r"LogWeight: (?P<logweight>[-\d.eE+]+|nan|-?inf), Total calls: (?P<calls>\d+), "
    r"Total proposals: (?P<proposals>\d+), Total applies: (?P<applies>\d+)\s*\n"
    r"Invalid: (?P<invalid>\d+), Noop: (?P<noop>\d+), Useful: (?P<useful>\d+)\s*\n"
    r"Num improving calls: (?P<improving>\d+), Mean improvement: (?P<mean_impr>[-\d.eE+]+)\s*\n"
    r"Num degrading calls: (?P<degrading>\d+), Mean degradation: (?P<mean_deg>[-\d.eE+]+)\s*\n"
    r"Average apply time: (?P<avg_apply>[-\d.eE+]+), "
    r"Average (?P<valid_only>valid )?propose time: (?P<avg_propose>[-\d.eE+]+), "
    r"Average valid call time: (?P<avg_call>[-\d.eE+]+)"
)


def parse(text: str) -> list[dict]:
    rows = []
    for m in BLOCK.finditer(text):
        d = m.groupdict()
        useful = int(d["useful"])
        applies = int(d["applies"])
        proposals = int(d["proposals"])
        avg_propose = float(d["avg_propose"])
        avg_apply = float(d["avg_apply"])
        # Older logs averaged propose time over Useful only; current ones average over every
        # proposal. The denominator decides what to multiply by.
        valid_only = bool(d["valid_only"])
        propose_calls = useful if valid_only else proposals

        # A never-measured average is stamped 1e-12 by the guard, not 0. Treat it as no time.
        propose_total = avg_propose * propose_calls if avg_propose > 1e-11 else 0.0
        apply_total = avg_apply * applies if avg_apply > 1e-11 else 0.0
        # Remove the propose time that _apply_time_total re-counted, once per apply.
        double_counted = min(applies * avg_propose, apply_total) if avg_propose > 1e-11 else 0.0

        rows.append({
            "name": d["name"],
            "log_weight": float(d["logweight"]),
            "proposals": proposals,
            "applies": applies,
            "useful": useful,
            "invalid": int(d["invalid"]),
            "noop": int(d["noop"]),
            "improving": int(d["improving"]),
            "mean_improvement": float(d["mean_impr"]),
            "valid_only_format": valid_only,
            "propose_seconds": propose_total,
            "apply_seconds": apply_total - double_counted,
            "raw_seconds": propose_total + apply_total,
            "seconds": propose_total + apply_total - double_counted,
            "us_per_call": float(d["avg_call"]) * 1e6,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="a solver run log, e.g. temp/SimAnn_TimeBasedEMA")
    ap.add_argument("--sort", default="seconds",
                    choices=["seconds", "improving", "proposals", "log_weight", "name"])
    ap.add_argument("--csv", default=None, help="also write the table here")
    args = ap.parse_args()

    with open(args.log, "r", encoding="utf-8", errors="replace") as f:
        rows = parse(f.read())

    if not rows:
        print(f"no `Stats for operator` blocks found in {args.log}", file=sys.stderr)
        return 1

    total = sum(r["seconds"] for r in rows)
    all_calls = sum(r["proposals"] for r in rows)
    stale = [r for r in rows if r["valid_only_format"]]
    unaccounted = sum(r["invalid"] + r["noop"] for r in stale)

    rows.sort(key=(lambda r: r["name"]) if args.sort == "name"
              else (lambda r: r[args.sort]), reverse=args.sort != "name")

    print(f"{args.log}: {len(rows)} operators, {total:.2f} s of operator time, "
          f"{all_calls:,} proposals")
    if stale:
        print(f"WARNING: {len(stale)} block(s) use the OLD 'Average valid propose time' format, so "
              f"{unaccounted:,} invalid/noop calls carry time the log never reports. Those rows are "
              f"shares of ACCOUNTED time only.")
    print()
    print(f"  {'operator':<40} {'time%':>7} {'seconds':>9} {'us/call':>9} "
          f"{'proposals':>10} {'inv+noop':>9} {'applies':>8} {'impr':>7} {'impr/s':>8} {'logW':>7}")
    for r in rows:
        share = (r["seconds"] / total * 100) if total > 0 else 0.0
        impr_per_s = (r["improving"] / r["seconds"]) if r["seconds"] > 0 else 0.0
        print(f"  {r['name']:<40} {share:6.2f}% {r['seconds']:9.3f} {r['us_per_call']:9.2f} "
              f"{r['proposals']:10,} {r['invalid'] + r['noop']:9,} {r['applies']:8,} "
              f"{r['improving']:7,} {impr_per_s:8.1f} {r['log_weight']:7.2f}")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + ["time_share"])
            w.writeheader()
            for r in rows:
                w.writerow({**r, "time_share": (r["seconds"] / total) if total > 0 else 0.0})
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
