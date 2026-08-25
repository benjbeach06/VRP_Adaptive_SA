"""
Hyperparameter search over SimAnnVRPSolver's "magic numbers", using Optuna (TPE).

PROVENANCE
----------
Written by Claude (Anthropic) during development assistance; not hand-written by the repository
author. The METHOD below is the author's, and corrected a worse proposal: Claude suggested fixing
the iteration count and forcing deterministic weighting to get a quieter objective. The author
rejected that -- it would tune a solver nobody runs -- and specified keeping production
nondeterminism while averaging ten short runs per configuration instead. That reduces the variance
of the estimator rather than changing the system being measured, and it is why these results
transfer to real solves.

    python tools/tune.py --budget-seconds 28800

2026-08-23: SEARCH_SPACE was rebuilt for the time-based schedule (SimAnn_VRP_Solver.py, commit
4aaf2c3). Weight decay, cooling, and plateau detection all read wall-clock seconds now instead of
iteration counts, and segment_length is no longer confounded with any of them -- it is a pure
sampling rate. The author's explicit instruction: tune all six live schedule/selection parameters
TOGETHER, not a subset -- their earlier scoring behaviour was measured under a mechanism that no
longer exists (see RESULTS.md, "The scoring cannot price rarity against cost"), so nothing about
this landscape should be assumed flat before it is searched.

    python tools/tune.py --budget-seconds 28800

METHOD -- and why it is shaped this way:

  * Production settings, deliberately. Runs use wall-clock termination, the normal timing-based
    operator weighting, and the normal time-based schedule -- the solver exactly as shipped.
    Fixing the iteration count and forcing deterministic weighting would give a much quieter
    objective, but it would be tuning a solver nobody runs.

  * Noise is handled by AVERAGING, not by removing it. Each configuration is scored over
    RUNS_PER_SIZE short runs at each instance size rather than one long run. Short-and-many beats
    long-and-few here because the run-to-run spread is large, so the variance of the mean is what
    matters.

  * Scores are normalized per instance size against a reference configuration (the current
    defaults), because raw objectives differ by an order of magnitude between different sizes and
    would otherwise let the largest size dominate the mean.

  * SEGMENT_LENGTH IS NOW A PURE SAMPLING RATE. In the old iteration-based schedule it silently
    set both the weight EMA's memory length and the plateau reheat frequency, which forced a
    reparameterisation (K/L independence) just to search it in isolation. The time-based schedule
    removes both couplings: weight decay reads weight_time_constant directly, and plateau length
    reads max_plateau_seconds directly. segment_length now controls only how often weights are
    RECOMPUTED, nothing about what they converge to.

  * BAYES_MAGNET is searched via 1 - Bayes_magnet, log-scaled, the same treatment one_minus_K
    got previously -- the parameter itself lives in (0.9, 0.9999) across the useful range and has
    no resolution on a linear or even a naive log scale there.

  * cooling_rate_per_second and max_plateau_seconds and plateau_reheat_exponent were EXCLUDED from
    every previous search (2026-08-11, 704 trials; 2026-08-16, 149 trials) on the argument that the
    reheat equilibrium (gap = C x S x R) makes C and R self-damping through S, so only the plateau
    quantity P is expected to resolve cleanly. That argument was derived for the ITERATION-based
    schedule. Whether it still holds in seconds is UNTESTED, not assumed -- hence tuning all six
    together tonight rather than re-excluding two of them on an argument that predates this code.

Results are written to the output JSON after every trial, so an interrupted run keeps its work.
"""
import argparse, contextlib, io, json, os, statistics, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import optuna

import SimAnn_VRP_Core_Model as CM
from SimAnn_VRP_Core_Model import Customer, Depot, FullSolution, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver
from run_stamp import solver_stamp          # noqa: E402


# Vehicle capacity for the tuning instance. 400 gives few long routes, which is the regime the
# operator roster was last measured in; 25 gives many short ones and is a different problem.
# This is the REFERENCE instance -- n=500, capacity=400 -- unless a caller overrides it.
CAPACITY = 400

# Each entry: name -> (optuna suggest kind, low, high, log?). Extend this to widen the search;
# nothing else needs to change. Every bound was set together with the repo author on 2026-08-23,
# and every DEFAULTS value below falls inside its own bound so trial 0 (the enqueued status quo)
# is a legal point, not an edge case.
SEARCH_SPACE = {
    # Pure sampling rate: how often weights are recomputed. No schedule coupling any more -- see
    # the module docstring.
    "segment_length":            ("int",   1,    1000, True),
    # log2-temperature halvings per SECOND. Default 4.47 derived from the shipped per-iteration
    # cooling_factor at a measured ~31,000 itr/s. 1.0 is roughly the author's stated floor -- one
    # halving per second is close to what the old segment-based schedule already ran at ("current
    # segment-based is close to 5"). 50 gives an order of magnitude of faster cooling above that.
    "cooling_rate_per_second":   ("float", 1.0,  50.0, True),
    # Half-life, in SECONDS OF THE OPERATOR'S OWN TIME, of the weight EMA. Default 0.019 is
    # calibrated to be neutral for an operator holding the roster's average clock share.
    "weight_time_constant":      ("float", 2e-4, 2.0,  True),
    # Seconds without an improving move before a plateau reheat fires. Floor 0.25s so a very fast
    # trial cannot make this degenerate; author's floor of "5-50s, so a run gets at least some
    # time to focus on exploitation, and 50s guarantees >=2 plateaus" was widened down to 0.25 to
    # keep the derived default (4.84s) a legal enqueued point rather than moving the default.
    "max_plateau_seconds":       ("float", 0.25, 50.0, True),
    # Fractional exponent of "reheat to this factor of plateau start". NEW to any search -- held
    # fixed at 0.2 in every previous run.
    "plateau_reheat_exponent":   ("float", 0.001, 0.9, True),
    # Bayes_magnet itself lives in (0.9, 0.9999); searched as 1 - Bayes_magnet for resolution, the
    # same treatment one_minus_K got previously. Trajectory study measured stage-1 magnetism as
    # the one negative signal in the whole rework (+12.25 units, 2.4 sigma, unresolved) -- this is
    # the first time it has been searched rather than left at its hand-chosen default.
    "one_minus_bayes_magnet":    ("float", 1e-4, 0.1,  True),
}

# Held constant. Per the author: these are either inactive under the current scoring (reaction_factor,
# statistic_reaction_factor -- the weight EMA now reads weight_time_constant, not a per-segment
# ratio) or measured much lower-impact than the six above (initial_temp_factor,
# empty_route_cleanup_interval, explore_reward, cost_exponent).
FIXED = {
    "initial_temp_factor": 1e-4,
    "explore_reward": 1e-5,
}

# Must track SimAnnVRPSolver.__init__'s defaults for these six parameters -- these are the
# reference the search normalizes against, so a stale value silently shifts every score. Every
# value here must fall inside its own SEARCH_SPACE bound; the preflight check in main() asserts
# this before spending any budget.
DEFAULTS = {
    "segment_length": 100,
    "cooling_rate_per_second": 4.47,
    "weight_time_constant": 0.019,
    "max_plateau_seconds": 4.84,
    "plateau_reheat_exponent": 0.2,
    "one_minus_bayes_magnet": 0.003,          # 1 - 0.997
}


def build_instance(num_customers: int, vehicles: int = 3) -> FullSolution:
    """Deterministic instance for a given size, so every configuration sees the same problem."""
    np.random.seed(42)
    depots = [Depot(i, loc, 35, 1) for i, loc in enumerate([(10, 10), (50, 50), (90, 10)])]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(num_customers)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(vehicles):
        sln.add_vehicle(Vehicle(initial_depot=depots[i % len(depots)], i=i, capacity=CAPACITY))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def solver_kwargs(params: dict) -> dict:
    params = {**FIXED, **params}
    return {
        "segment_length": max(1, int(params["segment_length"])),
        "time_based_schedule": True,
        "cooling_rate_per_second": params["cooling_rate_per_second"],
        "max_plateau_seconds": params["max_plateau_seconds"],
        "plateau_reheat_exponent": params["plateau_reheat_exponent"],
        "weight_time_constant": params["weight_time_constant"],
        "Bayes_magnet": 1.0 - params["one_minus_bayes_magnet"],
        "initial_temp_factor": params["initial_temp_factor"],
        "explore_reward": params["explore_reward"],
    }


# A configuration that raises scores inf, which is correct -- but a rename in the solver makes
# EVERY configuration raise, and the search then spends its whole budget comparing inf to inf.
# That has already happened once (plateau_reheat_factor -> plateau_reheat_exponent), so failures
# are counted and surfaced rather than silently folded into the score.
FAILURES: dict[str, int] = {}


def run_once(params: dict, num_customers: int, seed: int, seconds: float) -> float:
    """One full solve. Returns the best objective found, or inf if the configuration blew up."""
    CM.seed_solver_rng(seed)
    sln = build_instance(num_customers)
    try:
        solver = SimAnnVRPSolver(sln, max_time=seconds, **solver_kwargs(params))
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
            solver.solve(debug_level=0)
        best = solver.best_objective
    except Exception as exc:
        key = f"{type(exc).__name__}: {exc}"
        FAILURES[key] = FAILURES.get(key, 0) + 1
        return float("inf")
    return best if best == best and best != float("inf") else float("inf")


def score(params: dict, sizes, runs_per_size: int, seconds: float, reference: dict) -> float:
    """Mean over sizes of (mean objective at that size) / (reference objective at that size)."""
    ratios = []
    for size in sizes:
        results = [run_once(params, size, seed, seconds) for seed in range(runs_per_size)]
        finite = [r for r in results if r != float("inf")]
        if not finite:
            return float("inf")
        ratios.append(statistics.fmean(finite) / reference[size])
    return statistics.fmean(ratios)


def main() -> None:
    global CAPACITY

    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=28_800)
    ap.add_argument("--sizes", type=int, nargs="+", default=[500])
    ap.add_argument("--capacity", type=int, default=CAPACITY)
    # 5 runs/size x 1 size x 120s = 10 min/trial -> 6 trials/hour -> ~48 trials in 8h.
    ap.add_argument("--runs-per-size", type=int, default=5)
    ap.add_argument("--seconds-per-run", type=float, default=120.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "tune_results.json"))
    args = ap.parse_args()

    CAPACITY = args.capacity

    # Preflight: every DEFAULTS value must be a legal point in its own SEARCH_SPACE bound, or
    # trial 0 (the enqueued status quo) is out of range and Optuna either clips or raises before
    # anything useful runs.
    for name, value in DEFAULTS.items():
        kind, low, high, _log = SEARCH_SPACE[name]
        assert low <= value <= high, (
            f"DEFAULTS[{name!r}] = {value} is outside its own SEARCH_SPACE bound [{low}, {high}]")
    assert set(DEFAULTS) == set(SEARCH_SPACE), (
        f"DEFAULTS and SEARCH_SPACE must name the same parameters. "
        f"DEFAULTS only: {set(DEFAULTS) - set(SEARCH_SPACE)}; "
        f"SEARCH_SPACE only: {set(SEARCH_SPACE) - set(DEFAULTS)}")

    started = time.perf_counter()
    print(f"tuning {sorted(SEARCH_SPACE)} over sizes {args.sizes} at capacity {CAPACITY}; "
          f"{args.runs_per_size} runs/size x {args.seconds_per_run}s; "
          f"budget {args.budget_seconds:.0f}s", flush=True)

    # Preflight: the derived kwargs must actually construct a solver before spending the budget.
    try:
        probe_sln = build_instance(args.sizes[0])
        SimAnnVRPSolver(probe_sln, max_time=1.0, **solver_kwargs(DEFAULTS))
        print(f"  defaults construct cleanly: {solver_kwargs(DEFAULTS)}", flush=True)
    except Exception as exc:
        print(f"\nABORT: DEFAULTS/solver_kwargs cannot construct a solver: "
              f"{type(exc).__name__}: {exc}")
        sys.exit(1)

    # Reference = current defaults, measured the same way, used to normalize each size.
    reference = {}
    for size in args.sizes:
        runs = [run_once(DEFAULTS, size, seed, args.seconds_per_run)
                for seed in range(args.runs_per_size)]
        reference[size] = statistics.fmean(runs)
        print(f"  reference (defaults) size={size}: {reference[size]:.2f}", flush=True)

    # Fail fast. If the defaults cannot even run, every trial scores inf and the whole budget is
    # spent producing nothing -- check before committing hours to it.
    if any(r == float("inf") or r != r for r in reference.values()):
        print("\nABORT: the default configuration did not produce a finite objective.")
        for message, count in FAILURES.items():
            print(f"  {count:4d}x  {message}")
        if not FAILURES:
            print("  (no exceptions raised -- best_objective was inf or nan)")
        print("\nDEFAULTS/solver_kwargs are probably out of step with SimAnnVRPSolver.__init__.")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=12345))
    study.enqueue_trial(DEFAULTS)          # evaluate the status quo as trial 0

    state = {
        "_solver": solver_stamp(),
        "config": {"sizes": args.sizes, "runs_per_size": args.runs_per_size,
                   "seconds_per_run": args.seconds_per_run,
                   "budget_seconds": args.budget_seconds, "capacity": CAPACITY},
        "reference": {str(k): v for k, v in reference.items()},
        "defaults": DEFAULTS,
        "fixed": FIXED,
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
        value = score(params, args.sizes, args.runs_per_size, args.seconds_per_run, reference)
        state["trials"].append({"number": trial.number, "params": params, "value": value})
        with open(args.out, "w") as handle:
            json.dump(state, handle, indent=2, default=float)
        elapsed = time.perf_counter() - started
        if trial.number % 10 == 0 or value < 0.99:
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
    print(f"best score {study.best_value:.4f}  (1.0 == current defaults)")
    for name, value in study.best_params.items():
        print(f"    {name:24} {value!r:>14}   (default {DEFAULTS[name]!r})")
    print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
