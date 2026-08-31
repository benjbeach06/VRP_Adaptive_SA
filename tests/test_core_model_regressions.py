"""
Regression tests for concrete Core Model bugs, one test per historical defect.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

Every test here encodes a bug that was actually shipped and actually found. Each docstring states
the defect, so a future refactor that reintroduces it fails with an explanation rather than a
bare assertion. The recurring shape is worth internalising: nearly all of these were correct
abstractions wired to the wrong call site, not wrong ideas -- so they were invisible to code
review and only caught by comparing a cached value against a recomputed one.

Design input from the repository author: every test fixes its own generator seed (via
SeededTestCase), so cases stay valid under arbitrary ordering and when run individually.
"""

import copy
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (
    Customer, CustomerVisit, Depot, DirectOperator, FullSolution, Route, Vehicle,
    SeededTestCase,
    chain_problems, make_depots, make_solution, route_of, term_deltas,
    vehicle_counter_problems, visit_link_problems,
)
from SimAnn_VRP_BLOperators import CombineRoutes, ReassignCustomerChain, SplitRoute


def simple_customers(n=12, demand=1):
    return [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), demand) for i in range(n)]


class RouteLinkage(SeededTestCase):
    def test_combine_relinks_the_merged_tail(self):
        """
        combine_with appends the other route's customers and used to relink only the seam. With
        2+ absorbed customers the tail stayed wired to the ABSORBED route's last_visit, so
        self.last_visit.prev_visit still pointed at the pre-merge last customer. Every delta
        computed off last_visit was then silently wrong.
        """
        for absorbed_count in (1, 2, 3):
            with self.subTest(absorbed=absorbed_count):
                depots, customers = make_depots(), simple_customers()
                sln = make_solution(depots, customers, [100])
                vehicle = sln.vehicles[0]
                route1 = route_of(customers, [0], depots[1])
                sln.add_route_to_vehicle(route1, vehicle)
                sln.initialize_accounting()
                route2 = route_of(customers, range(6, 6 + absorbed_count), depots[2])
                sln.add_route_to_vehicle(route2, vehicle)
                sln.initialize_accounting()

                route1.combine_with(route2)

                self.assertEqual(visit_link_problems(sln), [])
                self.assertIs(route1.last_visit.prev_visit, route1.path[-1])
                nodes = [route1.start_depot] + list(route1.path) + [route1.end_depot]
                expected = sum(nodes[i].distance(nodes[i + 1]) for i in range(len(nodes) - 1))
                self.assertAlmostEqual(route1.total_distance(), expected, places=9)

    def test_last_route_start_depot_follows_final_route_end_depot(self):
        """
        A vehicle's LastRoute sentinel records the depot its predecessor ends at, but that was
        only written when routes were LINKED. Changing the end depot of an already-linked FINAL
        route left it stale, because the update path has no FirstRouteVisit to delegate to at the
        tail. Vehicle.final_depot and any "insert before LastRoute" pricing then read a wrong
        depot -- which predicted a zero travel delta for moves that really did change a start.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        route1 = route_of(customers, [0, 1], depots[1])
        sln.add_route_to_vehicle(route1, vehicle)
        sln.initialize_accounting()
        route2 = route_of(customers, [2, 3], depots[1])
        sln.add_route_to_vehicle(route2, vehicle)
        sln.initialize_accounting()
        self.assertIs(vehicle.last_route.start_depot, route2.end_depot)

        route2.set_end_depot(depots[2])

        self.assertIs(vehicle.last_route.start_depot, route2.end_depot,
                      "LastRoute.start_depot went stale after the final route changed end depot")
        self.assertIs(vehicle.final_depot, depots[2])

        route1.set_end_depot(depots[2])   # a mid-chain change must still propagate normally
        self.assertIs(route2.start_depot, route1.end_depot)


class DeltaArithmetic(SeededTestCase):
    def test_combining_with_immediate_successor_prices_both_depot_visits(self):
        """
        Combining with the immediate successor collapses a shared depot stop that is TWO visit
        objects (this route's last_visit and the successor's first_visit) at the same location.
        Pricing it as a single-node removal always evaluated to exactly 0, because that node's
        next_visit sits at the identical location.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        route1 = route_of(customers, [0, 1], depots[1])
        sln.add_route_to_vehicle(route1, vehicle)
        sln.initialize_accounting()
        route2 = route_of(customers, [6, 7], depots[1])
        sln.add_route_to_vehicle(route2, vehicle)
        sln.initialize_accounting()
        self.assertIs(route1.next_route, route2)

        before = sln.objective_terms()
        operator = CombineRoutes(sln)
        move = operator.evaluate((route1, route2))
        self.assertTrue(move.is_actionable)
        self.assertNotAlmostEqual(move.deltas.travel_distance, 0.0, places=9,
                                  msg="adjacent combine priced its travel delta as exactly zero")

        operator.apply(move)
        # OperatorBL.apply performs the MUTATION only. Accounting is the Operator wrapper's
        # job, and these tests drive the BL layer directly, so the record has to be applied
        # here or objective_terms() below reads caches the move never reached.
        sln.apply_accounting(move.accounting)
        actual = term_deltas(before, sln.objective_terms())
        for name, predicted, measured in zip(type(actual)._fields, move.deltas, actual):
            self.assertAlmostEqual(predicted, measured, places=9, msg=f"term {name} mismatched")

    def test_intra_route_move_reports_no_overload_change(self):
        """
        Moving a customer within one route only reorders it, so the load -- and both load-derived
        terms -- cannot change. Summing a pop-delta and an insert-delta measured against the SAME
        original load does not cancel, because max(0, load - capacity) is nonlinear: at
        load == capacity the pop contributes 0 and the insert contributes +demand, inventing
        overload worth a six-figure penalty.
        """
        depots = make_depots()
        customers = [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), 5) for i in range(6)]
        sln = make_solution(depots, customers, [10])   # capacity == load of two customers
        route = route_of(customers, [0, 1], depots[0])
        sln.add_route_to_vehicle(route, sln.vehicles[0])
        sln.initialize_accounting()
        self.assertEqual(route.current_load, sln.vehicles[0].capacity)

        before = sln.objective_terms()
        operator = DirectOperator(sln, ReassignCustomerChain(sln))
        # Chain of one, so this is still the single-customer move the regression was found with.
        move = operator.evaluate((route, 0, route, 1, False))
        self.assertTrue(move.is_actionable)
        self.assertEqual(move.deltas.total_route_overload, 0)
        self.assertEqual(move.deltas.vehicles_overloaded, 0)

        operator.apply(move)
        actual = term_deltas(before, sln.objective_terms())
        self.assertEqual(actual.total_route_overload, 0)
        self.assertEqual(actual.vehicles_overloaded, 0)

    def test_split_index_is_first_customer_of_the_new_route(self):
        """
        split_at treats split_index as the first customer of the SECOND half. The delta function
        used the opposite convention, so it priced the wrong boundary and rejected the last valid
        split outright.
        """
        depots, customers = make_depots(), simple_customers()
        for split_index in (1, 2, 3):
            with self.subTest(split_index=split_index):
                sln = make_solution(depots, customers, [100])
                route = route_of(customers, [0, 1, 2, 3], depots[0])
                sln.add_route_to_vehicle(route, sln.vehicles[0])
                sln.initialize_accounting()

                before = sln.objective_terms()
                operator = SplitRoute(sln)
                # Trailing operand is the destination for the second half; see SplitRouteOps.
                move = operator.evaluate((route, split_index, depots[1],
                                          Route([], route.end_depot)))
                self.assertTrue(move.is_actionable, "valid split reported as non-actionable")
                operator.apply(move)
                sln.apply_accounting(move.accounting)

                self.assertEqual(route.path_len, split_index)
                actual = term_deltas(before, sln.objective_terms())
                for name, predicted, measured in zip(type(actual)._fields, move.deltas, actual):
                    self.assertAlmostEqual(predicted, measured, places=9,
                                           msg=f"term {name} mismatched")

    def test_combine_revert_restores_the_absorbing_route_end_depot(self):
        """
        split_at assigns its refill depot to the FIRST half. Revert used to pass the absorbed
        route's end depot, which is what the absorbing route already carries post-combine -- a
        no-op that silently left it with the wrong end depot forever.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        route1 = route_of(customers, [0], depots[0])
        sln.add_route_to_vehicle(route1, vehicle)
        sln.initialize_accounting()
        route2 = route_of(customers, [6], depots[2])
        sln.add_route_to_vehicle(route2, vehicle)
        sln.initialize_accounting()
        original_end_depot = route1.end_depot

        operator = DirectOperator(sln, CombineRoutes(sln))
        move = operator.evaluate((route1, route2))
        self.assertTrue(move.is_actionable)
        operator.apply(move)
        operator.revert(move)

        self.assertIs(route1.end_depot, original_end_depot,
                      "revert left the absorbing route carrying the absorbed route's end depot")


class SolutionStateIsolation(SeededTestCase):
    def test_separate_solutions_do_not_share_containers(self):
        """
        FullSolution declared all_routes/vehicles/depot_route_starts as CLASS attributes with an empty
        __init__, so every instance mutated one shared set of containers. Python class-body
        defaults are shared for mutable objects -- unlike C# field initializers, which are
        per-instance.
        """
        depots, customers = make_depots(), simple_customers()
        first = make_solution(depots, customers, [100])
        route = route_of(customers, [0], depots[0])
        first.add_route_to_vehicle(route, first.vehicles[0])
        first.initialize_accounting()

        second = FullSolution()

        self.assertEqual(len(second.all_routes), 0)
        self.assertEqual(len(second.vehicles), 0)
        self.assertEqual(len(second.depot_route_starts), 0)
        self.assertIsNot(first.all_routes, second.all_routes)
        self.assertIsNot(first.vehicles, second.vehicles)
        self.assertIsNot(first.depot_route_starts, second.depot_route_starts)

    def test_snapshot_is_independent_of_the_live_solution(self):
        """copy.copy must deep-enough-copy that mutating the original leaves a snapshot untouched."""
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        sln.add_route_to_vehicle(route_of(customers, [0, 1], depots[1]), vehicle)
        sln.initialize_accounting()
        live_route = route_of(customers, [2, 3], depots[0])
        sln.add_route_to_vehicle(live_route, vehicle)
        sln.initialize_accounting()

        original_cost = sln.solution_cost()
        snapshot = copy.copy(sln)
        self.assertAlmostEqual(snapshot.solution_cost(), original_cost, places=9)
        for attribute in ("all_routes", "vehicles", "depot_route_starts", "empty_routes"):
            self.assertIsNot(getattr(snapshot, attribute), getattr(sln, attribute),
                             f"snapshot shares {attribute} with the live solution")

        live_route.pop_customer_at(0)

        self.assertAlmostEqual(snapshot.solution_cost(), original_cost, places=9,
                               msg="snapshot changed when the live solution was mutated")
        self.assertNotAlmostEqual(sln.solution_cost(), original_cost, places=9)


class VehicleCounterOracle(SeededTestCase):
    """
    The per-vehicle counters had NO oracle until 2026-08-28. This proves the new one FIRES.

    Silence is not evidence. An oracle that computes nothing is silent too, and this gap was
    invisible by construction: objective_terms() READS num_customers and num_routes_overloaded,
    and every per-term contract assertion compares move.deltas against a diff of two
    objective_terms() calls. A corrupt counter therefore makes the prediction and the measurement
    wrong by the SAME amount, and the assertion passes. Two of the five objective terms --
    vehicles_activated and vehicles_overloaded -- rest entirely on these counters.

    So the corruption test below is not ceremony. It is the only thing standing between that
    failure mode and a green suite.
    """

    def _two_route_vehicle(self, capacity=100):
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [capacity])
        vehicle = sln.vehicles[0]
        sln.add_route_to_vehicle(route_of(customers, [0, 1], depots[0]), vehicle)
        sln.add_route_to_vehicle(route_of(customers, [2], depots[0]), vehicle)
        sln.initialize_accounting()
        return sln, vehicle

    def test_the_oracle_is_silent_on_a_correct_solution(self):
        sln, vehicle = self._two_route_vehicle()
        self.assertEqual(vehicle_counter_problems(sln), [])
        # Asserted explicitly so a truth function that returns 0 for everything cannot pass by
        # agreeing with a counter that is also 0.
        self.assertEqual(vehicle.num_customers, 3)
        self.assertEqual(vehicle.num_routes_with_customers, 2)

    def test_the_oracle_fires_on_each_corrupted_counter(self):
        for name in ("num_customers", "num_routes_with_customers", "num_routes_overloaded"):
            with self.subTest(counter=name):
                sln, vehicle = self._two_route_vehicle()
                self.assertEqual(vehicle_counter_problems(sln), [])

                setattr(vehicle, name, getattr(vehicle, name) + 7)

                problems = vehicle_counter_problems(sln)
                self.assertTrue(
                    any(name in problem for problem in problems),
                    f"corrupting {name} produced no finding from the oracle: {problems}")

    def test_the_overload_counter_truth_follows_a_real_overload(self):
        """Exercises the truth side, not just the disagreement side.

        Capacity 1 with unit demands: the two-customer route is genuinely overloaded and the
        one-customer route is not, so the recomputed count is 1 rather than trivially 0.
        """
        sln, vehicle = self._two_route_vehicle(capacity=1)
        self.assertEqual(vehicle.num_routes_overloaded, 1)
        self.assertEqual(vehicle_counter_problems(sln), [])


class ChainMembershipOracle(SeededTestCase):
    """
    chain_problems must catch vehicle.routes drifting from the route chain.

    Both structures are maintained by link_to_vehicle_*/unlink_from_vehicle, and nothing compared
    them until 2026-08-28. A drift here is nastier than a wrong number: vehicle.routes is what
    rand_choice draws operands from, while the chain is what the objective is computed over. So a
    disagreement makes the solver propose against routes the objective cannot see, or ignore
    routes it is paying for, and neither shows up as a cost mismatch.
    """

    def test_it_fires_when_the_routeset_loses_a_chained_route(self):
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        route = route_of(customers, [0, 1], depots[0])
        sln.add_route_to_vehicle(route, vehicle)
        sln.add_route_to_vehicle(route_of(customers, [2], depots[0]), vehicle)
        sln.initialize_accounting()
        self.assertEqual(chain_problems(sln), [])

        # Drop it from the RouteSet only. The chain still links it, so the two now disagree.
        vehicle.routes.remove(route)

        problems = chain_problems(sln)
        self.assertTrue(
            any("vehicle.routes" in problem for problem in problems),
            f"RouteSet drift from the chain produced no finding: {problems}")


if __name__ == "__main__":
    unittest.main()
