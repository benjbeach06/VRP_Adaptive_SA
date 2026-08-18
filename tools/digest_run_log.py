"""Condense a solver run log into the parts worth reading.

    tools/digest_run_log.py experiment_logs/Robustness_Smoke_Test.txt

A 10-minute run prints ~2000 lines, most of it a 20-operator weight vector once per second. Reading
that by eye means skimming past the three things that actually carry information:

  1. the best-objective schedule -- where the descent happens, not that it happened
  2. the final per-operator stats, ordered so cheap-high-volume operators are visible
  3. discontinuities in individual operator weights, aligned against reheats

A weight jump AT a reheat is the mechanism working. A jump that is not at a reheat means an
operator's value changed phase mid-run, which is the interesting case and the one a wall of numbers
hides.
"""
import argparse
import ast
import math
import re
import statistics
import sys

SAMPLE = re.compile(
    r"Elapsed time: ([\d.]+) seconds, Best objective: ([\d.]+), Current objective: ([-\d.e+]+)")
STATE = re.compile(
    r"Log2 Temperature: ([-\d.]+), Complete reheats: (\d+), Plateau reheats: (\d+), Iterations: (\d+)")
STATBLOCK = re.compile(r"Stats for operator (\w+):")


def parse(path):
    samples, stats, order = [], {}, []
    cur = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if m := SAMPLE.search(line):
                samples.append({"t": float(m[1]), "best": float(m[2]), "curr": float(m[3])})
            elif m := STATE.search(line):
                if samples:
                    samples[-1].update(logT=float(m[1]), creheat=int(m[2]),
                                       preheat=int(m[3]), iters=int(m[4]))
            elif line.startswith("op weights:") and samples:
                samples[-1]["w"] = dict(ast.literal_eval(line.split(":", 1)[1].strip()))
            elif m := STATBLOCK.search(line):
                cur = m[1]
                stats[cur] = {}
                order.append(cur)
            elif cur:
                for k, v in re.findall(r"([A-Za-z ]+?): ([-\d.e+]+)", line):
                    stats[cur][k.strip()] = float(v)
    return [s for s in samples if "w" in s], stats, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--jump-factor", type=float, default=2.0,
                    help="flag a weight change of this ratio or more between samples")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    S, stats, order = parse(args.path)
    if not S:
        print("no samples parsed")
        return 1
    ops = list(S[0]["w"])
    final = S[-1]

    print(f"=== RUN === {len(S)} samples, {final['t']:.0f}s, {final.get('iters',0):,} iterations")
    print(f"start {S[0]['best']:,.0f} -> final {final['best']:,.2f}   "
          f"({S[0]['best']/max(final['best'],1e-9):,.0f}x reduction)")
    print(f"plateau reheats {final.get('preheat',0)}, complete reheats {final.get('creheat',0)}")

    # ---- 1. best-objective schedule, by milestone rather than by second -------------
    print("\n=== BEST-OBJECTIVE SCHEDULE ===")
    print("  time to cross each threshold (first sample at or below):")
    lo, hi = final["best"], S[0]["best"]
    marks = [hi * 0.5, hi * 0.1, hi * 0.01, hi * 0.001]
    marks += [lo * m for m in (1.5, 1.2, 1.1, 1.05, 1.02, 1.01, 1.0)]
    for mk in sorted({round(m, 2) for m in marks if lo <= m <= hi}, reverse=True):
        hit = next((s for s in S if s["best"] <= mk), None)
        if hit:
            print(f"    {mk:>12,.2f}   at {hit['t']:>6.0f}s  ({hit['t']/final['t']:5.1%} of budget)")

    print("\n  largest single-sample drops:")
    drops = sorted(((S[i-1]["best"] - S[i]["best"], S[i]["t"]) for i in range(1, len(S))),
                   reverse=True)[:6]
    for d, t in drops:
        print(f"    {d:>12,.2f}   at {t:>6.0f}s")

    tail = [s for s in S if s["t"] >= final["t"] * 0.5]
    gain = (tail[0]["best"] - final["best"]) / max(tail[0]["best"], 1e-9)
    print(f"\n  second half of the run bought {gain:.3%} "
          f"({tail[0]['best']:,.2f} -> {final['best']:,.2f})")

    # ---- 2. reheats -----------------------------------------------------------------
    rh = [S[i] for i in range(1, len(S))
          if S[i].get("preheat", 0) > S[i-1].get("preheat", 0)]
    if rh:
        # Gain is measured over THIS reheat's window -- up to the next reheat -- not to the end of
        # the run. Cumulative-to-end is monotonic by construction, so it marks every reheat before
        # the final improvement as productive and tells you nothing.
        bounds = [s["t"] for s in rh] + [final["t"] + 1]
        wins = []
        for i, s in enumerate(rh):
            window = [x for x in S if s["t"] < x["t"] <= bounds[i + 1]]
            got = s["best"] - min((x["best"] for x in window), default=s["best"])
            wins.append((got, s))
        productive = [w for w in wins if w[0] > 0]
        print(f"\n=== PLATEAU REHEATS ({len(rh)}) ===")
        print(f"    {len(productive)}/{len(rh)} produced a new best before the next reheat")
        print(f"    total gain attributed to reheats: {sum(g for g, _ in wins):,.2f}")
        print(f"    first at {rh[0]['t']:.0f}s, last at {rh[-1]['t']:.0f}s, "
              f"median gap {statistics.median([b - a for a, b in zip(bounds, bounds[1:-1])]):.0f}s")
        print("\n    most productive:")
        for got, s in sorted(wins, key=lambda w: -w[0])[:6]:
            print(f"      t={s['t']:>6.0f}s  best={s['best']:>10,.2f}  log2T {s['logT']:>7.2f}"
                  f"   gained {got:>8,.2f}")
        dead = next((i for i, (g, _) in enumerate(wins) if all(x == 0 for x, _ in wins[i:])), None)
        if dead is not None:
            print(f"\n    last {len(wins)-dead} reheats (from t={wins[dead][1]['t']:.0f}s) "
                  f"produced nothing")

    # ---- 3. weight jumps ------------------------------------------------------------
    print(f"\n=== WEIGHT JUMPS (>= {args.jump_factor}x between samples) ===")
    reheat_t = {s["t"] for s in rh}
    jumps = []
    for op in ops:
        for i in range(1, len(S)):
            a, b = S[i-1]["w"][op], S[i]["w"][op]
            if a <= 1e-12 or b <= 1e-12:
                continue
            r = b / a
            if r >= args.jump_factor or r <= 1 / args.jump_factor:
                jumps.append((abs(math.log(r)), S[i]["t"], op, a, b, r))
    jumps.sort(reverse=True)
    if not jumps:
        print("    none")
    else:
        at_reheat = sum(1 for j in jumps if j[1] in reheat_t)
        print(f"    {len(jumps)} jumps; {at_reheat} coincide with a reheat sample, "
              f"{len(jumps)-at_reheat} do not")
        print(f"\n    largest {args.top}:")
        for _, t, op, a, b, r in jumps[:args.top]:
            tag = "  [REHEAT]" if t in reheat_t else ""
            print(f"      t={t:>6.0f}s  {op:<40} {a:>9.3f} -> {b:>9.3f}  ({r:>7.2f}x){tag}")
        by_op = {}
        for _, t, op, *_ in jumps:
            by_op.setdefault(op, []).append(t)
        print("\n    operators by jump count:")
        for op, ts in sorted(by_op.items(), key=lambda kv: -len(kv[1]))[:args.top]:
            print(f"      {op:<42} {len(ts):>3}   first {min(ts):>5.0f}s  last {max(ts):>5.0f}s")

    # ---- 4. final operator stats ----------------------------------------------------
    print("\n=== FINAL OPERATOR STATS ===")
    print(f"  {'operator':<42} {'weight':>8} {'proposals':>10} {'applies':>8} {'acc%':>6} "
          f"{'improving':>9} {'us/call':>8}")
    rows = []
    for op in order:
        d = stats[op]
        prop = d.get("Total proposals", 0)
        rows.append((d.get("LogWeight", -99), op, prop, d.get("Total applies", 0),
                     100 * d.get("Total applies", 0) / prop if prop else 0,
                     d.get("Num improving calls", 0), 1e6 * d.get("Average call time", 0)))
    for lw, op, prop, ap_, acc, imp, us in sorted(rows, key=lambda r: -r[0]):
        print(f"  {op:<42} {lw:>8.2f} {prop:>10,.0f} {ap_:>8,.0f} {acc:>5.2f}% "
              f"{imp:>9,.0f} {us:>8.1f}")

    finalw = final["w"]
    live = {k: v for k, v in finalw.items() if v > 0}
    if live:
        print(f"\n  final weight spread: {max(live.values())/min(live.values()):,.1f}x "
              f"(max {max(live.values()):.3f}, min {min(live.values()):.3g})")
        print(f"  median final weight: {statistics.median(live.values()):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
