"""
Tests for how an operator's weight becomes its selection share.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

Stage 2 of the scoring rework removed the hand-set `exploit_selection_penalty_factor`. These tests
state the invariant that now holds and used to be violated: **equal weight means equal share.**
"""
import collections
import contextlib
import io
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import SeededTestCase, random_instance
from SimAnn_VRP_Solver import SimAnnVRPSolver
from SimAnn_VRP_Operators import Family

FARTHEST = (Family.INTRA_ROUTE, Family.REORDER, Family.OPTIMIZED, Family.FARTHEST_INSERTION)


class SelectionDiscount(SeededTestCase):

    def _solver(self):
        sln = random_instance(seed=7, n_customers=200, n_vehicles=40, capacity=25)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        return solver

    def test_no_operator_carries_a_selection_discount(self):
        """
        Every penalty factor is 1.0, so an adjusted weight equals its raw weight.

        Before stage 2 this was false for three operators. The multiply is deliberately still in
        `update_weights`, so this asserts the VALUES are neutral rather than that the term is gone.
        """
        solver = self._solver()
        for op in solver.operators:
            self.assertEqual(op.exploit_selection_penalty_factor, 1.0,
                             f"{type(op).__name__} carries a hand-set discount")
        for op in solver.operators:
            op.weight = 3.25
        solver.refresh_family_tree()
        for op in solver.operators:
            solver.adj_weights[op] = op.weight * op.exploit_selection_penalty_factor
            self.assertEqual(solver.adj_weights[op], op.weight)

    def test_the_farthest_insertion_variants_now_draw_equally(self):
        """
        Equal weight, equal share -- the three variants used to differ by 16x.

        The old factors were `1/conservative_vehicle_customers` for the base, times 4 for the span
        variant and divided by 4 for the long-route variant. So span against long-route was 16:1 in
        selection rate at identical weight, decided by a hand-set constant rather than by anything
        the solver measured.
        """
        solver = self._solver()
        # Derive adj_weights THROUGH the penalty, exactly as update_weights does. Setting
        # adj_weights directly would bypass the term this test is about, and the test would then
        # pass on the pre-stage-2 code too.
        for op in solver.operators:
            op.weight = 1.0
            solver.adj_weights[op] = op.weight * op.exploit_selection_penalty_factor
        solver.refresh_family_tree()

        variants = [type(op).__name__ for op in solver.operators if op.family == FARTHEST]
        self.assertEqual(len(variants), 3, "expected three farthest-insertion variants")

        draws = 300_000
        counts = collections.Counter(type(solver.choose_operator()).__name__
                                     for _ in range(draws))
        shares = [counts[name] / draws for name in variants]

        # All three sit under one parent, so equal weights must give equal shares. Binomial
        # standard error at this share is about 8e-5; 4 sigma is a wide, stable bound.
        widest = max(shares) - min(shares)
        self.assertLess(widest, 0.0015,
                        f"variants no longer draw equally: {dict(zip(variants, shares))}")
        self.assertGreater(min(shares), 0.0,
                           "every variant must still be reachable")


if __name__ == "__main__":
    unittest.main()
