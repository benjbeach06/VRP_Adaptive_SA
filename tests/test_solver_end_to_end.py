"""
End-to-end solver runs with full self-verification enabled.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

These drive complete solves at debug_level=3, which makes the solver verify itself as it runs:
every accepted move's reported improvement is checked against a fresh solution_cost(), every
REJECTED move is force-applied, checked, reverted and re-checked, and structural invariants are
asserted throughout. The rejected-move round-trip is the important half -- revert-only defects
never manifest on the accepted path, so nothing else sees them.

Two failure signals are asserted independently:
  * the solver's own findings (it should print none), and
  * drift between the incrementally-maintained curr_objective and a from-scratch solution_cost().
Drift can accumulate from a source the per-move checks miss, so it is checked separately rather
than assumed to follow.

Design input from the repository author: routing all randomness through one explicit generator
(np.random.default_rng) instead of the global `random` module. That change is what makes the
determinism test below pass -- identical seeds previously diverged across runs.
"""

import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (
    FULL_MATRIX, DirectOperator, SeededTestCase, all_problems, debug_findings, fingerprint,
    random_instance, run_solver,
)

# Wall-clock budget per solve. Kept small so the suite stays usable; the solver runs tens of
# thousands of iterations per second, so even a short budget exercises a long random walk.
SOLVE_SECONDS = 1.5 if FULL_MATRIX else 0.6

SMALL_CASES = [(1, 20, 3), (7, 20, 3), (42, 20, 3), (999, 20, 3)]
LARGE_CASES = [(5, 40, 5), (11, 60, 6), (77, 80, 8)]


class SolverSelfVerification(SeededTestCase):
    def _assert_clean_solve(self, seed, n_customers, n_vehicles, iterations=None):
        sln = random_instance(seed, n_customers, n_vehicles)
        solver, output = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=3,
                                    iterations=iterations)

        findings = debug_findings(output)
        self.assertEqual(
            findings[:5], [],
            f"seed={seed} n={n_customers}/{n_vehicles}: solver reported "
            f"{len(findings)} self-verification failures")

        drift = abs(solver.curr_objective - sln.solution_cost())
        self.assertLess(
            drift, 1e-6,
            f"seed={seed}: incremental objective drifted from recomputed cost by {drift}")

        self.assertEqual(all_problems(sln), [],
                         f"seed={seed}: solution violates its invariants after the solve")
        self.assertGreater(len(sln.all_routes), 0)

    def test_small_instances(self):
        for seed, n_customers, n_vehicles in SMALL_CASES:
            with self.subTest(seed=seed, customers=n_customers, vehicles=n_vehicles):
                self._assert_clean_solve(seed, n_customers, n_vehicles)

    def test_larger_instances(self):
        for seed, n_customers, n_vehicles in LARGE_CASES:
            with self.subTest(seed=seed, customers=n_customers, vehicles=n_vehicles):
                self._assert_clean_solve(seed, n_customers, n_vehicles)

    def test_fixed_iteration_budget(self):
        """
        Same checks, but terminating on an iteration count rather than the wall clock.

        Wall-clock termination makes a run depend on machine speed and on any instrumentation
        added while debugging, so a bug reproducible in a clean run can vanish the moment it is
        measured. A fixed budget removes that particular source of drift. (It is not sufficient
        on its own for full reproducibility -- see SolverDeterminism below.)
        """
        for seed, n_customers, n_vehicles in [(5, 40, 5), (11, 40, 5)]:
            with self.subTest(seed=seed):
                self._assert_clean_solve(seed, n_customers, n_vehicles, iterations=20000)


class SnapshotNormalisation(SeededTestCase):
    """
    Snapshots are the artifact callers inspect, so take_sln_snapshot normalizes before storing:
    every empty route disposed, and every remaining route assigned to a vehicle. Readers can rely
    on that without filtering.

    The disposal is undone immediately afterwards, so the LIVE solution must be untouched -- which
    is what keeps snapshotting safe with a move in flight. Disposing for real would invalidate
    operands (ReassignCustomerAt and ReassignRouteBefore both accept an empty dest_route) and move
    sln.version out from under the pending Move.
    """

    def test_snapshots_contain_no_empty_or_unassigned_routes(self):
        for seed, n_customers, n_vehicles in [(1, 20, 3), (5, 40, 5), (999, 20, 3)]:
            with self.subTest(seed=seed):
                sln = random_instance(seed, n_customers, n_vehicles)
                solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=3)

                self.assertGreater(len(solver.snapshots), 0, "solve produced no snapshots to check")
                for objective, snapshot in solver.snapshots:
                    empty = [r for r in snapshot.all_routes if r.is_empty]
                    unassigned = [r for r in snapshot.all_routes if not r.is_assigned]
                    self.assertEqual(empty, [], "snapshot retained empty routes")
                    self.assertEqual(unassigned, [], "snapshot retained unassigned routes")
                    self.assertAlmostEqual(objective, snapshot.solution_cost(), places=6,
                                           msg="snapshot's recorded objective disagrees with it")

    def test_snapshotting_leaves_the_live_solution_untouched(self):
        """The normalization must be visible only in the stored copy, never in the live solve."""
        sln = random_instance(4242, 30, 4)
        solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=4000)

        before = fingerprint(sln)
        before_objective = solver.curr_objective
        solver.take_sln_snapshot()

        self.assertEqual(fingerprint(sln), before,
                         "take_sln_snapshot mutated the live solution")
        self.assertEqual(solver.curr_objective, before_objective,
                         "take_sln_snapshot changed the running objective")
        self.assertEqual(all_problems(sln), [])

    def test_version_round_trips_through_apply_revert(self):
        """
        revert() decrements sln.version rather than incrementing, so an apply -> revert -> apply
        round trip lands back on the move's eval_version. Without that, the snapshot path
        (revert -> snapshot -> re-apply) would trip apply()'s staleness guard every time.
        """
        from SimAnn_VRP_BLOperators import ChangeEndDepot

        sln = random_instance(7, 20, 3)
        solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=2000)

        route = next(r for r in sln.all_routes if not r.is_empty)
        new_depot = next(d for d in sln.depots if d is not route.end_depot)
        operator = DirectOperator(sln, ChangeEndDepot(sln))

        version_before = sln.version
        move = operator.evaluate((route, new_depot))
        self.assertTrue(move.is_actionable)
        self.assertEqual(move.eval_version, version_before)

        operator.apply(move)
        self.assertEqual(sln.version, version_before + 1)
        operator.revert(move)
        self.assertEqual(sln.version, version_before,
                         "revert did not return the version to the state it restored")

        # The same move must still be applicable: the state it was priced against is back.
        # apply() asserts eval_version == sln.version, so a wrong version here raises rather
        # than silently re-applying against a different state.
        operator.apply(move)
        self.assertTrue(move.already_applied)
        operator.revert(move)

    def test_revert_and_apply_gatekeep_themselves(self):
        """Callers drive the lifecycle with the move in hand; the operator decides whether to act."""
        from SimAnn_VRP_BLOperators import ChangeEndDepot

        sln = random_instance(11, 20, 3)
        solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=2000)

        route = next(r for r in sln.all_routes if not r.is_empty)
        new_depot = next(d for d in sln.depots if d is not route.end_depot)
        operator = DirectOperator(sln, ChangeEndDepot(sln))
        move = operator.evaluate((route, new_depot))

        # The gatekeeping still holds; it reports through move.already_applied rather than through
        # a return value, so the caller asks the MOVE what happened instead of the operator.
        operator.revert(move)
        self.assertFalse(move.already_applied, "reverting a never-applied move should be a no-op")

        operator.apply(move)
        self.assertTrue(move.already_applied)
        operator.apply(move)
        self.assertTrue(move.already_applied, "re-applying the applied move should be a no-op")

        operator.revert(move)
        self.assertFalse(move.already_applied)
        operator.revert(move)
        self.assertFalse(move.already_applied, "double revert should be a no-op")


class SolverDeterminism(SeededTestCase):
    def test_same_seed_reproduces_exactly_with_deterministic_weighting(self):
        """
        Reproducibility is what makes a regression bisectable; assert it rather than hope.

        Needs THREE things pinned, and the third is easy to miss: a fixed iteration budget
        (wall-clock termination depends on machine speed), a seeded generator, and
        set_deterministic_weighting(). Without the last one, adaptive weighting scores operators
        by improvement per unit of measured time, so the trajectory follows CPU speed and cache
        state -- identical seeds then diverge, which is exactly what a heavy preceding test does
        to this one. That timing term is deliberate and valuable in production; this switch is
        for tests and bisection only.
        """
        results = []
        for _ in range(2):
            sln = random_instance(seed=4242, n_customers=30, n_vehicles=4)
            solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=8000,
                                   deterministic_weighting=True)
            results.append((round(solver.best_objective, 9), round(sln.solution_cost(), 9)))

        self.assertEqual(results[0], results[1],
                         "identical seed and iteration budget produced different results")

    def test_timing_based_weighting_is_the_only_nondeterminism(self):
        """
        Guards the claim above: with deterministic weighting on, a run must be reproducible even
        after arbitrary other work has run in the same process (which perturbs CPU/cache state
        and therefore the measured per-operator costs).
        """
        def solve_once():
            sln = random_instance(seed=4242, n_customers=30, n_vehicles=4)
            solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=4000,
                                   deterministic_weighting=True)
            return round(solver.best_objective, 9)

        first = solve_once()
        # Deliberately burn CPU on an unrelated solve to shift timing conditions.
        burner = random_instance(99, 60, 6)
        run_solver(burner, max_time=SOLVE_SECONDS, debug_level=0)
        self.assertEqual(solve_once(), first,
                         "deterministic weighting did not survive unrelated work in-process")


if __name__ == "__main__":
    unittest.main()
