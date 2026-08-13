"""
Hyperparameter search over SimAnnVRPSolver's "magic numbers", using Optuna (TPE).

    python tools/tune.py --budget-seconds 3600

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
    is worth doing before trusting these numbers at a very different max_time.

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
    "cooling_rate":          ("float", 1e-5, 1e-1, True),
    "initial_temp_factor":   ("float", 2e-3, 5e-1, True),
    "low_temp_factor":       ("float", 1e-60, 1e-5, True),
    "max_plateau_size":      ("int",   500, 50_000, True),
    "plateau_reheat_factor": ("float", 1.05, 8.0, False),
}

DEFAULTS = {
    "cooling_rate": 1e-2,
    "initial_temp_factor": 0.05,
    "low_temp_factor": 1e-40,
    "max_plateau_size": 10_000,
    "plateau_reheat_factor": 2.0,
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
    return {
        "cooling_factor": 1.0 - params["cooling_rate"],
        "initial_temp_factor": params["initial_temp_factor"],
        "low_temp_factor": params["low_temp_factor"],
        "max_plateau_size": int(params["max_plateau_size"]),
        "plateau_reheat_factor": params["plateau_reheat_factor"],
    }


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
    except Exception:
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
    ap.add_argument("--budget-seconds", type=float, default=3600)
    ap.add_argument("--sizes", type=int, nargs="+", default=[60, 200])
    ap.add_argument("--runs-per-size", type=int, default=5)
    ap.add_argument("--seconds-per-run", type=float, default=0.5)
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
    with open(args.out, "w") as handle:
        json.dump(state, handle, indent=2, default=float)

    print(f"\ncompleted {len(study.trials)} trials in {time.perf_counter() - started:.0f}s")
    print(f"best score {study.best_value:.4f}  (1.0 == current defaults)")
    for name, value in study.best_params.items():
        print(f"    {name:24} {value!r:>14}   (default {DEFAULTS[name]!r})")
    print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
