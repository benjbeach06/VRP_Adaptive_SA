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
from SimAnn_VRP_Solver import SimAnnVRPSolver, _fold_estimates, _lift_unproposed
from SimAnn_VRP_Operators import ESTIMATE_FLOOR, Family
from SimAnn_VRP_BLOperators import Move, MoveKind

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


class RateEstimates(SeededTestCase):
    """Stage 3: the shrunk rate estimates. Nothing reads them yet."""

    def _solver(self, **kw):
        sln = random_instance(seed=11, n_customers=200, n_vehicles=40, capacity=25)
        solver = SimAnnVRPSolver(sln, **kw)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        return solver

    def test_statistic_reaction_factor_defaults_to_the_operator_one(self):
        """-1 means \"track reaction_factor\", so the two are one knob until someone splits them."""
        self.assertEqual(self._solver().statistic_reaction_factor,
                         self._solver().reaction_factor)
        split = self._solver(statistic_reaction_factor=0.5)
        self.assertEqual(split.statistic_reaction_factor, 0.5)
        self.assertNotEqual(split.statistic_reaction_factor, split.reaction_factor)

    @unittest.skip("update_weights' improvement_estimate update is commented out, 2026-08-23 -- "
                   "nothing reads the estimate any more. design/operator_selection/dynamic_penalty.md")
    def test_the_estimate_moves_toward_the_measured_rate(self):
        """
        One segment of known stats moves the estimate by exactly alpha toward the observed rate.

        The denominator is PROPOSALS, not accepts. An operator that proposes 100 times and improves
        twice has an improvement rate of 0.02, however many of those proposals were accepted.
        """
        solver = self._solver(statistic_reaction_factor=0.5)
        target = solver.operators[0]
        for op in solver.operators:
            op.stats.proposals, op.stats.accepts, op.stats.improvements = 100, 40, 2
            op.stats.score_sum = 1.0
        before = target.improvement_estimate
        solver.update_weights()
        expected = 0.5 * before + 0.5 * 0.02
        self.assertAlmostEqual(target.improvement_estimate, expected, places=12)

    def test_estimates_never_fall_below_the_floor(self):
        """Zero improvements forever must not drive the estimate to zero."""
        solver = self._solver(statistic_reaction_factor=0.9)
        for _ in range(50):
            for op in solver.operators:
                op.stats.proposals, op.stats.accepts, op.stats.improvements = 100, 0, 0
                op.stats.score_sum = 0.0
            solver.update_weights()
        for op in solver.operators:
            self.assertGreaterEqual(op.improvement_estimate, ESTIMATE_FLOOR)

    def test_an_unproposed_estimate_is_magnetised_toward_siblings(self):
        """Same treatment as weight: shrink toward the family, not the roster."""
        solver = self._solver()
        intra = [op for op in solver.operators if op.family[0] is Family.INTRA_ROUTE]
        for op in solver.operators:
            here = op in intra
            op.improvement_estimate = 0.001 if here else 1.0
            solver.leaf_of[op].proposed = not here

        for child in solver.family_root.children:
            _fold_estimates(child)
        before = max(op.improvement_estimate for op in intra)
        _lift_unproposed(solver.family_root, solver.Bayes_magnet,
                         "estimate", "improvement_estimate")
        after = max(op.improvement_estimate for op in intra)
        self.assertGreater(after, before, "an unproposed subtree must be lifted")


if __name__ == "__main__":
    unittest.main()


class DynamicPenalty(SeededTestCase):
    """The penalty is a pure COST ratio against the roster's cheapest operator.

    Superseded 2026-08-23. It used to be improvement-per-second, with the score dividing by the
    penalty so the two cancelled while an operator kept earning. That inverted the ranking it was
    meant to produce -- see design/operator_selection/dynamic_penalty.md.
    """

    def _solver(self, **kw):
        sln = random_instance(seed=13, n_customers=200, n_vehicles=40, capacity=25)
        solver = SimAnnVRPSolver(sln, **kw)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        return solver

    @staticmethod
    def _set_cost(op, seconds):
        """Force scoring_cost to `seconds`, on BOTH of its branches.

        scoring_cost reads mean_valid_call_time when num_useful_calls > 0, and falls back to
        mean_call_time otherwise. Both are derived from totals and counts, so set all of them --
        setting only the valid-side totals leaves the fallback branch at 0 and divides by zero.
        """
        op.weight_by_time = True
        op._proposal_count, op._apply_count, op.num_useful_calls = 1, 0, 1
        op._propose_time_total = op._valid_propose_time_total = seconds
        op._apply_time_total = 0.0

    def test_the_penalty_is_a_ratio_against_the_roster_best(self):
        """In (0, 1], and exactly 1.0 for whichever operator has the best improvement per second."""
        solver = self._solver()
        for i, op in enumerate(solver.operators):
            op.stats.proposals, op.stats.accepts, op.stats.improvements = 100, 10, i
            op.stats.score_sum = 1.0
        solver.update_weights()

        penalties = [op.penalty for op in solver.operators]
        for p in penalties:
            self.assertGreater(p, 0.0)
            self.assertLessEqual(p, 1.0 + 1e-12)
        self.assertAlmostEqual(max(penalties), 1.0, places=12,
                               msg="the best operator must sit at penalty 1")

    def test_the_penalty_is_exactly_min_cost_over_cost(self):
        """
        Ranking by cost alone, unconditionally -- not only at plateau.

        The old penalty was `improvement_estimate / cost`, normalised against the roster best, so
        it only degenerated to `min_cost / cost` when every estimate happened to agree. Estimates
        did NOT agree in practice: they spread over five orders of magnitude, and an exhaustive
        operator's estimate stayed high enough to swamp its own cost. The improvement term is gone.
        """
        solver = self._solver()
        costs = {}
        for i, op in enumerate(solver.operators):
            seconds = 1e-5 * (i + 1)
            self._set_cost(op, seconds)
            costs[op] = seconds
            op.stats.proposals = 0                   # unproposed: no EMA, no magnet interference
        solver.update_weights()

        cheapest = min(costs.values())
        for op in solver.operators:
            self.assertAlmostEqual(op.penalty, cheapest / costs[op], places=9)

    def test_the_score_does_not_depend_on_the_penalty(self):
        """
        The score used to carry `1 / penalty`, so it cancelled against `adj_weight = weight *
        penalty` while an operator kept earning. That cancellation is REMOVED -- the penalty must
        now bite durably rather than washing out of the weight it feeds.
        """
        solver = self._solver()
        op = solver.operators[0]
        self._set_cost(op, 1e-4)

        raw = {}
        for penalty in (1.0, 0.25):
            op.penalty = penalty
            op.stats.reset()
            op.last_move = Move(kind=MoveKind.VALID, improvement=0.5)
            op.update_stats_for_accept()
            raw[penalty] = op.stats.score_sum
        self.assertAlmostEqual(raw[0.25], raw[1.0], places=12,
                               msg="the penalty must not reach the recorded score at all")

    def test_the_adjusted_weight_multiplies_the_penalty_in(self):
        """`adj_weight = weight * penalty` is where the penalty actually acts on selection."""
        solver = self._solver()
        for i, op in enumerate(solver.operators):
            op.stats.proposals, op.stats.accepts, op.stats.improvements = 100, 10, i
            op.stats.score_sum = 5.0
        solver.update_weights()
        for op in solver.operators:
            self.assertAlmostEqual(
                solver.adj_weights[op],
                op.weight * op.exploit_selection_penalty_factor * op.penalty, places=12)


class CostAccounting(SeededTestCase):
    """Stage 5: no-ops and invalids must not dilute the cost denominator."""

    def _op(self):
        sln = random_instance(seed=17, n_customers=60, n_vehicles=8)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()
        op = solver.operators[0]
        op.weight_by_time = True
        op._proposal_count = op._apply_count = op.num_useful_calls = 0
        op._propose_time_total = op._apply_time_total = op._valid_propose_time_total = 0.0
        return op

    def test_a_never_proposed_operator_is_priced_near_zero(self):
        """So everything gets sampled early rather than being priced out before its first call."""
        self.assertLessEqual(self._op().scoring_cost, 1e-11)

    def test_an_operator_that_is_never_valid_is_priced_at_its_proposal_cost(self):
        """Expensive invalids are penalised, but not catastrophically."""
        op = self._op()
        op._proposal_count, op._propose_time_total = 100, 0.5      # 5 ms each, all invalid
        self.assertAlmostEqual(op.scoring_cost, 0.005, places=9)

    def test_cheap_invalids_do_not_dilute_the_cost(self):
        """
        The point of the stage. 900 cheap invalids beside 100 expensive valid calls must price the
        operator at the VALID cost, not at the blended average.
        """
        op = self._op()
        op._proposal_count = 1000
        op.num_useful_calls = 100
        op._valid_propose_time_total = 1.0                          # 10 ms per valid call
        op._propose_time_total = 1.0 + 900 * 1e-6                   # plus 1 us per invalid
        blended = op._propose_time_total / 1000
        self.assertAlmostEqual(op.scoring_cost, 0.01, places=6)
        self.assertGreater(op.scoring_cost, blended * 9,
                           "the blended average would understate the true cost about tenfold")

    def test_the_first_valid_call_switches_the_cost_off_the_proposal_fallback(self):
        """
        `num_useful_calls > 0` is the branch condition, so one valid call moves an operator off
        its all-proposal fallback price and onto its valid-only price.

        There is NO floor holding the valid cost at or above the proposal cost. That floor existed
        until 2026-08-23 and was removed with the rest of the cost cascade -- an operator whose
        valid calls really are cheaper than its average proposal is now priced as cheap.
        """
        op = self._op()
        op._proposal_count, op._propose_time_total = 100, 1.0        # 10 ms per proposal
        self.assertAlmostEqual(op.scoring_cost, 0.01, places=9,
                               msg="no valid calls yet: priced at the proposal cost")

        op.num_useful_calls, op._valid_propose_time_total = 50, 0.1  # 2 ms per valid call
        self.assertAlmostEqual(op.scoring_cost, 0.002, places=9,
                               msg="valid calls exist: priced at the valid cost, with no floor")
