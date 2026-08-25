"""Pick a robust point from a completed tune.py study -- the CENTER of the good-scoring region,
never the argmin.

    .venv1/Scripts/python.exe tools/pick_tuned_center.py \
        experiment_logs/tuning/2026-08-23_six_param_time_based.json --top-frac 0.2

The single best trial in a noisy search is not a good default -- it is disproportionately likely to
be a lucky draw, not a genuinely better configuration (see project-vrp-schedule-tuning-exhausted:
the 149-trial operator-selection search's "winner" was LESS extreme than pure noise predicts for
that many draws). This picks the top `--top-frac` of finite-score trials, takes the per-parameter
MEDIAN in log space (every searched parameter here is log-scaled), then reports the ACTUAL trial in
that bucket nearest to that median point -- a real, tested configuration, not a synthetic blend that
was never run and could combine parameters in an untested interaction.

Writes the chosen trial's params as JSON, ready for tools/ablate_tuned_vs_stage1.py --params.
"""
import argparse
import json
import math
import sys


def log_or_linear(name: str, value: float, search_space: dict) -> float:
    kind, low, high, log = search_space[name]
    return math.log(max(value, 1e-12)) if log else value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tune_results", help="tune.py's --out JSON")
    ap.add_argument("--top-frac", type=float, default=0.2,
                    help="fraction of finite-score trials treated as the good region")
    ap.add_argument("--out", default=None, help="write the chosen params here as JSON")
    args = ap.parse_args()

    with open(args.tune_results, "r", encoding="utf-8") as f:
        state = json.load(f)

    search_space = state["search_space"]
    names = sorted(search_space)
    trials = [t for t in state["trials"] if t["value"] == t["value"] and t["value"] != float("inf")]
    if not trials:
        print("no finite trials in this study", file=sys.stderr)
        return 1

    trials.sort(key=lambda t: t["value"])
    n_top = max(1, int(round(len(trials) * args.top_frac)))
    bucket = trials[:n_top]

    print(f"{len(trials)} finite trials of {len(state['trials'])} total; "
          f"top {args.top_frac:.0%} = {n_top} trials, "
          f"scores {bucket[0]['value']:.4f} .. {bucket[-1]['value']:.4f} "
          f"(1.0 == defaults)")

    # Per-parameter median in log space across the bucket.
    medians = {}
    for name in names:
        vals = sorted(log_or_linear(name, t["params"][name], search_space) for t in bucket)
        mid = len(vals) // 2
        medians[name] = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2

    # Nearest ACTUAL trial to that median point, normalized per-parameter by the bucket's own
    # log-space spread so no single wide-range parameter dominates the distance.
    spreads = {}
    for name in names:
        vals = [log_or_linear(name, t["params"][name], search_space) for t in bucket]
        spreads[name] = (max(vals) - min(vals)) or 1.0

    def dist(trial) -> float:
        return math.sqrt(sum(
            ((log_or_linear(name, trial["params"][name], search_space) - medians[name])
             / spreads[name]) ** 2
            for name in names))

    center = min(bucket, key=dist)

    print(f"\nchosen trial {center['number']}: score {center['value']:.4f}, "
          f"distance {dist(center):.3f} from bucket median")
    print(f"{'parameter':<26} {'chosen':>14} {'bucket median':>14} {'default':>14}")
    for name in names:
        median_value = (math.exp(medians[name]) if search_space[name][3] else medians[name])
        print(f"{name:<26} {center['params'][name]!r:>14} {median_value:>14.4g} "
              f"{state['defaults'][name]!r:>14}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(center["params"], f, indent=2)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
