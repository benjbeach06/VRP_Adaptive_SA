"""Compare AVERAGE PROPOSE TIME per operator across two solver run logs.

    .venv1/Scripts/python.exe tools/compare_operator_propose_time.py A.log B.log \
        --labels pre-slotting slotting

Propose time is the metric that survives a short run. It is a mean over every proposal an operator
made -- typically 10^4 to 10^6 of them -- so it resolves far better than a throughput count, which
on this box carries a +/-8% noise floor between identical runs.

Applies are deliberately excluded. An operator only applies when its move is accepted, so apply
counts swing with the temperature schedule and two arms rarely accept the same number.

THE SANITY CHECK MATTERS MORE THAN THE TABLE. Two arms are only comparable per operator if they
walked the same search. This prints proposal counts and the best objective for both arms first: if
those diverge, the operators were called on different route states and a per-operator time delta
mixes the refactor's effect with a different workload.

Parsing is reused from `operator_time_share.py`, which already handles both historical log formats.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from operator_time_share import parse  # noqa: E402

BEST = "Best objective:"


def avg_propose_us(row: dict) -> float:
    """Mean propose time in microseconds. parse() gives the total and the denominator it used."""
    calls = row["useful"] if row["valid_only_format"] else row["proposals"]
    if calls == 0 or row["propose_seconds"] == 0.0:
        return 0.0
    return row["propose_seconds"] / calls * 1e6


def read(path: str) -> tuple[dict[str, dict], str]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    rows = parse(text)
    if not rows:
        raise SystemExit(f"no `Stats for operator` blocks found in {path}")
    best = ""
    for line in text.splitlines():
        if BEST in line:
            best = line.split(BEST)[1].split(",")[0].strip()
    return {r["name"]: r for r in rows}, best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs=2, help="baseline log, then current log")
    ap.add_argument("--labels", nargs=2, default=["A", "B"])
    ap.add_argument("--sort", default="delta", choices=["delta", "pct", "name", "baseline"])
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    (a_rows, a_best), (b_rows, b_best) = read(args.logs[0]), read(args.logs[1])
    a_label, b_label = args.labels

    shared = sorted(set(a_rows) & set(b_rows))
    only_a, only_b = sorted(set(a_rows) - set(b_rows)), sorted(set(b_rows) - set(a_rows))

    a_props = sum(a_rows[n]["proposals"] for n in a_rows)
    b_props = sum(b_rows[n]["proposals"] for n in b_rows)
    same_walk = all(a_rows[n]["proposals"] == b_rows[n]["proposals"] for n in shared)

    print("SANITY CHECK -- are the two arms comparable?")
    print(f"  best objective    {a_label}: {a_best or '?'}    {b_label}: {b_best or '?'}")
    print(f"  total proposals   {a_label}: {a_props:,}    {b_label}: {b_props:,}"
          f"    ({(b_props / a_props - 1) * 100:+.1f}%)" if a_props else "")
    print(f"  identical per-operator proposal counts: {same_walk}")
    if not same_walk:
        print("  -> the arms walked DIFFERENT searches. Per-operator means below are still each")
        print("     arm's true cost per proposal, but the workload behind them is not identical.")
    if only_a or only_b:
        print(f"  operators only in {a_label}: {only_a or 'none'}")
        print(f"  operators only in {b_label}: {only_b or 'none'}")
    print()

    table = []
    for name in shared:
        a_us, b_us = avg_propose_us(a_rows[name]), avg_propose_us(b_rows[name])
        pct = (b_us / a_us - 1) * 100 if a_us else 0.0
        table.append({"name": name, "a_us": a_us, "b_us": b_us,
                      "delta_us": b_us - a_us, "pct": pct,
                      "a_proposals": a_rows[name]["proposals"],
                      "b_proposals": b_rows[name]["proposals"]})

    key = {"delta": lambda r: r["delta_us"], "pct": lambda r: r["pct"],
           "name": lambda r: r["name"], "baseline": lambda r: -r["a_us"]}[args.sort]
    table.sort(key=key)

    w = max(len(r["name"]) for r in table)
    print(f"{'operator':<{w}}  {a_label + ' us':>12}  {b_label + ' us':>12}  {'delta us':>10}  {'change':>8}")
    print("-" * (w + 50))
    for r in table:
        print(f"{r['name']:<{w}}  {r['a_us']:>12.3f}  {r['b_us']:>12.3f}  "
              f"{r['delta_us']:>+10.3f}  {r['pct']:>+7.1f}%")

    # Unweighted mean treats a rare operator the same as a hot one, so it says whether the change
    # is BROAD. It is the honest headline when the arms ran different numbers of proposals.
    plain = sum(r["pct"] for r in table) / len(table)

    # Fixed-mix weighting: price BOTH arms against the SAME workload, the baseline's proposal mix.
    # Weighting each arm by its own mix would fold the differing proposal counts of a wall-clock
    # run back into a number meant to isolate per-proposal cost.
    mix_a = sum(r["a_us"] * r["a_proposals"] for r in table) / 1e6
    mix_b = sum(r["b_us"] * r["a_proposals"] for r in table) / 1e6
    print("-" * (w + 50))
    print(f"{'unweighted mean change':<{w}}  {'':>12}  {'':>12}  {'':>10}  {plain:>+7.1f}%")
    print(f"{'on baseline mix (s)':<{w}}  {mix_a:>12.3f}  {mix_b:>12.3f}  {mix_b - mix_a:>+10.3f}  "
          f"{(mix_b / mix_a - 1) * 100:>+7.1f}%")
    print(f"\n  Baseline mix = each arm's mean propose time x the BASELINE's proposal counts, so")
    print(f"  both columns describe the same workload. Seconds, not microseconds.")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(table[0]))
            wr.writeheader()
            wr.writerows(table)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
