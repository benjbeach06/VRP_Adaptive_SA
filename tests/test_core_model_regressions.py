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
    Customer, CustomerVisit, Depot, FullSolution, Route, Vehicle,
    SeededTestCase,
    depot_usage_problems, make_depots, make_solution, route_of, term_deltas, visit_link_problems,
)
from SimAnn_VRP_BLOperators import CombineRoutes, ReassignCustomerAt, SplitRoute


def simple_customers(n=12, demand=1):
    return [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), demand) for i in range(n)]


class DepotUsageAccounting(SeededTestCase):
    """depot_num_uses is incremental; it must match a fresh count at all times."""

    def test_decrement_happens_even_when_depot_has_other_users(self):
        """
        Removing a route's last customer makes it inactive, so its start depot loses a use --
        ALWAYS, not only when that depot drops to zero accepts.

        The decrement used to be gated on will_deactivate_depot_if_removed(), which additionally
        requires num_routes_starting_here == 1. That is the depot-ACTIVATION question, not the
        usage-COUNT question, so with 2+ routes sharing a depot the decrement was skipped and
        depot_num_uses drifted permanently upward.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        # Both routes start at depot 0 (the vehicle's initial depot, and route1's end depot).
        route1 = route_of(customers, [0], depots[0])
        sln.add_route_to_vehicle(route1, vehicle)
        route2 = route_of(customers, [1], depots[0])
        sln.add_route_to_vehicle(route2, vehicle)
        self.assertEqual(sln.depot_num_uses[depots[0]], 2)

        route1.pop_customer_at(0)

        self.assertEqual(sln.depot_num_uses[depots[0]], 1,
                         "depot usage did not decrement when another route still used the depot")
        self.assertEqual(depot_usage_problems(sln), [])

    def test_popping_only_customer_when_depot_has_one_user_does_not_raise(self):
        """
        The decrement path called uncount_route_in_depot(), which exists only on LastRouteVisit --
        FirstRouteVisit spells it uncount_route_depot_use. It never fired only because the
        (buggy) guard above was almost always false, so fixing that guard would otherwise have
        converted a silent drift into an AttributeError.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        route = route_of(customers, [0], depots[1])
        sln.add_route_to_vehicle(route, sln.vehicles[0])
        self.assertEqual(sln.depot_num_uses[depots[0]], 1)

        route.pop_customer_at(0)   # must not raise

        self.assertEqual(sln.depot_num_uses[depots[0]], 0)
        self.assertEqual(depot_usage_problems(sln), [])

    def test_increment_for_empty_route_whose_start_and_end_differ(self):
        """
        A route "accepts" its depot when it is ACTIVE (has customers and is assigned). Insertion
        used to gate the increment on is_trivial (empty AND start == end), so inserting into an
        empty route whose start != end never incremented -- drift in the opposite direction.
        """
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        route = route_of(customers, [0], depots[1])          # starts at depot 0, ends at depot 1
        sln.add_route_to_vehicle(route, sln.vehicles[0])
        route.pop_customer_at(0)
        self.assertTrue(route.is_empty and not route.is_trivial)
        self.assertEqual(sln.depot_num_uses[depots[0]], 0)

        route.insert_customer(CustomerVisit(customers[2]), 0)

        self.assertEqual(sln.depot_num_uses[depots[0]], 1,
                         "insertion into an empty non-cycle route did not re-count its depot")
        self.assertEqual(depot_usage_problems(sln), [])


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
                route2 = route_of(customers, range(6, 6 + absorbed_count), depots[2])
                sln.add_route_to_vehicle(route2, vehicle)

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
        route2 = route_of(customers, [2, 3], depots[1])
        sln.add_route_to_vehicle(route2, vehicle)
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
        route2 = route_of(customers, [6, 7], depots[1])
        sln.add_route_to_vehicle(route2, vehicle)
        self.assertIs(route1.next_route, route2)

        before = sln.objective_terms()
        operator = CombineRoutes(sln)
        move = operator.evaluate((route1, route2))
        self.assertTrue(move.is_actionable)
        self.assertNotAlmostEqual(move.deltas.travel_distance, 0.0, places=9,
                                  msg="adjacent combine priced its travel delta as exactly zero")

        operator.apply(move)
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
        self.assertEqual(route.current_load, sln.vehicles[0].capacity)

        before = sln.objective_terms()
        operator = ReassignCustomerAt(sln)
        move = operator.evaluate((route, 0, route, 1))
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

                before = sln.objective_terms()
                operator = SplitRoute(sln)
                move = operator.evaluate((route, split_index, depots[1]))
                self.assertTrue(move.is_actionable, "valid split reported as non-actionable")
                operator.apply(move)

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
        route2 = route_of(customers, [6], depots[2])
        sln.add_route_to_vehicle(route2, vehicle)
        original_end_depot = route1.end_depot

        operator = CombineRoutes(sln)
        move = operator.evaluate((route1, route2))
        self.assertTrue(move.is_actionable)
        operator.apply(move)
        operator.revert(move)

        self.assertIs(route1.end_depot, original_end_depot,
                      "revert left the absorbing route carrying the absorbed route's end depot")


class SolutionStateIsolation(SeededTestCase):
    def test_separate_solutions_do_not_share_containers(self):
        """
        FullSolution declared all_routes/vehicles/depot_num_uses as CLASS attributes with an empty
        __init__, so every instance mutated one shared set of containers. Python class-body
        defaults are shared for mutable objects -- unlike C# field initialisers, which are
        per-instance.
        """
        depots, customers = make_depots(), simple_customers()
        first = make_solution(depots, customers, [100])
        route = route_of(customers, [0], depots[0])
        first.add_route_to_vehicle(route, first.vehicles[0])

        second = FullSolution()

        self.assertEqual(len(second.all_routes), 0)
        self.assertEqual(len(second.vehicles), 0)
        self.assertEqual(len(second.depot_num_uses), 0)
        self.assertIsNot(first.all_routes, second.all_routes)
        self.assertIsNot(first.vehicles, second.vehicles)
        self.assertIsNot(first.depot_num_uses, second.depot_num_uses)

    def test_snapshot_is_independent_of_the_live_solution(self):
        """copy.copy must deep-enough-copy that mutating the original leaves a snapshot untouched."""
        depots, customers = make_depots(), simple_customers()
        sln = make_solution(depots, customers, [100])
        vehicle = sln.vehicles[0]
        sln.add_route_to_vehicle(route_of(customers, [0, 1], depots[1]), vehicle)
        live_route = route_of(customers, [2, 3], depots[0])
        sln.add_route_to_vehicle(live_route, vehicle)

        original_cost = sln.solution_cost()
        snapshot = copy.copy(sln)
        self.assertAlmostEqual(snapshot.solution_cost(), original_cost, places=9)
        for attribute in ("all_routes", "vehicles", "depot_num_uses", "empty_routes"):
            self.assertIsNot(getattr(snapshot, attribute), getattr(sln, attribute),
                             f"snapshot shares {attribute} with the live solution")

        live_route.pop_customer_at(0)

        self.assertAlmostEqual(snapshot.solution_cost(), original_cost, places=9,
                               msg="snapshot changed when the live solution was mutated")
        self.assertNotAlmostEqual(sln.solution_cost(), original_cost, places=9)


if __name__ == "__main__":
    unittest.main()
