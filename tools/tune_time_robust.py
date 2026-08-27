"""
Time-robust variant of tools/tune.py.

tools/tune.py scores every trial at ONE fixed seconds_per_run (many seeds, same runtime). That
finds parameters that are good at that one runtime, but says nothing about whether they are good
across runtimes -- a parameter set that only pays off once a plateau has had 200 seconds to form
would look identical, in that search, to one that is robust from 60s to 300s.

This script scores every trial across FIVE DIFFERENT RUNTIMES (1, 2, 3, 4, 5 minutes), one seed
each, instead of several seeds at one runtime. A configuration that only works at one point on the
schedule can no longer hide behind an average over restatements of the same runtime.

Same six SEARCH_SPACE parameters as tools/tune.py, imported from it directly rather than
redefined, so the two searches stay comparable and a bound change only has to happen once.

STARTING POINT: the enqueued trial 0 is CHOSEN_CENTER, the 2026-08-23 8-hour single-runtime
search's chosen result (experiment_logs/tuning/2026-08-23_chosen_center.json) -- not the solver's
original hand-picked defaults. This search starts from where that one left off, since that is the
current best-known point and the thing being tested here is its robustness across runtimes, not
whether it beats the hand defaults again.

REFERENCE (used to normalize every trial's per-runtime score) is measured with more seeds per
runtime than any one trial gets, since the reference is reused by every trial in the whole run and
its own noise floor matters more than any single trial's. See REFERENCE_SEEDS_PER_RUNTIME.

    python tools/tune_time_robust.py --budget-seconds 64800

Results are written to the output JSON after every trial, so an interrupted run keeps its work.
"""
import argparse, json, os, statistics, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import optuna

import tune
from tune import SEARCH_SPACE, build_instance, run_once, FAILURES  # noqa: F401
from run_stamp import solver_stamp

# Reference VRP instance -- n=500, capacity=400. Matches tune.py and the rest of this project's
# experiments; see the project convention of naming the instance in every plan.
SIZE = 500
CAPACITY = 400

# Five runtimes, one seed each, per trial. Different seeds per runtime (not the same seed reused)
# so a lucky/unlucky seed at one runtime cannot be mistaken for a runtime effect.
RUNTIMES_SECONDS = [60.0, 120.0, 180.0, 240.0, 300.0]
SEEDS = [1, 2, 3, 4, 5]

# The reference is reused by every trial in the whole search, so it gets more seeds than any one
# trial does -- its own noise is a fixed cost paid once, not something averaged away per trial.
REFERENCE_SEEDS_PER_RUNTIME = 5

CHOSEN_CENTER_PATH = os.path.join(ROOT, "experiment_logs", "tuning", "2026-08-23_chosen_center.json")


def load_chosen_center() -> dict:
    with open(CHOSEN_CENTER_PATH) as f:
        params = json.load(f)
    # segment_length must be an int for tune.solver_kwargs / Optuna's suggest_int enqueue.
    params["segment_length"] = int(round(params["segment_length"]))
    return params


CHOSEN_CENTER = load_chosen_center()


def score_one_trial(params: dict, reference: dict) -> tuple[float, dict]:
    """Mean over the five (seed, runtime) pairs of objective / reference[runtime].
    Returns (score, per_runtime_raw) so raw objectives are recoverable from the log, not just
    the normalized score."""
    ratios = []
    raw = {}
    for seed, seconds in zip(SEEDS, RUNTIMES_SECONDS):
        obj = run_once(params, SIZE, seed, seconds)
        raw[str(seconds)] = obj
        if obj == float("inf"):
            return float("inf"), raw
        ratios.append(obj / reference[str(seconds)])
    return statistics.fmean(ratios), raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=64_800.0)  # 18 hours
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "tune_time_robust_results.json"))
    args = ap.parse_args()

    for name, value in CHOSEN_CENTER.items():
        kind, low, high, _log = SEARCH_SPACE[name]
        assert low <= value <= high, (
            f"CHOSEN_CENTER[{name!r}] = {value} is outside its own SEARCH_SPACE bound "
            f"[{low}, {high}]")
    assert set(CHOSEN_CENTER) == set(SEARCH_SPACE), (
        f"CHOSEN_CENTER and SEARCH_SPACE must name the same parameters. "
        f"CHOSEN_CENTER only: {set(CHOSEN_CENTER) - set(SEARCH_SPACE)}; "
        f"SEARCH_SPACE only: {set(SEARCH_SPACE) - set(CHOSEN_CENTER)}")

    started = time.perf_counter()
    print(f"time-robust tuning {sorted(SEARCH_SPACE)} at n={SIZE} capacity={CAPACITY}; "
          f"runtimes {RUNTIMES_SECONDS}s, seeds {SEEDS}; budget {args.budget_seconds:.0f}s",
          flush=True)
    print(f"  starting point (CHOSEN_CENTER): {CHOSEN_CENTER}", flush=True)

    tune.CAPACITY = CAPACITY

    try:
        probe_sln = build_instance(SIZE)
        from SimAnn_VRP_Solver import SimAnnVRPSolver
        SimAnnVRPSolver(probe_sln, max_time=1.0, **tune.solver_kwargs(CHOSEN_CENTER))
        print("  CHOSEN_CENTER constructs cleanly", flush=True)
    except Exception as exc:
        print(f"\nABORT: CHOSEN_CENTER/solver_kwargs cannot construct a solver: "
              f"{type(exc).__name__}: {exc}")
        sys.exit(1)

    # Reference: CHOSEN_CENTER, measured at each runtime with REFERENCE_SEEDS_PER_RUNTIME seeds,
    # distinct from the per-trial SEEDS so the reference's own noise is an independent estimate.
    reference = {}
    ref_seed_base = 1000
    for seconds in RUNTIMES_SECONDS:
        seeds = range(ref_seed_base, ref_seed_base + REFERENCE_SEEDS_PER_RUNTIME)
        runs = [run_once(CHOSEN_CENTER, SIZE, s, seconds) for s in seeds]
        reference[str(seconds)] = statistics.fmean(runs)
        print(f"  reference (CHOSEN_CENTER) {seconds:g}s: {reference[str(seconds)]:.2f} "
              f"({REFERENCE_SEEDS_PER_RUNTIME} seeds)", flush=True)

    if any(v == float("inf") or v != v for v in reference.values()):
        print("\nABORT: CHOSEN_CENTER did not produce a finite objective at every runtime.")
        for message, count in FAILURES.items():
            print(f"  {count:4d}x  {message}")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=12345))
    study.enqueue_trial(CHOSEN_CENTER)  # evaluate the starting point as trial 0

    state = {
        "_solver": solver_stamp(),
        "_how_run": "tools/tune_time_robust.py -- 5 runtimes x 1 seed each per trial, "
                    "starting from CHOSEN_CENTER (2026-08-23_chosen_center.json)",
        "config": {"size": SIZE, "capacity": CAPACITY, "runtimes_seconds": RUNTIMES_SECONDS,
                   "seeds": SEEDS, "reference_seeds_per_runtime": REFERENCE_SEEDS_PER_RUNTIME,
                   "budget_seconds": args.budget_seconds},
        "reference": reference,
        "chosen_center": CHOSEN_CENTER,
        "search_space": {k: list(v) for k, v in SEARCH_SPACE.items()},
        "trials": [],
    }

    def objective(trial: optuna.Trial) -> float:
        params = {}
        for name, (kind, low, high, log) in SEARCH_SPACE.items():
            if kind == "int":
                params[name] = trial.suggest_int(name, int(low), int(high), log=log)
            else:
                params[name] = trial.suggest_float(name, low, high, log=log)
        value, raw = score_one_trial(params, reference)
        state["trials"].append({"number": trial.number, "params": params, "value": value,
                                 "raw_by_runtime": raw})
        with open(args.out, "w") as handle:
            json.dump(state, handle, indent=2, default=float)
        elapsed = time.perf_counter() - started
        if trial.number % 5 == 0 or value < 0.99:
            print(f"  trial {trial.number:4d}  score {value:.4f}  ({elapsed:.0f}s elapsed)",
                  flush=True)
        return value

    def out_of_time(study_, trial_) -> None:
        if time.perf_counter() - started > args.budget_seconds:
            study_.stop()

    study.optimize(objective, callbacks=[out_of_time])

    state["best"] = {"params": study.best_params, "value": study.best_value}
    state["failures"] = dict(FAILURES)
    with open(args.out, "w") as handle:
        json.dump(state, handle, indent=2, default=float)

    print(f"\ncompleted {len(study.trials)} trials in {time.perf_counter() - started:.0f}s")
    if FAILURES:
        print("failed runs (scored inf):")
        for message, count in FAILURES.items():
            print(f"    {count:4d}x  {message}")
    print(f"best score {study.best_value:.4f}  (1.0 == CHOSEN_CENTER)")
    for name, value in study.best_params.items():
        print(f"    {name:24} {value!r:>14}   (CHOSEN_CENTER {CHOSEN_CENTER[name]!r})")
    print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
