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
    FULL_MATRIX, SeededTestCase, all_problems, debug_findings, random_instance, run_solver,
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
        measured. A fixed budget makes the walk a pure function of the seed.
        """
        for seed, n_customers, n_vehicles in [(5, 40, 5), (11, 40, 5)]:
            with self.subTest(seed=seed):
                self._assert_clean_solve(seed, n_customers, n_vehicles, iterations=20000)


class SolverDeterminism(SeededTestCase):
    def test_same_seed_and_iteration_budget_reproduce_exactly(self):
        """Reproducibility is what makes a regression bisectable; assert it rather than hope."""
        results = []
        for _ in range(2):
            sln = random_instance(seed=4242, n_customers=30, n_vehicles=4)
            solver, _ = run_solver(sln, max_time=SOLVE_SECONDS, debug_level=0, iterations=8000)
            results.append((round(solver.best_objective, 9), round(sln.solution_cost(), 9)))

        self.assertEqual(results[0], results[1],
                         "identical seed and iteration budget produced different results")


if __name__ == "__main__":
    unittest.main()
