"""
Long-running correctness stress test, aimed squarely at delta computations.

PROVENANCE
----------
Written by Claude (Anthropic) during development assistance; not hand-written by the repository
author. The DESIGN is the author's, and both of their decisions materially strengthened it:

  * the check sequence below -- unconditional evaluate -> apply -> revert -> apply -> commit,
    verifying objective terms AND invariants after every transition, not just after the first
    apply. Claude's original checked at two points and would have missed an objective that
    drifted only on the second apply;
  * accepting EVERY actionable move rather than random-walking like a solve. A solve-like walk
    clusters near local optima and under-visits the degenerate states where delta bugs live.

This harness found a latent crash on the solver's snapshot path (revert -> snapshot -> re-apply
against a route that revert had rebuilt as a new object) and an unguarded 2-of-n sample that
raised whenever the route count collapsed below two.

    python tools/stress.py --budget-seconds 3600

WHAT IT CHECKS, per proposed move, against ground truth recomputed from scratch:

  1. PURITY          evaluate() must not change the solution (except for _evaluates_by_applying
                     operators, which mutate atomically and are handled separately).
  2. PER-TERM DELTA  move.deltas compared to a diff of two objective_terms() calls FIELD BY
                     FIELD -- not just the scalar improvement. "improvement off by 27.78" is a
                     search; "travel_distance wrong, other four exact" is a location. This is the
                     check this whole tool exists for.
  3. INVARIANTS      after apply: depot usage counters, the visit doubly-linked list, the vehicle
                     route chain, successor start-depot agreement, and cached route loads all
                     still agree with a fresh recomputation.
  4. EXACT REVERT    a structural + cost fingerprint (including all_routes ORDER) must return to
                     precisely its pre-move value. Revert-only defects never appear on the
                     accepted path, so nothing else can see them.

Between probes it random-walks the solution -- accepting improving moves and occasionally
worsening ones -- so checks run against states an actual solve would reach, not just freshly
built ones. Instance size, vehicle count and seed vary per episode.

Findings are written to the output JSON continuously, so killing the run keeps its results.
"""
import argparse, collections, contextlib, io, json, os, statistics, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # reuse the oracles rather than duplicate them

import numpy as np

import SimAnn_VRP_Core_Model as CM
from SimAnn_VRP_Core_Model import Customer, Depot, FullSolution, ObjectiveTermDelta, Vehicle
from SimAnn_VRP_Solver import SimAnnVRPSolver
from _harness import all_problems, fingerprint          # noqa: E402

TOLERANCE = 1e-6
TERMS = ObjectiveTermDelta._fields


def build_instance(num_customers: int, num_vehicles: int, seed: int) -> FullSolution:
    np.random.seed(seed)
    depots = [Depot(i, loc, 35, 1) for i, loc in enumerate([(10, 10), (50, 50), (90, 10)])]
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(num_customers)]
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i in range(num_vehicles):
        sln.add_vehicle(Vehicle(initial_depot=depots[i % len(depots)], i=i, capacity=25))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


def term_diff(before: ObjectiveTermDelta, after: ObjectiveTermDelta) -> dict:
    return {name: getattr(after, name) - getattr(before, name) for name in TERMS}


class Stress:
    def __init__(self, out_path: str):
        self.out_path = out_path
        self.counts = collections.Counter()
        self.by_operator = collections.Counter()
        self.by_operator_term = collections.Counter()
        self.examples = []
        self.probes = 0
        self.episodes = 0

    def record(self, kind: str, operator: str, detail: dict, term: str = "-") -> None:
        self.counts[kind] += 1
        self.by_operator[(kind, operator)] += 1
        if kind == "delta_mismatch":
            self.by_operator_term[(operator, term)] += 1
        if len(self.examples) < 300:
            self.examples.append({"kind": kind, "operator": operator, "term": term, **detail})

    def check_objective(self, sln: FullSolution, name: str, stage: str, context: dict,
                        expected_terms) -> None:
        """Compare the running objective_terms() against the value it's supposed to hold at this
        stage, field by field. Used after every apply/revert, not just the first."""
        actual = sln.objective_terms()
        if actual != expected_terms:
            self.record("objective_mismatch", name,
                        {**context, "stage": stage,
                         "expected": {t: float(getattr(expected_terms, t)) for t in TERMS},
                         "actual": {t: float(getattr(actual, t)) for t in TERMS}})

    def check_invariants(self, sln: FullSolution, name: str, stage: str, context: dict) -> None:
        problems = all_problems(sln)
        if problems:
            self.record("invariant_violation", name, {**context, "stage": stage,
                                                       "problems": problems[:4]})

    def probe(self, solver: SimAnnVRPSolver, sln: FullSolution, context: dict) -> None:
        """
        Unconditional evaluate -> apply -> revert -> apply -> commit, checking objective terms
        and structural invariants after EVERY step (not just after the first apply). apply() and
        revert() gatekeep themselves (a no-op if already in that state), so calling them
        unconditionally is exactly what the solver's own code does -- this is the same sequence
        the snapshot path runs (revert -> snapshot -> re-apply), plus one extra revert/apply pair
        for coverage on operators the solver only ever applies once.
        """
        operator = CM.rand_choice(solver.operators)
        name = type(operator).__name__

        pre_terms = sln.objective_terms()
        pre_print = fingerprint(sln)

        # 1. evaluate (via propose, which also does operand selection)
        move = operator.propose()
        if not move.is_actionable:
            operator.revert(move)
            return
        self.probes += 1

        # check: validity right after evaluate.
        if move.already_applied:
            # Escape-hatch operator: evaluate() already mutated during propose(), so pre_print
            # (taken before propose ran) is the only valid pre-move baseline -- fingerprinting
            # NOW would capture the post-mutation state and make a correct revert() look wrong.
            baseline_print = pre_print
        else:
            if sln.objective_terms() != pre_terms:
                self.record("purity_violation", name,
                            {**context, "note": "evaluate() mutated the solution"})
            # Operand SELECTION can legitimately reorder all_routes even for a pure operator
            # (choose_random_nonempty_route lifts empty routes out and back), so the baseline is
            # taken AFTER propose here -- otherwise that reordering is misattributed to revert.
            baseline_print = fingerprint(sln)

        # 2. apply (no-op if propose() already applied it)
        operator.apply(move)

        # check: objective (per-term, against ground truth) and validity after apply
        measured = term_diff(pre_terms, sln.objective_terms())
        for term in TERMS:
            predicted = getattr(move.deltas, term)
            actual = measured[term]
            if abs(predicted - actual) > TOLERANCE:
                self.record("delta_mismatch", name,
                            {**context, "predicted": float(predicted), "measured": float(actual),
                             "diff": float(predicted - actual),
                             "improvement": float(move.improvement)}, term=term)
        self.check_invariants(sln, name, "after_apply", context)
        applied_terms = sln.objective_terms()
        applied_print = fingerprint(sln)

        # 3. revert
        operator.revert(move)

        # check: objective and validity after revert -- must be back to the pre-move state
        self.check_objective(sln, name, "after_revert", context, pre_terms)
        self.check_invariants(sln, name, "after_revert", context)
        reverted_print = fingerprint(sln)
        if reverted_print != baseline_print:
            differing = [i for i, (a, b) in enumerate(zip(baseline_print, reverted_print))
                         if a != b]
            self.record("revert_not_exact", name,
                        {**context, "fingerprint_fields_differing": differing,
                         "cost_before": baseline_print[0], "cost_after": reverted_print[0]})
            return                                   # state is dirty; don't build on it

        # 4. apply again -- exactly what the solver's snapshot path does
        #    (revert -> take_sln_snapshot -> apply). An operator that cannot survive this crashes
        #    a real solve, so it is checked explicitly rather than left to chance.
        try:
            operator.apply(move)
        except Exception as error:
            self.record("reapply_after_revert_failed", name,
                        {**context, "error": f"{type(error).__name__}: {error}"})
            return

        # check: objective and validity after the second apply -- must match the first apply
        self.check_objective(sln, name, "after_reapply", context, applied_terms)
        self.check_invariants(sln, name, "after_reapply", context)
        if fingerprint(sln) != applied_print:
            self.record("reapply_state_differs", name, {**context})
            operator.revert(move)
            return

        # 5. commit, unconditionally. A solve-like 90%-improving walk spends nearly all its time
        # near local optima, which under-visits exactly the degenerate/rare structural states --
        # near-empty routes, single-customer routes, load sitting exactly at capacity -- where
        # delta bugs actually live (the shared-start-depot activation bug this tool caught was
        # invisible until routes were driven into that specific configuration). Always-accepting
        # makes this a true random walk that mixes across the whole reachable state space instead
        # of clustering near good solutions.
        operator.commit(move)
        solver.curr_objective -= move.improvement

    def episode(self, seed: int, num_customers: int, num_vehicles: int, probes: int) -> None:
        self.episodes += 1
        context = {"seed": seed, "customers": num_customers, "vehicles": num_vehicles}
        CM.seed_solver_rng(seed)
        sln = build_instance(num_customers, num_vehicles, seed)
        solver = SimAnnVRPSolver(sln, max_time=0.01)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        solver.curr_objective = sln.solution_cost()
        solver.best_objective = solver.curr_objective

        for step in range(probes):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.probe(solver, sln, {**context, "step": step})
            except Exception:
                self.record("exception", "-", {**context, "step": step,
                                               "traceback": traceback.format_exc()[-1200:]})
                return                                # this episode's state is unusable
            if step % 200 == 199:
                with contextlib.redirect_stdout(io.StringIO()):
                    solver._cleanup_empty_routes()

    def save(self) -> None:
        payload = {
            "probes": self.probes,
            "episodes": self.episodes,
            "counts": dict(self.counts),
            "by_operator": {f"{k[0]}|{k[1]}": v for k, v in self.by_operator.items()},
            "delta_mismatch_by_operator_term":
                {f"{k[0]}|{k[1]}": v for k, v in self.by_operator_term.items()},
            "examples": self.examples,
        }
        with open(self.out_path, "w") as handle:
            json.dump(payload, handle, indent=2, default=float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=3600)
    ap.add_argument("--probes-per-episode", type=int, default=600)
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "stress_results.json"))
    args = ap.parse_args()

    stress = Stress(args.out)
    started = time.perf_counter()
    seed = 0
    sizes = [12, 25, 40, 60, 90, 140, 200]
    vehicle_counts = [1, 2, 3, 5, 8]

    print(f"stress: budget {args.budget_seconds:.0f}s, {args.probes_per_episode} probes/episode (always-accept random walk)",
          flush=True)
    while time.perf_counter() - started < args.budget_seconds:
        seed += 1
        num_customers = sizes[seed % len(sizes)]
        num_vehicles = vehicle_counts[seed % len(vehicle_counts)]
        stress.episode(seed, num_customers, num_vehicles, args.probes_per_episode)
        if seed % 20 == 0:
            stress.save()
            elapsed = time.perf_counter() - started
            print(f"  {elapsed:6.0f}s  episodes {stress.episodes:5d}  probes {stress.probes:8d}  "
                  f"findings {sum(stress.counts.values()):5d}  {dict(stress.counts)}", flush=True)

    stress.save()
    elapsed = time.perf_counter() - started
    print(f"\n=== stress complete: {elapsed:.0f}s, {stress.episodes} episodes, "
          f"{stress.probes} probes ===")
    if not stress.counts:
        print("NO FINDINGS -- deltas, invariants and reverts all verified clean.")
    else:
        print("findings by kind:")
        for kind, n in stress.counts.most_common():
            print(f"    {kind:22} {n}")
        print("findings by operator:")
        for (kind, op), n in stress.by_operator.most_common(20):
            print(f"    {kind:22} {op:34} {n}")
        if stress.by_operator_term:
            print("delta mismatches by operator and TERM (this localises the bug):")
            for (op, term), n in stress.by_operator_term.most_common(20):
                print(f"    {op:34} {term:24} {n}")
    print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
