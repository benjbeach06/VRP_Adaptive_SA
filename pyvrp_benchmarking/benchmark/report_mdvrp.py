"""
Summarise the multi-depot / chaining benchmark.

There is no published best-known solution for these instances -- they are
generated for this model's actual setting, which no standard benchmark covers.
So PyVRP is the reference: the gap column is (SA - PyVRP) / PyVRP.

Reports the SA mean across seeds, not the best, for the same reason report.py
does: best-of-k on a stochastic solver is a biased estimate.
"""
from __future__ import annotations

import argparse
import json
import statistics as stats
from pathlib import Path

HERE = Path(__file__).resolve().parent


# Behave like a normal Unix filter when piped into head/less.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass          # Windows, or not the main thread

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results_mdvrp.jsonl"))
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.results) if l.strip()]
    if not rows:
        raise SystemExit("no results")

    grouped: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        grouped.setdefault(r["instance"], {}).setdefault(r["solver"], []).append(r)
    order = sorted(grouped, key=lambda k: grouped[k]["pyvrp"][0]["n"]
                   if grouped[k].get("pyvrp") else 0)

    header = (f"{'instance':<14}{'n':>6}{'dep':>5}{'PyVRP':>9}{'veh':>5}{'trips':>7}"
              f"{'SA mean':>10}{'veh':>5}{'trips':>7}{'gap%':>8}{'spread%':>9}")
    print(header)
    print("-" * len(header))

    gaps, csv_rows = [], [["instance", "n", "depots", "pyvrp_cost", "pyvrp_vehicles",
                           "sa_mean_cost", "sa_vehicles", "gap_vs_pyvrp_pct",
                           "sa_spread_pct", "sa_iters_per_s", "pyvrp_iters_per_s"]]
    infeasible = [r for r in rows if not r.get("feasible", True)]
    sa_rate, pv_rate = [], []

    for name in order:
        g = grouped[name]
        sa_runs = [r for r in g.get("simann_sa", []) if r.get("feasible")]
        pv_runs = [r for r in g.get("pyvrp", []) if r.get("feasible")]
        if not sa_runs or not pv_runs:
            continue
        sa = [r["cost"] for r in sa_runs]
        pv = min(r["cost"] for r in pv_runs)
        sa_mean = stats.mean(sa)
        gap = 100 * (sa_mean - pv) / pv
        spread = 100 * (max(sa) - min(sa)) / sa_mean if len(sa) > 1 else 0.0
        gaps.append(gap)

        r0, p0 = sa_runs[0], pv_runs[0]
        s_rate = (r0["iterations"] or 0) / r0["elapsed"]
        p_rate = (p0["iterations"] or 0) / p0["elapsed"]
        sa_rate.append(s_rate)
        pv_rate.append(p_rate)

        print(f"{name:<14}{r0['n']:>6}{r0['depots']:>5}{pv:>9,.0f}"
              f"{p0['vehicles_used']:>5}{p0['trips']:>7}"
              f"{sa_mean:>10,.0f}{r0['vehicles_used']:>5}{r0['trips']:>7}"
              f"{gap:>8.2f}{spread:>9.2f}")
        csv_rows.append([name, r0["n"], r0["depots"], pv, p0["vehicles_used"],
                         round(sa_mean, 1), r0["vehicles_used"], round(gap, 3),
                         round(spread, 3), round(s_rate), round(p_rate)])

    print("-" * len(header))
    print(f"{'mean gap vs PyVRP':<66}{stats.mean(gaps):>8.2f}")
    print()
    print(f"throughput  SA {stats.mean(sa_rate):>10,.0f} moves/s      "
          f"PyVRP {stats.mean(pv_rate):>8,.0f} HGS iterations/s")
    print("  (not comparable units: one SA iteration is a single move proposal; one PyVRP")
    print("   iteration is a full genetic generation with crossover and local search.)")

    cross = [r["cross_depot_trips"] for r in rows if r.get("feasible")]
    print(f"\ncross-depot trips (a route ending at a different depot than it started):")
    for name in order:
        g = grouped[name]
        if not g.get("pyvrp") or not g.get("simann_sa"):
            continue
        print(f"  {name:<14} SA {g['simann_sa'][0]['cross_depot_trips']:>3}"
              f"   PyVRP {g['pyvrp'][0]['cross_depot_trips']:>3}"
              f"   of {g['simann_sa'][0]['trips']} / {g['pyvrp'][0]['trips']} trips")

    if infeasible:
        print(f"\n{len(infeasible)} INFEASIBLE run(s) excluded:")
        for r in infeasible[:8]:
            print(f"  {r['solver']:<10} {r['instance']:<14} {'; '.join(r['problems'])[:70]}")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            csv.writer(f).writerows(csv_rows)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
