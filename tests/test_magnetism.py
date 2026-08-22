"""
Tests for sibling-local weight magnetism.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

The pinned-selection idea is Benjamin's: replace the solver's selection with a fixed sequence, so a
scoring change cannot move the trajectory through selection. That turns "the suite still passes"
into a statement about where an effect can and cannot travel.
"""
import contextlib
import io
import math
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (SeededTestCase, deterministic_clock, fixed_operator_sequence,
                      random_instance)
from SimAnn_VRP_Solver import SimAnnVRPSolver, _fold, _lift_unproposed
from SimAnn_VRP_Operators import Family

REVERSAL = (Family.INTRA_ROUTE, Family.REVERSAL)


class Magnetism(SeededTestCase):

    def _solve(self, magnet: float, iterations: int = 6000) -> float:
        sln = random_instance(seed=4242, n_customers=30, n_vehicles=4)
        solver = SimAnnVRPSolver(sln, Bayes_magnet=magnet)
        solver.max_time = 30.0
        solver.set_deterministic_weighting()
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
            with fixed_operator_sequence(solver), deterministic_clock(solver, iterations):
                solver.solve(debug_level=0)
        return round(solver.best_objective, 9)

    def test_the_magnet_acts_only_through_selection(self):
        """
        With the operator sequence pinned, Bayes_magnet must not change the outcome AT ALL.

        The magnet moves weights, and weights exist to steer selection. If pinning selection still
        leaves an objective difference, something outside selection is reading those weights, which
        would be a defect rather than a tuning question.
        """
        self.assertEqual(self._solve(0.997), self._solve(0.90))

    def test_the_pinned_sequence_is_actually_pinned(self):
        """The harness above proves nothing unless it really fixes the sequence."""
        sln = random_instance(seed=4242, n_customers=30, n_vehicles=4)
        solver = SimAnnVRPSolver(sln)
        with fixed_operator_sequence(solver):
            first = [type(solver.choose_operator()).__name__ for _ in range(200)]
        with fixed_operator_sequence(solver):
            second = [type(solver.choose_operator()).__name__ for _ in range(200)]
        self.assertEqual(first, second)
        self.assertGreater(len(set(first)), 1, "a pinned sequence must still be varied")

    def test_a_starved_subfamily_is_pulled_toward_its_SIBLINGS(self):
        """
        REVERSAL starved inside a proposed INTRA_ROUTE converges to the intra level, not the roster.

        This is the whole point of the change. Under a flat roster mean it would climb toward the
        other root families instead, which do a different job entirely.
        """
        sln = random_instance(seed=1, n_customers=60, n_vehicles=8)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()

        def pin():
            for op in solver.operators:
                if op.family[:2] == REVERSAL:
                    continue
                op.weight = 1.0 if op.family[0] is Family.INTRA_ROUTE else 1000.0
                solver.adj_weights[op] = op.weight
                solver.leaf_of[op].proposed = True

        for op in solver.operators:
            if op.family[:2] == REVERSAL:
                op.weight = 0.01
                solver.adj_weights[op] = 0.01
                solver.leaf_of[op].proposed = False
        pin()

        # Mirrors update_weights: fold, lift, then write the lifted weights back into adj_weights
        # before the next fold. Without the write-back the lift compounds instead of converging,
        # because _fold reloads every leaf from adj_weights.
        for _ in range(4000):
            for child in solver.family_root.children:
                _fold(child, solver.adj_weights)
            _lift_unproposed(solver.family_root, solver.Bayes_magnet)
            for op in solver.operators:
                solver.adj_weights[op] = op.weight * op.exploit_selection_penalty_factor
            pin()

        final = [op.weight for op in solver.operators if op.family[:2] == REVERSAL]
        for w in final:
            self.assertAlmostEqual(w, 1.0, delta=0.05,
                                   msg="starved family should converge to its SIBLING level")
            self.assertLess(w, 10.0, "it must not be pulled toward the roster level of 1000")

    def test_an_unproposed_family_is_lifted_at_the_root(self):
        """The complementary case: a whole family with no proposals rises toward its sibling families."""
        sln = random_instance(seed=1, n_customers=60, n_vehicles=8)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        for op in solver.operators:
            intra = op.family[0] is Family.INTRA_ROUTE
            op.weight = 0.01 if intra else 1000.0
            solver.adj_weights[op] = op.weight
            solver.leaf_of[op].proposed = not intra

        for child in solver.family_root.children:
            _fold(child, solver.adj_weights)
        before = max(op.weight for op in solver.operators
                     if op.family[0] is Family.INTRA_ROUTE)
        _lift_unproposed(solver.family_root, solver.Bayes_magnet)
        after = max(op.weight for op in solver.operators
                    if op.family[0] is Family.INTRA_ROUTE)
        self.assertGreater(after, before, "an unproposed family must be lifted at the root")


if __name__ == "__main__":
    unittest.main()
