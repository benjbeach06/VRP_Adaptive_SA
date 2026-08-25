"""Plot a cross-commit ablation produced by `tools/ablate_trajectory.py`.

    .venv1/Scripts/python.exe tools/plot_trajectory.py experiment_logs/ablations/<study>

`plot_ablation.py` reads one `results.json` whose arms are values of one parameter. This reads one
folder per COMMIT, which is what a trajectory study produces.

Four panels, because a stage can help or hurt for two different reasons and the endpoint alone
cannot tell them apart:

- **Paired delta per seed** -- did this stage beat the baseline, and on how many seeds.
- **Spread of those deltas** -- the noise floor. A behaviour-neutral arm sits astride zero.
- **Convergence** -- median best objective against elapsed time. Shows WHEN an arm pulled ahead, and
  separates "slow" from "stuck".
- **Throughput** -- median iterations against elapsed time. A stage that costs per-iteration work
  shows up here and nowhere else.

The last two need the `path` field, which `ablate_param.run_once` records per report interval.
"""
import argparse
import json
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402


def load(study: str) -> list[dict]:
    arms = []
    for name in sorted(os.listdir(study)):
        path = os.path.join(study, name, "results.json")
        if os.path.isfile(path):
            arms.append(json.load(open(path, encoding="utf-8")))
    return arms


def finite(runs: list[dict]) -> list[float]:
    return [r["objective"] for r in runs if r["objective"] != float("inf")]


def median_curve(runs: list[dict], column: int) -> tuple[list[float], list[float]]:
    """Median across seeds of one path column, bucketed by whole seconds of elapsed time."""
    buckets: dict[int, list[float]] = {}
    for run in runs:
        for row in run.get("path", []):
            buckets.setdefault(int(round(row[0])), []).append(row[column])
    times = sorted(buckets)
    return times, [statistics.median(buckets[t]) for t in times]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    arms = load(args.study)
    if len(arms) < 2:
        print(f"need at least two arms, found {len(arms)}", file=sys.stderr)
        return 1

    base = arms[0]
    base_obj = [r["objective"] for r in base["runs"]]
    cfg = base["config"]

    fig, ax = plt.subplots(2, 2, figsize=(15, 10))
    labels, deltas = [], []

    for arm in arms[1:]:
        pairs = [(a["objective"], b) for a, b in zip(arm["runs"], base_obj)
                 if a["objective"] != float("inf") and b != float("inf")]
        d = [a - b for a, b in pairs]
        label = f"{arm['label']} ({arm['commit'][:7]})"
        labels.append(label)
        deltas.append(d)
        ax[0][0].plot(range(len(d)), d, marker="o", ms=3, lw=1, label=label)

    ax[0][0].axhline(0, color="k", lw=1)
    ax[0][0].set_xlabel("seed")
    ax[0][0].set_ylabel(f"objective minus {base['label']}")
    ax[0][0].set_title("Paired delta per seed  (negative = better)")
    ax[0][0].legend(fontsize=7)

    ax[0][1].boxplot(deltas, tick_labels=[l.split(" (")[0] for l in labels])
    ax[0][1].axhline(0, color="k", lw=1)
    ax[0][1].set_ylabel(f"objective minus {base['label']}")
    ax[0][1].set_title("Spread of paired deltas")
    ax[0][1].tick_params(axis="x", labelrotation=40, labelsize=7)

    for arm in arms:
        t, y = median_curve(arm["runs"], 1)
        if t:
            ax[1][0].plot(t, y, lw=1.2, label=f"{arm['label']} ({arm['commit'][:7]})")
        t, it = median_curve(arm["runs"], 2)
        if t:
            ax[1][1].plot(t, it, lw=1.2, label=arm["label"])

    ax[1][0].set_xlabel("elapsed seconds")
    ax[1][0].set_ylabel("median best objective")
    ax[1][0].set_title("Convergence  (lower is better)")
    ax[1][0].legend(fontsize=7)

    ax[1][1].set_xlabel("elapsed seconds")
    ax[1][1].set_ylabel("median iterations")
    ax[1][1].set_title("Throughput")
    ax[1][1].legend(fontsize=7)

    n = len(finite(base["runs"]))
    fig.suptitle(f"Scoring rework trajectory -- n={cfg.get('size')} capacity 400, "
                 f"{cfg.get('seconds'):g}s, {n} paired seeds, baseline {base['label']}")
    fig.tight_layout()
    out = args.out or os.path.join(args.study, "trajectory.png")
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")

    print(f"\n--- vs {base['label']} ---")
    for arm, d in zip(arms[1:], deltas):
        vals = finite(arm["runs"])
        mean = sum(vals) / len(vals) if vals else float("nan")
        if len(d) > 1:
            m = statistics.fmean(d)
            sem = statistics.stdev(d) / len(d) ** 0.5
            print(f"  {arm['label']:<32} mean {mean:9.2f}   {m:+8.2f} +/- {sem:5.2f}   "
                  f"{m / sem if sem else 0:+5.1f} sigma   won {sum(x < 0 for x in d)}/{len(d)}")
        else:
            print(f"  {arm['label']:<32} mean {mean:9.2f}   too few paired runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
