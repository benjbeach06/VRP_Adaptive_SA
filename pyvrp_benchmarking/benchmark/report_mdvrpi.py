"""
Report the MDVRPI run against Crevier et al. (2007), Table 8.

Read the sign convention carefully. The solver is run on a RELAXATION of MDVRPI --
the rotation-duration constraint D is not implemented -- so a negative "vs pub"
is expected and is not a win. The column that decides anything is `dur viol`:
how many of the returned rotations exceed D, and by how much.
"""
from __future__ import annotations

import argparse
import json
import statistics as stats
from pathlib import Path

ORDER = ["a2", "b2", "c2", "d2", "e2", "f2", "g2", "h2", "i2", "j2"]


# Behave like a normal Unix filter when piped into head/less.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass          # Windows, or not the main thread

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results",
                    default=str(Path(__file__).resolve().parent / "results_mdvrpi.jsonl"))
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.results) if l.strip()]
    by = {}
    for r in rows:
        by.setdefault(r["instance"], []).append(r)

    header = (f"{'inst':<5}{'src':>6}{'n':>5}{'r':>3}{'m':>3}"
              f"{'published':>11}{'SA mean':>10}{'SA best':>10}{'vs pub%':>9}"
              f"{'veh':>5}{'dur viol':>10}{'worst over%':>13}")
    print(header)
    print("-" * len(header))

    vs, worst_all, viol_frac, csv_rows = [], [], [], [[
        "instance", "source", "n", "depots", "m", "published_best",
        "sa_mean", "sa_best", "vs_published_pct", "vehicles_used",
        "rotations_over_D", "worst_over_pct"]]

    for name in ORDER:
        rs = by.get(name)
        if not rs:
            continue
        ok = [r for r in rs if r["capacity_and_coverage_ok"]]
        if not ok:
            print(f"{name:<5}  all runs violated capacity/coverage")
            continue
        costs = [r["cost"] for r in ok]
        mean, best = stats.mean(costs), min(costs)
        r0 = ok[0]
        pub = r0["published_best"]
        gap = 100 * (mean - pub) / pub
        nviol = stats.mean(r["num_duration_violations"] for r in ok)
        worst = max(r["worst_over_pct"] for r in ok)
        vs.append(gap); worst_all.append(worst)
        viol_frac.append(nviol / max(r0["vehicles_used"], 1))

        print(f"{name:<5}{r0['source']:>6}{r0['n']:>5}{r0['depots']:>3}{r0['fleet']:>3}"
              f"{pub:>11.2f}{mean:>10.2f}{best:>10.2f}{gap:>9.2f}"
              f"{r0['vehicles_used']:>5}{nviol:>10.1f}{worst:>13.1f}")
        csv_rows.append([name, r0["source"], r0["n"], r0["depots"], r0["fleet"], pub,
                         round(mean, 2), round(best, 2), round(gap, 2),
                         r0["vehicles_used"], round(nviol, 1), worst])

    print("-" * len(header))
    print(f"{'mean':<48}{stats.mean(vs):>9.2f}{'':>15}{stats.mean(worst_all):>13.1f}")
    print()
    print("HOW TO READ THIS")
    print("  'vs pub%' negative = cheaper than the published best. That is EXPECTED and is")
    print("  NOT a result: the rotation-duration constraint D is not implemented, so this")
    print("  solves a relaxation whose optimum lower-bounds the true MDVRPI optimum.")
    print(f"  On average {100*stats.mean(viol_frac):.0f}% of returned rotations exceed D, by up to "
          f"{max(worst_all):.0f}%.")
    print("  The constraint binds: the discount is bought with infeasibility, not with search.")
    print()
    print("  A cost ABOVE the published value would have been decisive the other way.")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            csv.writer(f).writerows(csv_rows)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
