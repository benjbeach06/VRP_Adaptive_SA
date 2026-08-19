"""Compare solver runs against each other and against Hexaly, and plot the convergence curves.

    tools/compare_runs.py temp/Hexaly_run temp/SimAnn_Run_NoAdaptiveWeights temp/SimAnn_Run_WithAdaptiveWeights

Log format is detected per file. A Hexaly log carries `[ N sec, M itr]: objective` lines; a SimAnn
log carries `Elapsed time: ... Best objective: ...` plus a final per-operator stats block.

For SimAnn runs it reports operator usage AND wall-clock share. Share is the number that matters:
a roster is a budget allocation, and proposal counts alone hide an operator that is rare and
expensive. Share is computed as `Total calls x Average call time`, which is what the operator
actually spent, not what it was selected for.
"""
import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from digest_run_log import parse as parse_simann          # noqa: E402

HEX_SAMPLE = re.compile(r"\[\s*(\d+) sec,\s*([\d]+) itr\]:\s*([\d.]+)")
HEX_GAP = re.compile(r"\[ optimality gap\s*\]:\s*([\d.]+)%")
HEX_BREAKDOWN = re.compile(
    r"Cost breakdown for route (\d+) : start_dist=([\d.]+), end_dist=([\d.]+), mid_dist=([\d.]+)")
HEX_PATH = re.compile(r"^\d+, \{'Path': (\[.*?\]), 'Vehicle': (\d+), 'Cost': ([\d.]+)\}", re.M)


def parse_hexaly(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    samples = [{"t": float(s), "best": float(o), "iters": int(i)}
               for s, i, o in HEX_SAMPLE.findall(text)]
    gaps = [float(g) for g in HEX_GAP.findall(text)]
    routes = [{"route": int(r), "start": float(a), "end": float(b), "mid": float(m)}
              for r, a, b, m in HEX_BREAKDOWN.findall(text)]
    paths = []
    for p, v, c in HEX_PATH.findall(text):
        nodes = ast.literal_eval(p)
        paths.append({"nodes": nodes, "vehicle": int(v), "cost": float(c)})
    return samples, gaps, routes, paths


def report_hexaly(name, samples, gaps, routes, paths):
    print(f"\n=== {name} (Hexaly) ===")
    if not samples:
        print("  no samples parsed")
        return
    first, final = samples[0], samples[-1]
    print(f"  budget {final['t']:.0f}s, {final['iters']:,} iterations "
          f"({final['iters']/max(final['t'],1):,.0f} itr/s)")
    print(f"  first feasible {first['best']:,.2f} at {first['t']:.0f}s "
          f"-> final {final['best']:,.2f}")
    if gaps:
        print(f"  reported optimality gap: {gaps[-1]:.2f}%  (its own bound is very loose)")

    # Where the descent actually happened.
    lo, hi = final["best"], first["best"]
    print("\n  time to threshold:")
    for frac in (0.75, 0.5, 0.25, 0.1, 0.0):
        mark = lo + (hi - lo) * frac
        hit = next((s for s in samples if s["best"] <= mark), None)
        if hit:
            print(f"    {mark:>10,.2f}  at {hit['t']:>4.0f}s ({hit['t']/final['t']:5.1%})")
    half = [s for s in samples if s["t"] >= final["t"] / 2]
    if half:
        gain = (half[0]["best"] - final["best"]) / max(half[0]["best"], 1e-9)
        print(f"  second half of the run bought {gain:.3%}")

    print("\n  SOLUTION PROFILE")
    used = [p for p in paths if len(p["nodes"]) > 2]
    empty = len(paths) - len(used)
    print(f"    route slots {len(paths)}, NON-EMPTY {len(used)}, empty {empty}")
    if used:
        sizes = sorted(len(p["nodes"]) - 2 for p in used)
        print(f"    customers per route: min {sizes[0]}, median {sizes[len(sizes)//2]}, "
              f"max {sizes[-1]}")
        print(f"    vehicles used: {sorted({p['vehicle'] for p in used})}")
    if routes:
        tot = sum(r["start"] + r["end"] + r["mid"] for r in routes)
        depot = sum(r["start"] + r["end"] for r in routes)
        print(f"    breakdown over {len(routes)} reported routes: total {tot:,.2f}, "
              f"depot legs {depot:,.2f} ({depot/tot:.1%}), inter-customer {tot-depot:,.2f}")


def report_simann(name, path):
    S, stats, order = parse_simann(path)
    print(f"\n=== {name} (SimAnn) ===")
    if not S:
        print("  no samples parsed")
        return None
    final = S[-1]
    print(f"  budget {final['t']:.0f}s, {final.get('iters',0):,} iterations "
          f"({final.get('iters',0)/max(final['t'],1):,.0f} itr/s)")
    print(f"  start {S[0]['best']:,.2f} -> final {final['best']:,.2f}  "
          f"({(1 - final['best']/S[0]['best']):.2%} reduction)")
    print(f"  plateau reheats {final.get('preheat',0)}, complete {final.get('creheat',0)}")
    half = [s for s in S if s["t"] >= final["t"] / 2]
    if half:
        print(f"  second half bought {(half[0]['best']-final['best'])/half[0]['best']:.3%}")

    rows = []
    for op in order:
        d = stats[op]
        calls = d.get("Total calls", 0)
        secs = calls * d.get("Average call time", 0.0)
        rows.append({
            "op": op, "weight": d.get("LogWeight", -99), "calls": calls,
            "applies": d.get("Total applies", 0), "secs": secs,
            "improving": d.get("Num improving calls", 0),
            "us": 1e6 * d.get("Average call time", 0.0),
            "invalid": d.get("Invalid", 0), "noop": d.get("Noop", 0),
        })
    total_secs = sum(r["secs"] for r in rows) or 1.0
    total_calls = sum(r["calls"] for r in rows) or 1

    print(f"\n  OPERATOR USAGE AND WALL-CLOCK SHARE   "
          f"(accounted {total_secs:.1f}s of {final['t']:.0f}s = {total_secs/final['t']:.0%})")
    print(f"  {'operator':<42} {'calls%':>7} {'TIME%':>7} {'sec':>7} {'acc%':>6} "
          f"{'improving':>9} {'us/call':>8} {'logW':>7}")
    for r in sorted(rows, key=lambda r: -r["secs"]):
        acc = 100 * r["applies"] / r["calls"] if r["calls"] else 0
        print(f"  {r['op']:<42} {100*r['calls']/total_calls:>6.2f}% "
              f"{100*r['secs']/total_secs:>6.2f}% {r['secs']:>7.1f} {acc:>5.2f}% "
              f"{r['improving']:>9,.0f} {r['us']:>8.1f} {r['weight']:>7.2f}")
    return {"samples": S, "rows": rows, "total_secs": total_secs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", default="experiment_logs/run_comparison.png")
    args = ap.parse_args()

    curves = []
    for p in args.paths:
        name = Path(p).name
        text = Path(p).read_text(encoding="utf-8", errors="replace")[:4000]
        if "itr]:" in text:
            samples, gaps, routes, paths = parse_hexaly(p)
            report_hexaly(name, samples, gaps, routes, paths)
            curves.append((name, [(s["t"], s["best"]) for s in samples], "Hexaly"))
        else:
            got = report_simann(name, p)
            if got:
                curves.append((name, [(s["t"], s["best"]) for s in got["samples"]], "SimAnn"))

    plot(curves, args.out)


def plot(curves, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    colors = {"Hexaly": "#c1440e", "SimAnn": None}
    palette = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b"]
    i = 0
    for name, pts, kind in curves:
        if not pts:
            continue
        xs = [t for t, _ in pts]
        ys = [o for _, o in pts]
        if kind == "Hexaly":
            c, lw, ls = colors["Hexaly"], 2.4, "-"
        else:
            c, lw, ls = palette[i % len(palette)], 1.8, "--" if i else "-"
            i += 1
        label = f"{name}  (final {ys[-1]:,.1f})"
        for a in (ax, ax2):
            a.plot(xs, ys, label=label, color=c, linewidth=lw, linestyle=ls)

    ax.set_title("Convergence, full run")
    ax.set_xlabel("elapsed seconds"); ax.set_ylabel("best objective")
    ax.legend(fontsize=9); ax.grid(alpha=.3)

    finals = [pts[-1][1] for _, pts, _ in curves if pts]
    lo = min(finals) * 0.985
    hi = min(finals) * 1.12
    ax2.set_ylim(lo, hi); ax2.set_xlim(0, max(t for _, pts, _ in curves for t, _ in pts))
    ax2.set_title("Same data, zoomed to the endgame")
    ax2.set_xlabel("elapsed seconds"); ax2.set_ylabel("best objective")
    ax2.legend(fontsize=9); ax2.grid(alpha=.3)

    # Instance is read off the runs, not hardcoded -- a stale subtitle is a wrong claim.
    fig.suptitle("Solver comparison -- 500 customers, capacity 400, 3 depots, seed 42",
                 fontsize=12)
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    print(f"\nplot written to {out}")


if __name__ == "__main__":
    sys.exit(main())
