"""
Summarise results.jsonl against CVRPLIB best-known solutions.

Reports the SA solver's *mean* gap across seeds, not its best. Taking the best
of k stochastic runs is a biased estimate of what the solver does -- the same
argmax-selection problem METHODOLOGY.md rejects for parameter tuning. Best and
spread are shown alongside so the noise is visible, but the mean is the headline.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as stats
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTANCE_DIR = HERE / "instances" / "CVRP"


def size_of(name: str) -> int:
    m = re.search(r"n(\d+)", name)
    return int(m.group(1)) if m else 0


# Behave like a normal Unix filter when piped into head/less.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass          # Windows, or not the main thread

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results.jsonl"))
    ap.add_argument("--csv", default=None, help="also write a CSV to this path")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(HERE))
    from cvrplib import read_bks

    rows = [json.loads(l) for l in open(args.results) if l.strip()]
    if not rows:
        raise SystemExit("no results")

    grouped: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        grouped.setdefault(r["instance"], {}).setdefault(r["solver"], []).append(r)

    infeasible = [r for r in rows if not r.get("feasible", True)]

    header = (f"{'instance':<14}{'n':>6}{'BKS':>9}"
              f"{'PyVRP':>9}{'gap%':>8}{'iters':>12}"
              f"{'SA mean':>10}{'gap%':>8}{'SA best':>9}{'bgap%':>8}{'spread%':>9}")
    print(header)
    print("-" * len(header))

    csv_rows = [["instance", "n", "bks", "pyvrp", "pyvrp_gap_pct",
                 "sa_mean", "sa_mean_gap_pct", "sa_best", "sa_best_gap_pct", "sa_spread_pct"]]
    sa_gaps, sa_best_gaps, pv_gaps = [], [], []

    for name in sorted(grouped, key=size_of):
        bks = read_bks(INSTANCE_DIR / f"{name}.sol")
        if bks is None:
            continue
        g = grouped[name]
        sa = [r["cost"] for r in g.get("simann_sa", []) if r.get("feasible")]
        pv = [r["cost"] for r in g.get("pyvrp", []) if r.get("feasible")]
        if not sa:
            continue

        sa_mean, sa_best = stats.mean(sa), min(sa)
        sa_gap = 100 * (sa_mean - bks) / bks
        sa_bgap = 100 * (sa_best - bks) / bks
        spread = 100 * (max(sa) - min(sa)) / sa_mean if len(sa) > 1 else 0.0
        sa_gaps.append(sa_gap)
        sa_best_gaps.append(sa_bgap)

        if pv:
            pv_cost = min(pv)
            pv_gap = 100 * (pv_cost - bks) / bks
            pv_iters = max((r.get("iterations") or 0) for r in g["pyvrp"])
            pv_gaps.append(pv_gap)
            pv_s = f"{pv_cost:>9.0f}{pv_gap:>8.2f}{pv_iters:>12,}"
        else:
            pv_cost, pv_gap, pv_s = None, None, f"{'-':>9}{'-':>8}{'-':>12}"

        print(f"{name:<14}{size_of(name):>6}{bks:>9.0f}{pv_s}"
              f"{sa_mean:>10.0f}{sa_gap:>8.2f}{sa_best:>9.0f}{sa_bgap:>8.2f}{spread:>9.2f}")
        csv_rows.append([name, size_of(name), bks, pv_cost,
                         None if pv_gap is None else round(pv_gap, 3),
                         round(sa_mean, 1), round(sa_gap, 3), sa_best,
                         round(sa_bgap, 3), round(spread, 3)])

    print("-" * len(header))
    if pv_gaps:
        print(f"{'mean gap to BKS':<29}{'':>9}{stats.mean(pv_gaps):>8.2f}{'':>12}"
              f"{'':>10}{stats.mean(sa_gaps):>8.2f}{'':>9}{stats.mean(sa_best_gaps):>8.2f}")
    else:
        print(f"{'mean gap to BKS':<56}{stats.mean(sa_gaps):>8.2f}"
              f"{'':>9}{stats.mean(sa_best_gaps):>8.2f}")

    if infeasible:
        print(f"\n{len(infeasible)} INFEASIBLE run(s) excluded:")
        for r in infeasible[:10]:
            print(f"  {r['solver']:<10} {r['instance']:<14} {'; '.join(r['problems'])[:80]}")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            csv.writer(f).writerows(csv_rows)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
