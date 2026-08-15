"""
Re-measure the top configurations from a tune.py search, reporting RAW objectives.

PROVENANCE
----------
Written by Claude (Anthropic) during development assistance; not hand-written by the repository
author. Written because tune.py stores only normalized scores, so "what objective did the best
configuration actually reach" could not be answered from its results at all.

    python tools/validate.py --top 3 --runs 10 --seconds 60
    python tools/validate.py --top 3 --runs 10 --seconds 240 --seed-offset 200   # 4x length

WHY THIS EXISTS, AND WHAT IT DOES DIFFERENTLY FROM tune.py:

  * RAW OBJECTIVES. tune.py divides everything by a reference and averages the ratio across
    sizes, so a 0.42% score is not interpretable in the units anyone actually cares about. Here
    every individual run's objective is kept and reported.

  * PAIRED COMPARISON. Each configuration is run on the SAME seed set as the defaults. Because
    seeding also fixes the initial solution, the paired difference cancels a large share of the
    run-to-run variance that swamped the search. tune.py compared independent means, where the
    measurement error on one configuration was ~25 objective units at size 200 -- larger than the
    gap it was trying to resolve.

  * UNSEEN SEEDS. The search scored every configuration on seeds 0..runs_per_size-1. Re-measuring
    on those seeds would report the value the sampler already selected for, so --seed-offset
    moves the whole set clear of them. Defaults to 100.

  * The reference configuration is measured here too, in the same pass and on the same seeds, so
    the comparison never depends on a number carried over from the search.

initial_temp_factor is held at tune.FIXED, exactly as it was during the search.
"""
import argparse, json, os, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Reusing tune.py's instance builder, solver_kwargs and run_once is deliberate: a local copy
# would silently drift from the thing being validated.
import tune


def measure(params: dict, size: int, seeds: list[int], seconds: float) -> list[float]:
    return [tune.run_once(params, size, seed, seconds) for seed in seeds]


def summarize(values: list[float]) -> dict:
    finite = [v for v in values if v == v and v != float("inf")]
    if not finite:
        return {"n": 0, "failed": len(values)}
    return {
        "n": len(finite),
        "failed": len(values) - len(finite),
        "mean": statistics.fmean(finite),
        "min": min(finite),
        "max": max(finite),
        "stdev": statistics.stdev(finite) if len(finite) > 1 else 0.0,
    }


def paired(candidate: list[float], baseline: list[float]) -> dict | None:
    """Per-seed differences (candidate - baseline). Negative means the candidate is better."""
    pairs = [(c, b) for c, b in zip(candidate, baseline)
             if c == c and b == b and c != float("inf") and b != float("inf")]
    if len(pairs) < 2:
        return None
    diffs = [c - b for c, b in pairs]
    mean = statistics.fmean(diffs)
    stdev = statistics.stdev(diffs)
    stderr = stdev / len(diffs) ** 0.5
    return {
        "n": len(diffs),
        "mean_diff": mean,
        "stdev_diff": stdev,
        "stderr_diff": stderr,
        # Not a p-value. It is "how many standard errors from zero", which is the useful
        # quantity when deciding whether a gap is worth acting on.
        "sigmas": mean / stderr if stderr > 0 else 0.0,
        "wins": sum(1 for d in diffs if d < 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(ROOT, "tools", "tune_results.json"))
    ap.add_argument("--top", type=int, default=3, help="how many best configurations to re-measure")
    ap.add_argument("--runs", type=int, default=10, help="runs per configuration per size")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--sizes", type=int, nargs="+", default=[60, 200])
    ap.add_argument("--seed-offset", type=int, default=100,
                    help="first seed; keep clear of the seeds tune.py scored on")
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "validate_results.json"))
    args = ap.parse_args()

    with open(args.results) as handle:
        results = json.load(handle)

    trials = [t for t in results["trials"]
              if t["value"] == t["value"] and t["value"] != float("inf")]
    best = sorted(trials, key=lambda t: t["value"])[:args.top]

    configs = [("defaults", dict(tune.DEFAULTS))]
    configs += [(f"trial{t['number']}", dict(t["params"])) for t in best]

    seeds = list(range(args.seed_offset, args.seed_offset + args.runs))
    total = len(configs) * len(args.sizes) * args.runs * args.seconds
    print(f"re-measuring {len(configs)} configurations x {len(args.sizes)} sizes x {args.runs} "
          f"runs x {args.seconds:.0f}s")
    print(f"seeds {seeds[0]}..{seeds[-1]} (search used 0..{results['config']['runs_per_size']-1})")
    print(f"fixed: {tune.FIXED}")
    print(f"estimated wall time: {total/60:.0f} min\n", flush=True)

    state = {
        "source": os.path.basename(args.results),
        "config": {"runs": args.runs, "seconds": args.seconds, "sizes": args.sizes,
                   "seeds": seeds, "fixed": tune.FIXED},
        "configs": {name: params for name, params in configs},
        "raw": {}, "summary": {}, "paired": {},
    }

    for size in args.sizes:
        print(f"--- size {size} " + "-" * 52)
        raw: dict[str, list[float]] = {}
        for name, params in configs:
            raw[name] = measure(params, size, seeds, args.seconds)
            s = summarize(raw[name])
            state["raw"].setdefault(str(size), {})[name] = raw[name]
            state["summary"].setdefault(str(size), {})[name] = s
            if s["n"] == 0:
                print(f"  {name:10}  ALL {s['failed']} RUNS FAILED")
                continue
            print(f"  {name:10}  mean {s['mean']:9.2f}   min {s['min']:9.2f}   "
                  f"sd {s['stdev']:6.2f}   n={s['n']}"
                  + (f"   FAILED {s['failed']}" if s["failed"] else ""), flush=True)

        print(f"\n  paired vs defaults (negative = better, same seeds):")
        for name, _ in configs[1:]:
            p = paired(raw[name], raw["defaults"])
            state["paired"].setdefault(str(size), {})[name] = p
            if p is None:
                print(f"  {name:10}  not enough paired runs")
                continue
            print(f"  {name:10}  {p['mean_diff']:+8.2f} +/- {p['stderr_diff']:5.2f}   "
                  f"{p['sigmas']:+5.1f} sigma   won {p['wins']}/{p['n']} seeds")
        print()

        with open(args.out, "w") as handle:
            json.dump(state, handle, indent=2, default=float)

    if tune.FAILURES:
        print("failed runs:")
        for message, count in tune.FAILURES.items():
            print(f"    {count:4d}x  {message}")

    print(f"results written to {args.out}")
    print("\nA gap under ~2 sigma is not worth acting on; the search itself could not resolve "
          "below ~25 objective units at size 200, and pairing only narrows that.")


if __name__ == "__main__":
    main()
