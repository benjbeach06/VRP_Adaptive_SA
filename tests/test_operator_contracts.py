"""
Contract tests for the operator layer: purity, delta accuracy, invariants, exact revert.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

Every OperatorBL must satisfy four properties, and each one catches a different bug class:

  1. evaluate() is PURE            -- an operator that quietly mutates while pricing corrupts the
                                      search, and breaks best-of-k selection outright.
  2. deltas match ground truth     -- compared TERM BY TERM, not just as a scalar improvement.
                                      "improvement off by 27.78" is a search; "travel_distance
                                      wrong, other four exact" is a location.
  3. invariants hold after apply   -- cached state (depot counts, loads, visit links, route
                                      chain) must still agree with a fresh recomputation.
  4. revert() restores EXACTLY     -- structural and cost identity. This is the only property
                                      that catches revert-only bugs, which no accepted-move
                                      check can see because they never manifest on the apply path.

Design input from the repository author: every test fixes its own generator seed (via
SeededTestCase), so cases stay valid under arbitrary ordering and when run individually.

The exhaustive sweeps are reduced by default. Set VRP_FULL_MATRIX=1 for the full ones.
"""

import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (
    Customer, FULL_MATRIX, Route, SeededTestCase,
    DirectOperator,
    all_problems, fingerprint, make_depots, make_solution, random_instance,
    raw_record_claim_problems, raw_record_completeness_problems,
    raw_record_distance_problems, route_of, route_states, term_deltas,
)
from SimAnn_VRP_BLOperators import CombineRoutes, ReassignRouteBefore


def matrix_customers(n=24):
    return [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), 1) for i in range(n)]


class OperatorContractBase(SeededTestCase):
    """Shared contract assertion. A TestCase subclass (not a bare mixin) so the
    assert* helpers it calls are actually declared; it defines no test_* methods,
    so discovery collects nothing from it directly."""
    def assert_operator_contract(self, sln, base_operator, operands, label):
        """Purity -> per-term delta -> invariants -> exact revert, for one evaluated move."""
        # Wrapped, not driven directly: the wrapper owns Move.already_applied, which
        # OperatorBL.revert() asserts on but never sets. See _harness.DirectOperator.
        operator = DirectOperator(sln, base_operator)
        before_fingerprint = fingerprint(sln)
        before_terms = sln.objective_terms()
        before_states = route_states(sln)

        move = operator.evaluate(operands)
        if not move.is_actionable:
            return False

        if not move.already_applied:
            self.assertEqual(sln.objective_terms(), before_terms,
                             f"{label}: evaluate() mutated the solution (not pure)")

        # UNCONDITIONAL, and that matters. An _evaluates_by_applying operator arrives here with the
        # structure already in the solution but its accounting still owed, and apply() is where the
        # accounting is topped up. Guarding this call on `not already_applied` -- as it was until
        # 2026-08-28 -- means a by-applying move is never accounted anywhere in this suite, so the
        # all_problems check below would pass against caches that were simply never written.
        # apply() gatekeeps itself for the structural half, so calling it always is safe.
        operator.apply(move)

        actual = term_deltas(before_terms, sln.objective_terms())
        for name, predicted, measured in zip(type(actual)._fields, move.deltas, actual):
            self.assertAlmostEqual(
                predicted, measured, places=9,
                msg=f"{label}: term '{name}' predicted {predicted} but measured {measured}")

        self.assertEqual(all_problems(sln), [], f"{label}: invariants broken after apply")

        # All three halves of the raw-record oracle. Claim was wired first, during the conversion,
        # because it is the only one that stays meaningful while records are partial. Completeness
        # and distance went in once all 24 aggregators reported -- before that, an unconverted
        # aggregator's empty record is indistinguishable from a converted one that is wrong.
        after_terms = sln.objective_terms()
        self.assertEqual(raw_record_claim_problems(before_states, move.raw_deltas), [],
                         f"{label}: raw delta record disagrees with the mutation it describes")
        self.assertEqual(raw_record_completeness_problems(before_states, sln, move.raw_deltas), [],
                         f"{label}: raw delta record is missing a route that changed")
        self.assertEqual(raw_record_distance_problems(before_terms, after_terms, move.raw_deltas), [],
                         f"{label}: raw delta record's travel_distance is wrong")

        # No commit() here: committing finalises the move and clears the operator's revert
        # payload, so a contract test that commits can no longer check the revert half.
        operator.revert(move)

        self.assertEqual(fingerprint(sln), before_fingerprint,
                         f"{label}: revert() did not restore the solution exactly")
        self.assertEqual(all_problems(sln), [], f"{label}: invariants broken after revert")
        return True


class ReassignRouteMatrix(OperatorContractBase):
    """
    Every src position x destination kind x end-depot assignment x empty-route placement.

    The end-depot sweep matters because a depot used by exactly ONE route deactivates when that
    route moves away, which is a different code path from the multi-user case. The empty-route
    dimension mirrors what the solver actually contains between periodic cleanups.
    """

    def _build(self, a_ends, b_ends, empty_spec):
        depots, customers = make_depots(), matrix_customers()
        sln = make_solution(depots, customers, [100, 100],
                            initial_depot_of=lambda i, d: d[i])
        vehicle_a, vehicle_b = sln.vehicles[0], sln.vehicles[1]
        index = iter(range(len(customers)))
        a_routes, b_routes = [], []
        for end in a_ends:
            route = route_of(customers, [next(index), next(index)], depots[end])
            sln.add_route_to_vehicle(route, vehicle_a)
            a_routes.append(route)
        for end in b_ends:
            route = route_of(customers, [next(index), next(index)], depots[end])
            sln.add_route_to_vehicle(route, vehicle_b)
            b_routes.append(route)
        if empty_spec is not None:
            group, position = empty_spec
            victim = (a_routes if group == "A" else b_routes)[position]
            while victim.path_len:
                victim.pop_customer_at(0)
        # END OF THE BUILD -- after the emptying pops, which are setup, not the move under test.
        sln.initialize_accounting()
        return sln, vehicle_a, vehicle_b, a_routes, b_routes

    def test_matrix(self):
        import itertools
        if FULL_MATRIX:
            a_patterns = list(itertools.product(range(3), repeat=3))
            b_patterns = list(itertools.product(range(3), repeat=2))
            empties = [None, ("A", 0), ("A", 1), ("A", 2), ("B", 0), ("B", 1)]
        else:
            a_patterns = [(0, 1, 2), (0, 2, 1), (1, 1, 1), (2, 0, 0)]
            b_patterns = [(1, 2), (2, 2)]
            empties = [None, ("A", 1), ("B", 0)]

        checked = 0
        for a_ends in a_patterns:
            for b_ends in b_patterns:
                for empty_spec in empties:
                    for src_index in range(len(a_ends)):
                        for dest_kind in ("B0", "B1", "B_last", "A_other", "A_last"):
                            sln, vehicle_a, vehicle_b, a_routes, b_routes = self._build(
                                a_ends, b_ends, empty_spec)
                            src = a_routes[src_index]
                            if dest_kind == "B0":
                                dest = b_routes[0]
                            elif dest_kind == "B1":
                                dest = b_routes[1]
                            elif dest_kind == "B_last":
                                dest = vehicle_b.last_route
                            elif dest_kind == "A_last":
                                dest = vehicle_a.last_route
                            else:
                                dest = [r for i, r in enumerate(a_routes) if i != src_index][0]
                            label = (f"a={a_ends} b={b_ends} empty={empty_spec} "
                                     f"src=#{src_index} dest={dest_kind}")
                            if self.assert_operator_contract(
                                    sln, ReassignRouteBefore(sln), (src, dest), label):
                                checked += 1
        self.assertGreater(checked, 0, "matrix produced no actionable moves")


class CombineRoutesMatrix(OperatorContractBase):
    """Adjacent-next, adjacent-prev and non-adjacent combines across route lengths and depots."""

    def _build(self, len1, len2, end1, end2, adjacency):
        depots, customers = make_depots(), matrix_customers()
        sln = make_solution(depots, customers, [100, 100],
                            initial_depot_of=lambda i, d: d[i])
        vehicle_a, vehicle_b = sln.vehicles[0], sln.vehicles[1]
        first = route_of(customers, range(len1), depots[end1])
        second = route_of(customers, range(12, 12 + len2), depots[end2])
        if adjacency == "next":
            sln.add_route_to_vehicle(first, vehicle_a)
            sln.add_route_to_vehicle(second, vehicle_a)
        elif adjacency == "prev":
            sln.add_route_to_vehicle(second, vehicle_a)
            sln.add_route_to_vehicle(first, vehicle_a)
        else:
            sln.add_route_to_vehicle(first, vehicle_a)
            sln.add_route_to_vehicle(second, vehicle_b)
        sln.initialize_accounting()
        return sln, first, second

    def test_matrix(self):
        checked = 0
        for adjacency in ("next", "prev", "far"):
            for len1 in (1, 2, 3):
                for len2 in (1, 2, 3):
                    for end1, end2 in ((1, 1), (0, 2), (2, 0)):
                        sln, first, second = self._build(len1, len2, end1, end2, adjacency)
                        label = f"{adjacency} len1={len1} len2={len2} ends=({end1},{end2})"
                        if self.assert_operator_contract(
                                sln, CombineRoutes(sln), (first, second), label):
                            checked += 1
        self.assertGreater(checked, 0, "matrix produced no actionable moves")


class RandomisedOperatorContract(OperatorContractBase):
    """
    Drives the real Operator wrappers so operands come from the same selection logic the solver
    accepts, then checks the BL contract on whatever they produce. Covers operators (and operand
    shapes) the hand-built matrices above don't enumerate.
    """

    def test_contract_across_random_operands(self):
        from SimAnn_VRP_Solver import SimAnnVRPSolver
        import contextlib, io

        proposals = 2000 if FULL_MATRIX else 400
        sln = random_instance(seed=20260809, n_customers=30, n_vehicles=4)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(io.StringIO()):
            solver.make_initial_solution()

        self.assertEqual(all_problems(sln), [], "initial solution violates its own invariants")

        checked = 0
        for step in range(proposals):
            wrapper = solver.operators[step % len(solver.operators)]
            before_fingerprint = fingerprint(sln)
            before_terms = sln.objective_terms()
            # BEFORE propose(), not after: a by-applying operator mutates during evaluate, so a
            # snapshot taken afterwards would already include the change it is meant to witness.
            before_states = route_states(sln)

            move = wrapper.propose()
            if not move.is_actionable:
                wrapper.revert_and_reject(move)   # gatekeeps itself
                self.assertEqual(fingerprint(sln), before_fingerprint,
                                 f"{type(wrapper).__name__}: non-actionable proposal left a change")
                continue

            label = f"{type(wrapper).__name__} (step {step})"
            if not move.already_applied:
                self.assertEqual(sln.objective_terms(), before_terms,
                                 f"{label}: propose() mutated the solution")

            # apply_for_acceptance, not apply: paired with the revert_and_reject below, this is
            # exactly the solver's accept/reject path, so the test exercises the timed production
            # route rather than a quieter one only tests use.
            #
            # UNCONDITIONAL for the same reason as assert_operator_contract above -- a by-applying
            # move's accounting is topped up here, and guarding the call would leave it unwritten.
            wrapper.apply_for_acceptance(move)

            actual = term_deltas(before_terms, sln.objective_terms())
            for name, predicted, measured in zip(type(actual)._fields, move.deltas, actual):
                self.assertAlmostEqual(
                    predicted, measured, places=9,
                    msg=f"{label}: term '{name}' predicted {predicted} but measured {measured}")
            self.assertEqual(all_problems(sln), [], f"{label}: invariants broken after apply")

            # THE RAW-RECORD CHECK BELONGS HERE, not only in assert_operator_contract. That helper
            # is reached by exactly two operator classes -- ReassignRouteBefore and CombineRoutes,
            # measured 2026-08-28 -- so the oracle wired into it covers 2 of the roster. This loop
            # cycles EVERY operator the solver actually runs, which is the coverage the aggregator
            # conversion needs. Without this, a wrong record in any other operator is silent.
            self.assertEqual(raw_record_claim_problems(before_states, move.raw_deltas), [],
                             f"{label}: raw delta record disagrees with the mutation it describes")
            self.assertEqual(raw_record_completeness_problems(before_states, sln, move.raw_deltas), [],
                             f"{label}: raw delta record is missing a route that changed")
            self.assertEqual(
                raw_record_distance_problems(before_terms, sln.objective_terms(), move.raw_deltas),
                [], f"{label}: raw delta record's travel_distance is wrong")

            wrapper.revert_and_reject(move)
            self.assertEqual(fingerprint(sln), before_fingerprint,
                             f"{label}: revert() did not restore the solution exactly")
            checked += 1

        self.assertGreater(checked, 0, "no actionable proposals were produced")


if __name__ == "__main__":
    unittest.main()
