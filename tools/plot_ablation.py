"""Plot one ablation's paired deltas.

    .venv1/Scripts/python.exe tools/plot_ablation.py experiment_logs/ablations/<folder>

Reads `results.json` from the folder and writes `deltas.png` beside it. Every ablation gets one, in
the same two-panel format, so two ablations can be compared by eye without re-deriving a chart.

Left panel: the paired delta per seed, one line per arm. This is where a table hides things -- an
arm can win on the mean while losing on most seeds, or win everywhere by a little.

Right panel: the spread of those deltas. A replicate arm, identical to the control, sits astride
zero and shows the noise floor the other arms are judged against.

Control is the FIRST value in the run's `--values` list, as `ablate_param.py` reports it.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

try:
    from ablation_arms import ARMS
except Exception:                                                  # not an arm sweep
    ARMS = {}


def arm_label(param: str, value: float) -> str:
    if param == "ablation_arm" and int(value) in ARMS:
        return f"{int(value)}: {ARMS[int(value)][0]}"
    return f"{param}={value:g}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    doc = json.load(open(os.path.join(args.folder, "results.json"), encoding="utf-8"))
    cfg = doc["config"]
    param = cfg.get("param", "value")
    values = [float(v) for v in cfg["values"]]
    control, arms = values[0], values[1:]
    res = {float(k): [x["objective"] for x in v] for k, v in doc["results"].items()}

    base = res[control]
    series = {}
    for v in arms:
        pairs = [(a, b) for a, b in zip(res[v], base)
                 if a != float("inf") and b != float("inf")]
        series[v] = [a - b for a, b in pairs]

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    for v in arms:
        ax[0].plot(range(len(series[v])), series[v], marker="o", ms=4, lw=1,
                   label=arm_label(param, v))
    ax[0].axhline(0, color="k", lw=1)
    ax[0].set_xlabel("seed")
    ax[0].set_ylabel(f"objective minus control ({arm_label(param, control)})")
    ax[0].set_title("Paired delta per seed  (negative = better)")
    ax[0].legend(fontsize=8)

    ax[1].boxplot([series[v] for v in arms],
                  tick_labels=[arm_label(param, v) for v in arms])
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set_ylabel("objective minus control")
    ax[1].set_title("Spread of paired deltas")
    ax[1].tick_params(axis="x", labelrotation=30, labelsize=8)

    n = len(base)
    fig.suptitle(f"n={cfg.get('size')} capacity={cfg.get('capacity')}, "
                 f"{cfg.get('seconds'):g}s, {n} paired seeds, start={cfg.get('start')}")
    fig.tight_layout()
    out = args.out or os.path.join(args.folder, "deltas.png")
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
