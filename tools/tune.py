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

  * Scores are normalized per instance size against a reference configuration (the current
    defaults), because raw objectives differ by an order of magnitude between 60 and 200
    customers and would otherwise let the largest size dominate the mean.

  * The SELECTION parameters are what this searches now. They were previously excluded because
    the statistics they consume ignored two things a score should account for -- how often an
    operator's moves are accepted, and what its exploration costs. explore_reward fixed that:
    score = max(explore_reward, improvement**1.5) / mean_cost floors the IMPROVEMENT term, so an
    accepted uphill move is worth explore_reward / mean_cost. Acceptance rate enters because
    score_sum accumulates per accept; cost enters through the division. The rest of TODO(rescore)
    -- splitting proposal timing from accept timing -- is still open, so treat these as fitted to
    an improved but not finished measurement.

  * K AND L ARE MADE INDEPENDENT, which is the whole point of the parameterisation. L
    (segment_length) is purely a SAMPLING RATE: how often weights are recomputed. On its own,
    changing L would silently change two other things, so both are normalised away:
      - the weight EMA compounds (1 - reaction_factor) once per SEGMENT, so the per-ITERATION
        retention K = (1 - p)**(1/L) is what must stay fixed. Hence p = 1 - K**L.
      - curr_plateau_size counts SEGMENTS, so max_plateau_size = PLATEAU_ITERATIONS / L keeps
        improvement-free iterations-to-reheat constant.
    With both, L=100 reproduces the shipped solver exactly and L means only "bucket size".
    Cooling needs no such treatment -- log_temperature is advanced once per ITERATION, above the
    segment check, so the annealing schedule is already independent of L.

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
from run_stamp import solver_stamp          # noqa: E402


# Each entry: name -> (optuna suggest kind, low, high, log?). Extend this to widen the search;
# nothing else needs to change.
# Improvement-free ITERATIONS before a plateau reheat, held constant so segment_length does not
# change reheat frequency. 2e5 is the shipped behaviour: segment_length 100 x max_plateau_size
# 2000. Raising it makes reheat unreachable in a short run -- at n=500 a 30s solve is roughly
# 950k iterations, so 2e6 would mean no trial ever reheats.
PLATEAU_ITERATIONS = 2e5

# Vehicle capacity for the tuning instance. 400 gives few long routes, which is the regime the
# operator roster was last measured in; 25 gives many short ones and is a different problem.
CAPACITY = 400

# Per-ITERATION weight retention equivalent to the shipped (segment_length=100,
# reaction_factor=0.01). Derived, not typed, so it cannot drift from those two.
DEFAULT_ONE_MINUS_K = 1.0 - (1.0 - 0.01) ** (1.0 / 100)

SEARCH_SPACE = {
    # K is the per-ITERATION retention multiplier of the weight EMA; 1-K is searched because K
    # itself lives in [0.997, 0.999999] across the useful range and has no resolution on a log
    # scale. reaction_factor is DERIVED as 1 - K**segment_length, so this knob means the same
    # thing at every segment_length. Bounds map to reaction_factor 1e-4 .. 0.25 at L=100.
    "one_minus_K":     ("float", 1e-6, 3e-3, True),
    # Pure sampling rate: how many iterations between weight recomputes. Both of its side effects
    # are normalised away (see the module docstring), so this measures bucketing alone.
    "segment_length":  ("int",   1, 1000, True),
    # Floor on the improvement term of an accepted move's score, so an accepted UPHILL move is
    # worth explore_reward / mean_cost instead of nothing. Spans nine orders of magnitude down
    # from the default because the useful scale is genuinely unknown -- it competes against
    # whatever weights operators settle at, which moves with temperature through a run.
    "explore_reward":  ("float", 1e-9, 1e-3, True),
}

# Held constant. The annealing schedule was searched over 704 trials on 2026-08-11 and the
# landscape was flat (3.6% best-to-worst); hand defaults then beat all 47 validation trials and
# won a paired 240s comparison. Re-searching it here would spend trials re-deriving that while
# diluting the three parameters actually under test.
FIXED = {
    "initial_temp_factor": 1e-4,
    "cooling_rate": 1e-4,
    "plateau_reheat_exponent": 0.2,
}

# Must track SimAnnVRPSolver.__init__'s defaults: these are the reference the search normalizes
# against, so a stale value silently shifts every score.
DEFAULTS = {
    "one_minus_K": DEFAULT_ONE_MINUS_K,
    "segment_length": 100,
    "explore_reward": 1e-5,
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
    segment_length = max(1, int(params["segment_length"]))
    retention = 1.0 - params["one_minus_K"]

    return {
        "cooling_factor": 1.0 - params["cooling_rate"],
        "initial_temp_factor": params["initial_temp_factor"],
        "plateau_reheat_exponent": params["plateau_reheat_exponent"],
        "segment_length": segment_length,
        # Both derived from segment_length so that it stays a pure sampling rate. See the module
        # docstring; at segment_length=100 these reproduce reaction_factor=0.01 and
        # max_plateau_size=2000, i.e. the shipped solver exactly.
        "reaction_factor": 1.0 - retention ** segment_length,
        "max_plateau_size": max(1, int(PLATEAU_ITERATIONS / segment_length)),
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
    # Both are read by build_instance/solver_kwargs, which take no config argument. Declared here
    # so the CLI can override them; must precede the argparse defaults that read their values.
    global CAPACITY, PLATEAU_ITERATIONS

    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=28_800)
    ap.add_argument("--sizes", type=int, nargs="+", default=[500])
    ap.add_argument("--capacity", type=int, default=CAPACITY)
    ap.add_argument("--plateau-iterations", type=float, default=PLATEAU_ITERATIONS,
                    help="Improvement-free iterations before a reheat, held constant across "
                         "segment_length. 2e5 is the shipped behaviour.")
    # 5 per size x 2 sizes = 10 runs per trial. The score is a mean of two size-means, so its
    # variance is sigma^2/10 -- the same noise reduction as 10 runs at one size, while keeping
    # both sizes in the normalization. At 60s/run that is 10 min per trial, ~48 trials in 8h.
    ap.add_argument("--runs-per-size", type=int, default=5)
    ap.add_argument("--seconds-per-run", type=float, default=60.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "tune_results.json"))
    args = ap.parse_args()

    CAPACITY = args.capacity
    PLATEAU_ITERATIONS = args.plateau_iterations

    started = time.perf_counter()
    print(f"tuning {sorted(SEARCH_SPACE)} over sizes {args.sizes} at capacity {CAPACITY}; "
          f"{args.runs_per_size} runs/size x {args.seconds_per_run}s; "
          f"plateau_iterations {PLATEAU_ITERATIONS:.0f}; "
          f"budget {args.budget_seconds:.0f}s", flush=True)
    # Prove the derivation reproduces the shipped solver at L=100 before spending the budget.
    check = solver_kwargs(DEFAULTS)
    print(f"  defaults derive: reaction_factor {check['reaction_factor']:.6f} (want 0.010000), "
          f"max_plateau_size {check['max_plateau_size']} (want 2000)", flush=True)

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
