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
    random_instance, run_solver, catch_mis_reported_noops,
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


class NoOpDetection(SeededTestCase):
    """
    A move worth nothing that also DOES nothing must not report VALID.

    Zero-delta moves are legitimate -- reversing a symmetric run costs nothing and still changes
    the solution. The defect is the other case: a move priced at zero that leaves the vehicles
    exactly as they were. That hands its operator weight it did not earn.

    The cost of getting this wrong is about to rise. Under family-level selection, one operator's
    undeserved weight lifts its whole family's geometric mean, so a silent no-op stops being local.
    See planning/family-level-selection.md.

    Deterministic weighting and a fixed iteration budget, so a finding is reproducible rather than
    a trajectory that happened once.
    """

    ITERATIONS = 4000

    def test_no_zero_delta_move_leaves_the_solution_unchanged(self):
        for seed, n_customers, n_vehicles in [(1, 20, 3), (5, 40, 5), (17, 30, 4)]:
            with self.subTest(seed=seed):
                sln = random_instance(seed, n_customers, n_vehicles)
                with catch_mis_reported_noops(sln) as findings:
                    run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0,
                               iterations=self.ITERATIONS, deterministic_weighting=True)
                counts: dict[str, int] = {}
                for name, kind in findings:
                    counts[f"{name} ({kind})"] = counts.get(f"{name} ({kind})", 0) + 1
                self.assertEqual(
                    counts, {},
                    "operators reported an actionable zero-delta move that changed nothing")

    def test_the_no_op_detector_actually_fires(self):
        """
        A clean run means nothing until the detector is shown to fire.

        Inject the defect by RE-OPENING the hole the fix closed: force one operator to return the
        identity order, and make PermuteChain price an identity as VALID again. That is the exact
        shape of the bug this suite found, so passing here means the detector would catch its
        return.

        Crafting some other zero-delta case would test a different thing. The question is whether
        THIS defect stays caught.
        """
        import SimAnn_VRP_BLOperators as BL
        from SimAnn_VRP_Operators import ReorderShortSpanExactly

        original_reorder = ReorderShortSpanExactly._reorder
        original_evaluate = BL.PermuteChain._evaluate_impl

        def leaky_evaluate(self, operands):
            result = original_evaluate(self, operands)
            _, _, permutation = operands
            is_identity = (len(permutation) > 1
                           and all(source == position
                                   for position, source in enumerate(permutation)))
            if result[1] == BL.MoveKind.NOOP and is_identity:
                # Pre-fix behaviour: price a no-op as a real move worth nothing.
                self._revert_info = self._apply_impl(operands)
                return BL.ObjectiveTermDelta(travel_distance=0.0), BL.MoveKind.VALID
            return result

        ReorderShortSpanExactly._reorder = lambda self, points, left, right: list(range(len(points)))
        BL.PermuteChain._evaluate_impl = leaky_evaluate
        try:
            sln = random_instance(1, 20, 3)
            with catch_mis_reported_noops(sln) as findings:
                run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0,
                           iterations=self.ITERATIONS, deterministic_weighting=True)
        finally:
            ReorderShortSpanExactly._reorder = original_reorder
            BL.PermuteChain._evaluate_impl = original_evaluate

        self.assertTrue(
            findings,
            "detector missed a DELIBERATE no-op -- its clean runs prove nothing")
