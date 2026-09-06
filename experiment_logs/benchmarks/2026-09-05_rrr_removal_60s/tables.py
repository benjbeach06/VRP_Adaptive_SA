"""Paired analysis of the RandomRouteReassignment A/B.

The two arms are matched per (instance, seed): the same seed, the same construction, and the two
runs back to back on the same machine. So the unit of analysis is the PAIR, not the arm mean.
Reports per-instance means, the paired delta, and a sign test over pairs.

Runs while the sweep is still going -- it reports whatever pairs are complete and says how many.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTANCES = Path(r"C:\Users\Bben6\PycharmProjects\PythonProject"
                 r"\pyvrp_benchmarking\benchmark\instances\CVRP")


def load(arm: str) -> dict[tuple[str, int], dict]:
    path = HERE / f"results_{arm}.jsonl"
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return {(r["instance"], r["seed"]): r for r in recs}


def best_known(name: str) -> int | None:
    sol = INSTANCES / f"{name}.sol"
    if not sol.exists():
        return None
    for line in reversed(sol.read_text().splitlines()):
        if line.lower().startswith("cost"):
            return int(line.split()[-1])
    return None


def mean(xs): return sum(xs) / len(xs)


def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial p at q=0.5. Ties are dropped, the standard convention."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main() -> None:
    base, treat = load("baseline"), load("treatment")
    pairs = sorted(set(base) & set(treat), key=lambda k: (list(ORDER).index(k[0]), k[1]))

    print(f"{len(pairs)} complete pairs of 40 "
          f"({len(base)} baseline runs, {len(treat)} treatment runs)\n")

    problems = [(a, k) for a, d in (("baseline", base), ("treatment", treat))
                for k, r in d.items()
                if not r["feasible"] or r["reported_objective"] != r["cost"]
                or not (60.0 <= r["elapsed"] <= 62.0)]
    print(f"invariant failures: {len(problems)}" + (f"  {problems}" if problems else ""))
    print()

    print("| instance | n | BKS | pairs | baseline | gap% | treatment | gap% | delta% | sd(base) | sd(treat) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")

    all_deltas, wins, losses, ties = [], 0, 0, 0
    for name in ORDER:
        ks = [k for k in pairs if k[0] == name]
        if not ks:
            continue
        b = [base[k]["cost"] for k in ks]
        t = [treat[k]["cost"] for k in ks]
        bks = best_known(name)
        for bi, ti in zip(b, t):
            all_deltas.append(100 * (ti - bi) / bi)
            if ti < bi:
                wins += 1
            elif ti > bi:
                losses += 1
            else:
                ties += 1
        gb = f"{100*(mean(b)-bks)/bks:.2f}" if bks else "-"
        gt = f"{100*(mean(t)-bks)/bks:.2f}" if bks else "-"
        d = 100 * (mean(t) - mean(b)) / mean(b)
        print(f"| {name} | {base[ks[0]]['n']} | {bks} | {len(ks)} | {mean(b):,.0f} | {gb} | "
              f"{mean(t):,.0f} | {gt} | {d:+.2f} | {sd(b):.0f} | {sd(t):.0f} |")

    print()
    print(f"paired delta over {len(all_deltas)} pairs: "
          f"mean {mean(all_deltas):+.2f}%, sd {sd(all_deltas):.2f}%")
    print(f"treatment better on {wins}, worse on {losses}, tied on {ties}; "
          f"sign test p = {sign_test_p(wins, losses):.3f}")
    print("Negative delta means the treatment (operator removed) is CHEAPER.")


ORDER = ["X-n101-k25", "X-n153-k22", "X-n200-k36", "X-n303-k21",
         "X-n401-k29", "X-n502-k39", "X-n701-k44", "X-n1001-k43"]

if __name__ == "__main__":
    main()
