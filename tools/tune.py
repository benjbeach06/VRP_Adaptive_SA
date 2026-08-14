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

  * plateau_reheat_exponent is NEW and has never been searched, so it holds most of the headroom
    here. It is also the parameter this setup is least able to fit: it exists to sustain
    exploration across a long run, and a 60s tuning run rewards reaching a decent solution
    quickly. Validate the winner at 4x length on unseen seeds before adopting it -- as was done
    for the 2026-08-11 results.

METHOD -- and why it is shaped this way:

  * Production settings, deliberately. Runs use wall-clock termination and the normal
    timing-based operator weighting, i.e. the solver exactly as shipped. Fixing the iteration
    count and forcing deterministic weighting would give a much quieter objective, but it would
    be tuning a solver nobody runs.

  * Noise is handled by AVERAGING, not by removing it. Each configuration is scored over
    RUNS_PER_SIZE short runs at each instance size rather than one long run. Short-and-many beats
    long-and-few here because the run-to-run spread is large (measured at roughly +-30% on
    iteration rate), so the variance of the mean is what matters.

  * Scores are normalised per instance size against a reference configuration (the current
    defaults), because raw objectives differ by an order of magnitude between 60 and 200
    customers and would otherwise let the largest size dominate the mean.

  * The weighting parameters (segment_length, reaction_factor, and the hard-coded 0.997 and 1.5
    exponents) are deliberately NOT searched. See TODO(rescore) in SimAnn_VRP_Operators.py: the
    statistics they consume are known to be measuring the wrong thing until the proposal/accept
    timing split lands, so any value fitted now would be fitted to broken measurements. Add them
    to SEARCH_SPACE once that is fixed.

  * cooling_factor is per-ITERATION, so its best value depends on how many iterations fit in the
    budget. Results therefore transfer only to runs of a similar length; a longer run wants
    slower cooling. Reparameterising it as a fraction of the expected budget would fix that and
    SHOULD BE DONE BEFORE THE NEXT SEARCH -- the 704-trial run of 2026-08-11 was invalidated by
    exactly this. It ran at 0.5s per solve, where the temperature collapsed within ~1000
    iterations, so it tuned an annealing schedule that was already degenerate. Use
    --seconds-per-run at the length you actually care about.

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


# Each entry: name -> (optuna suggest kind, low, high, log?). Extend this to widen the search;
# nothing else needs to change.
SEARCH_SPACE = {
    # Searched as (1 - cooling_factor) so the interesting region near 1.0 gets resolution.
    # Range recentred after the temperature-collapse fix. The old upper end (1e-1) cooled so fast
    # that the anneal was degenerate within ~1000 iterations, so the previous search optimised the
    # wrong thing. cooling_rate is per-ITERATION, so a long run needs a much smaller value.
    "cooling_rate":            ("float", 1e-6, 3e-3, True),
    # Now sets how OFTEN the temperature is pulled back to objective scale, so it matters more
    # under the new reheat than it did under the old one.
    "max_plateau_size":        ("int",   500, 50_000, True),
    # Reheat closes (1 - p) of the log-space gap between temperature and log2(objective).
    # p -> 0 is a full reset to objective scale; p -> 1 is no reheat at all. Must stay in (0, 1):
    # p >= 1 moves the temperature away from the objective and does not converge.
    "plateau_reheat_exponent": ("float", 0.02, 0.9, False),
}

# Held constant, deliberately NOT searched. initial_temp_factor only governs the opening
# transient -- the first plateau reheat overwrites the temperature outright -- so searching it
# lets the starting regime drift underneath the three parameters actually being measured, and
# spends trials resolving an effect that decays. 1e-4 is chosen as a balanced middle: low enough
# that exploitation begins inside a 60s budget, high enough that some exploration happens first.
# Both behaviours stay reachable, which is what exposes the other parameters' effects instead of
# masking them. Applies to the reference configuration too, so normalisation sees the same regime.
FIXED = {
    "initial_temp_factor": 1e-4,
}

# Must track SimAnnVRPSolver.__init__'s defaults: these are the reference the search normalises
# against, so a stale value silently shifts every score.
DEFAULTS = {
    "cooling_rate": 1e-4,
    "max_plateau_size": 2_000,
    "plateau_reheat_exponent": 0.2,
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
        sln.add_vehicle(Vehicle(initial_depot=depots[i % len(depots)], i=i, capacity=25))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def solver_kwargs(params: dict) -> dict:
    params = {**FIXED, **params}
    return {
        "cooling_factor": 1.0 - params["cooling_rate"],
        "initial_temp_factor": params["initial_temp_factor"],
        "max_plateau_size": int(params["max_plateau_size"]),
        "plateau_reheat_exponent": params["plateau_reheat_exponent"],
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=28_800)
    ap.add_argument("--sizes", type=int, nargs="+", default=[60, 200])
    # 5 per size x 2 sizes = 10 runs per trial. The score is a mean of two size-means, so its
    # variance is sigma^2/10 -- the same noise reduction as 10 runs at one size, while keeping
    # both sizes in the normalisation. At 60s/run that is 10 min per trial, ~48 trials in 8h.
    ap.add_argument("--runs-per-size", type=int, default=5)
    ap.add_argument("--seconds-per-run", type=float, default=60.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "tune_results.json"))
    args = ap.parse_args()

    started = time.perf_counter()
    print(f"tuning {len(SEARCH_SPACE)} parameters over sizes {args.sizes}; "
          f"{args.runs_per_size} runs/size x {args.seconds_per_run}s; "
          f"budget {args.budget_seconds:.0f}s", flush=True)

    # Reference = current defaults, measured the same way, used to normalise each size.
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
        "config": {"sizes": args.sizes, "runs_per_size": args.runs_per_size,
                   "seconds_per_run": args.seconds_per_run,
                   "budget_seconds": args.budget_seconds},
        "reference": {str(k): v for k, v in reference.items()},
        "defaults": DEFAULTS,
        "fixed": FIXED,
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
