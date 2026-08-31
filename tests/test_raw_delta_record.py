"""
Composition of RawDeltaRecord -- the merge rule the raw-delta accounting refactor rests on.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author. Design input from the repository author: the
staged rollout these records exist to serve, and the decision that None carries "not on the
solution" rather than a dedicated UNASSIGNED sentinel.

Sequential accounting has implicit coverage today through _SequentialCombineRoutes and
cost_deltas_for_removing_empty_routes. The merge RULE itself had none, and it earns its own tests
for two reasons. It is one rule standing in for what would otherwise be five per-field rules, so a
mistake in it is a mistake everywhere at once. And a wrong merge is silent: it yields a well-formed
record that simply prices a move incorrectly, with nothing structural to trip over.
"""
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (Customer, Depot, SeededTestCase, Vehicle, depot_usage_problems, make_depots,
                      make_solution, raw_record_claim_problems,
                      raw_record_completeness_problems, raw_record_distance_problems, route_of,
                      route_states)
from SimAnn_VRP_Core_Model import AccountingRecord, Num, RawDeltaRecord, VIRTUAL_DEPOT


def rec(travel: Num = 0, loads=None, counts=None, starts=None, vehicles=None) -> RawDeltaRecord:
    """Test-only convenience: build a record naming only the maps a case cares about.

    Omitting a map here means what it means in production code -- nothing moved in that field --
    so these tests exercise the real shape rather than a padded one.
    """
    return RawDeltaRecord(travel, loads or {}, counts or {}, starts or {}, vehicles or {})


class RawDeltaComposition(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.depots = make_depots()
        customers = [Customer(i, (i * 7 % 40, i * 13 % 31), 1) for i in range(4)]
        self.route_a = route_of(customers, [0], self.depots[0])
        self.route_b = route_of(customers, [1], self.depots[1])
        self.vehicle = Vehicle(i=0, initial_depot=self.depots[0], capacity=100)

    def test_distance_adds(self):
        self.assertAlmostEqual(rec(3.5).then(rec(-1.25)).travel_distance, 2.25, places=9)

    def test_a_route_in_both_records_keeps_the_first_base_and_the_last_final(self):
        """The whole point of transition form: the composed record still carries the true base."""
        first = rec(loads={self.route_a: (1, 5)}, counts={self.route_a: (1, 3)})
        second = rec(loads={self.route_a: (5, 9)}, counts={self.route_a: (3, 4)})

        composed = first.then(second)

        self.assertEqual(composed.load_changes[self.route_a], (1, 9))
        self.assertEqual(composed.customer_deltas[self.route_a], (1, 4))

    def test_a_route_returned_to_where_it_started_is_dropped(self):
        composed = rec(loads={self.route_a: (2, 7)}).then(rec(loads={self.route_a: (7, 2)}))

        self.assertEqual(composed.load_changes, {})

    def test_the_maps_drop_independently(self):
        """A route whose load returns to base but whose count does not stays in ONE map only.

        This is the property the per-field shape buys, and the old whole-route entry could not
        express it: it had to keep the entry alive for both fields or for neither.
        """
        first = rec(loads={self.route_a: (2, 7)}, counts={self.route_a: (1, 3)})
        second = rec(loads={self.route_a: (7, 2)}, counts={self.route_a: (3, 4)})

        composed = first.then(second)

        self.assertEqual(composed.load_changes, {})
        self.assertEqual(composed.customer_deltas[self.route_a], (1, 4))

    def test_create_then_dispose_composes_to_nothing(self):
        """Creation and disposal are ordinary transitions through None, so this needs no special
        case in the merge rule -- it falls out of the drop rule."""
        created = rec(counts={self.route_a: (0, 1)},
                      starts={self.route_a: (None, self.depots[0])},
                      vehicles={self.route_a: (None, self.vehicle)})
        disposed = rec(counts={self.route_a: (1, 0)},
                       starts={self.route_a: (self.depots[0], None)},
                       vehicles={self.route_a: (self.vehicle, None)})

        composed = created.then(disposed)

        self.assertEqual(composed.customer_deltas, {})
        self.assertEqual(composed.start_depot_changes, {})
        self.assertEqual(composed.vehicle_changes, {})

    def test_a_route_touched_by_only_one_record_passes_through(self):
        first = rec(loads={self.route_a: (1, 4)})
        second = rec(loads={self.route_b: (0, 2)})

        composed = first.then(second)

        self.assertEqual(composed.load_changes[self.route_a], (1, 4))
        self.assertEqual(composed.load_changes[self.route_b], (0, 2))

    def test_an_unchanged_entry_is_dropped_even_from_a_single_record(self):
        """The drop rule is uniform. An aggregator should not emit a no-op entry, but if it does,
        composing must not preserve it -- otherwise "did this move change anything?" gets a
        different answer depending on how many records were merged."""
        noop = rec(loads={self.route_a: (4, 4)})

        self.assertEqual(noop.then(RawDeltaRecord()).load_changes, {})

    def test_composition_asserts_when_the_second_record_has_a_different_base(self):
        """`later` must be measured against the state `self` left. Silently chaining across a gap
        would produce a well-formed record describing a transition that never happened."""
        first = rec(vehicles={self.route_a: (None, self.vehicle)})
        # Claims to start from no vehicle, but the first record already attached one.
        second = rec(vehicles={self.route_a: (None, None)})

        with self.assertRaises(AssertionError):
            first.then(second)

    def test_load_is_exempt_from_the_gap_assert(self):
        """Float drift across a chain of load moves is expected, so composing must not assert on
        it. A wrong load still surfaces, through the overload term."""
        first = rec(loads={self.route_a: (1, 5)})
        second = rec(loads={self.route_a: (5.000000001, 9)})

        self.assertEqual(first.then(second).load_changes[self.route_a], (1, 9))

    def test_an_omitted_field_is_shared_and_cannot_be_written(self):
        """The defaults are ONE shared empty map, so sharing has to be made safe by immutability.

        A plain {} default would be a single mutable dict behind every record ever built, and the
        first write into it would corrupt every other record silently. Sharing an immutable map
        instead costs no allocation and makes that failure impossible rather than unlikely.
        """
        one, two = RawDeltaRecord(), RawDeltaRecord()

        self.assertIs(one.load_changes, two.load_changes)
        with self.assertRaises(TypeError):
            one.load_changes[self.route_a] = (0, 1)  # type: ignore - that is the point

    def test_composition_order_is_deterministic(self):
        """Dict order is insertion order, and the solver behavior must not depend on how a record
        was built. Same inputs, identical key order."""
        first = rec(loads={self.route_a: (1, 2)})
        second = rec(loads={self.route_b: (3, 4)})

        self.assertEqual(list(first.then(second).load_changes),
                         [self.route_a, self.route_b])
        self.assertEqual(list(second.then(first).load_changes),
                         [self.route_b, self.route_a])


class AccountingApplication(SeededTestCase):
    """
    FullSolution.apply_accounting is the ONLY place a derived cache is written, and it must decide
    nothing -- every step function was already resolved by the processor.

    The contract the tests below pin down: apply ADDS a record, revert applies record.inverse,
    which subtracts the same values. Counters take plain deltas; route loads and start depots are
    stated as (initial, final) pairs, so applying twice equals applying once.

    start_depot_changes passes through raw -- the sink removes the route from the initial depot's
    RouteSet and adds it to the final one, skipping VIRTUAL_DEPOT on both passes. Order across
    apply/revert is NOT restored: RouteSet is swap-with-last, and a position-carrying inverse was
    rejected because it would run during pricing. A record that disagrees with the solution raises
    rather than passing silently.
    """

    def setUp(self):
        super().setUp()
        self.depots = make_depots()
        customers = [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), 1) for i in range(6)]
        self.sln = make_solution(self.depots, customers, [100])
        self.vehicle = self.sln.vehicles[0]
        self.routes = []
        for index in range(3):
            route = route_of(customers, [index], self.depots[0])
            self.sln.add_route_to_vehicle(route, self.vehicle)
            self.sln.initialize_accounting()
            self.routes.append(route)

    def depot_order(self, depot=None):
        return [str(route) for route in self.sln.depot_route_starts[depot or self.depots[0]]]

    def test_an_empty_record_is_a_no_op(self):
        before = self.depot_order()
        record = AccountingRecord()

        self.assertTrue(record.is_empty)
        self.assertTrue(record.inverse.is_empty)
        self.sln.apply_accounting(record)

        self.assertEqual(self.depot_order(), before)

    def counters(self) -> tuple[int, int, int]:
        return (self.vehicle.num_routes_overloaded, self.vehicle.num_routes_with_customers,
                self.vehicle.num_customers)

    def test_vehicle_counter_deltas_apply_and_the_inverse_subtracts_them(self):
        """The whole sink contract in one test: apply adds, revert subtracts the same record."""
        before = self.counters()
        record = AccountingRecord(vehicle_delta_routes_overloaded={self.vehicle: 2},
                                  vehicle_delta_active_routes={self.vehicle: -1},
                                  vehicle_delta_num_customers={self.vehicle: 3})

        self.sln.apply_accounting(record)
        self.assertEqual(self.counters(), (before[0] + 2, before[1] - 1, before[2] + 3))

        self.sln.apply_accounting(record.inverse)
        self.assertEqual(self.counters(), before)

    def test_num_customers_is_sink_written_like_the_other_counters(self):
        """It is a plain sum with no step function of its own, and it is still sink-written.

        The processor reads it as the BASE for vehicles_activated. A base the mutators wrote would
        already hold the after-value when an _evaluates_by_applying operator reaches the processor.
        """
        before = self.vehicle.num_customers

        self.sln.apply_accounting(AccountingRecord(vehicle_delta_num_customers={self.vehicle: 4}))

        self.assertEqual(self.vehicle.num_customers, before + 4)

    def test_a_route_load_write_stores_the_final_value_and_the_inverse_the_initial(self):
        """Loads carry (initial, final) rather than a delta, so applying twice is applying once."""
        route = self.routes[0]
        before = route.current_load
        record = AccountingRecord(route_loads={route: (before, before + 17)})

        self.sln.apply_accounting(record)
        self.assertEqual(route.current_load, before + 17)
        self.sln.apply_accounting(record)
        self.assertEqual(route.current_load, before + 17)

        self.sln.apply_accounting(record.inverse)
        self.assertEqual(route.current_load, before)

    def test_a_depot_move_applies_and_the_inverse_puts_it_back(self):
        """start_depot_changes passes through raw: remove from the initial, add to the final."""
        moved = self.routes[0]
        record = AccountingRecord(
            start_depot_changes={moved: (self.depots[0], self.depots[1])})

        self.sln.apply_accounting(record)
        self.assertNotIn(str(moved), self.depot_order(self.depots[0]))
        self.assertIn(str(moved), self.depot_order(self.depots[1]))

        self.sln.apply_accounting(record.inverse)
        self.assertIn(str(moved), self.depot_order(self.depots[0]))
        self.assertNotIn(str(moved), self.depot_order(self.depots[1]))

    def test_a_virtual_end_is_skipped_on_both_passes(self):
        """A route going inactive counts against no depot, and virtual is how the record says so.

        This is the transition that has no geometric depot change behind it: an emptied route keeps
        its start depot and still has to leave depot_route_starts.
        """
        leaving = self.routes[0]
        record = AccountingRecord(
            start_depot_changes={leaving: (self.depots[0], VIRTUAL_DEPOT)})

        self.sln.apply_accounting(record)
        self.assertNotIn(str(leaving), self.depot_order())

        self.sln.apply_accounting(record.inverse)
        self.assertIn(str(leaving), self.depot_order())

    def test_removing_a_route_that_does_not_start_there_raises(self):
        """A record that disagrees with the solution is a processor bug, and must not pass
        silently -- a missed discard leaves depot_route_starts permanently wrong."""
        stranger = route_of([Customer(99, (5, 5), 1)], [0], self.depots[0])
        record = AccountingRecord(
            start_depot_changes={stranger: (self.depots[0], self.depots[1])})

        with self.assertRaises(KeyError):
            self.sln.apply_accounting(record)


class RawRecordOracle(SeededTestCase):
    """
    The raw-record oracle checks the record against the mutation it claims to describe.

    It is deliberately TWO halves, and the split is not cosmetic. During the aggregator conversion
    the records are partial by construction, so a single combined check would fail on every
    unconverted aggregator and end up switched off exactly when it is needed. The CLAIM half is
    meaningful from the first converted aggregator; the COMPLETENESS half only becomes true once
    all 24 report.

    These tests exist because both halves are vacuous while records are empty, and a detector
    that has never been seen to fire is not evidence of anything.
    """

    def setUp(self):
        super().setUp()
        self.depots = make_depots()
        customers = [Customer(i, (11 * i % 70, (17 * i) % 61 + 3), 3) for i in range(6)]
        self.sln = make_solution(self.depots, customers, [100])
        self.route = route_of(customers, [0, 1, 2], self.depots[0])
        self.sln.add_route_to_vehicle(self.route, self.sln.vehicles[0])
        self.sln.initialize_accounting()
        self.before = route_states(self.sln)
        self.was_load = self.route.recompute_current_load()
        self.was_count = self.route.num_customers
        # A real mutation: one customer out, so load and count both move.
        self.route.pop_customer_at(0)

    def truthful_record(self, loads=None, counts=None) -> RawDeltaRecord:
        """The record the mutation in setUp should have produced.

        Start depot and vehicle are absent rather than written as (x, x): the pop moved neither,
        and absence is how this shape says so.
        """
        return rec(loads=loads or {self.route: (self.was_load,
                                               self.route.recompute_current_load())},
                   counts=counts or {self.route: (self.was_count, self.route.num_customers)})

    def test_a_truthful_record_is_silent(self):
        self.assertEqual(raw_record_claim_problems(self.before, self.truthful_record()), [])

    def test_it_fires_on_a_wrong_FINAL_value(self):
        wrong = self.truthful_record(
            counts={self.route: (self.was_count, self.route.num_customers + 5)})

        problems = raw_record_claim_problems(self.before, wrong)

        self.assertTrue(any("num_customers" in p and "ended at" in p for p in problems),
                        f"a wrong final value produced no finding: {problems}")

    def test_it_fires_on_a_wrong_INITIAL_value(self):
        """The base matters as much as the final: a step function is resolved from it, so a record
        that misremembers where a route started prices the crossing wrong."""
        wrong = self.truthful_record(
            loads={self.route: (self.was_load + 99, self.route.recompute_current_load())})

        problems = raw_record_claim_problems(self.before, wrong)

        self.assertTrue(any("load" in p and "started at" in p for p in problems),
                        f"a wrong initial value produced no finding: {problems}")

    def test_an_empty_record_is_silent_but_INCOMPLETE(self):
        """The two halves are genuinely different checks, and this is the case that proves it.
        The route really changed and the record says nothing -- which the claim half cannot see,
        because it only verifies what is claimed."""
        empty = RawDeltaRecord()

        self.assertEqual(raw_record_claim_problems(self.before, empty), [])

        problems = raw_record_completeness_problems(self.before, self.sln, empty)
        self.assertTrue(any("no entry" in p for p in problems),
                        f"a missing entry produced no finding: {problems}")

    def test_completeness_is_satisfied_by_a_truthful_record(self):
        self.assertEqual(
            raw_record_completeness_problems(self.before, self.sln, self.truthful_record()), [])

    def test_completeness_fires_per_field_not_per_route(self):
        """A record listing the route under one field but not another is still incomplete.

        This is the failure the per-field shape makes possible and the whole-route shape could not:
        the route HAS an entry, so a per-route check passes while the load is silently wrong.
        """
        count_only = rec(counts={self.route: (self.was_count, self.route.num_customers)})

        problems = raw_record_completeness_problems(self.before, self.sln, count_only)

        self.assertTrue(
            any("load_changes" in p for p in problems),
            f"a route present in one map but missing from another was not caught: {problems}")


class RawRecordDistance(SeededTestCase):
    """
    The THIRD half of the raw-record oracle, and the four aggregators it currently covers.

    Distance sits on RawDeltaRecord itself, not inside `routes`, so neither the claim half nor the
    completeness half can see it. That matters most for the INTRA-ROUTE aggregators, which by
    design populate distance and nothing else: without this check their records are verified by no
    oracle at all, and a deterministic run comparing IDENTICAL says nothing about them, because
    the processor does not consume the record yet.

    The aggregators are exercised DIRECTLY rather than through their operators. Two of the four --
    cost_deltas_for_permutation and cost_deltas_for_subpermutation -- are not reachable from any
    OperatorBL today, so an operator-driven test would silently skip them.
    """

    def setUp(self):
        super().setUp()
        self.depots = make_depots()
        # Spread out, and deliberately not collinear: a reorder has to actually change distance,
        # or every assertion below passes on 0 == 0 and proves nothing.
        customers = [Customer(i, (13 * i % 71, (29 * i) % 53 + 5), 3) for i in range(6)]
        self.sln = make_solution(self.depots, customers, [100])
        self.route = route_of(customers, [0, 1, 2, 3, 4], self.depots[0])
        self.sln.add_route_to_vehicle(self.route, self.sln.vehicles[0])
        self.sln.initialize_accounting()

    def check(self, price_and_mutate):
        """Price, mutate, then hold the record's distance against what the solution really moved.

        Returns the measured change so a caller can assert it is non-trivial.
        """
        before_terms = self.sln.objective_terms()
        record = price_and_mutate()
        after_terms = self.sln.objective_terms()

        self.assertEqual(raw_record_distance_problems(before_terms, after_terms, record), [],
                         "the record's travel_distance disagrees with the solution")
        return after_terms.travel_distance - before_terms.travel_distance

    # ---------------------------------------------------------------- the detector itself
    def test_it_fires_on_a_wrong_distance(self):
        before_terms = self.sln.objective_terms()
        self.route.reverse_customer_chain(range(0, 3))
        after_terms = self.sln.objective_terms()
        real = after_terms.travel_distance - before_terms.travel_distance
        self.assertNotAlmostEqual(real, 0, places=6, msg="the setup mutation moved no distance")

        problems = raw_record_distance_problems(
            before_terms, after_terms, RawDeltaRecord.for_travel(real + 7.5))

        self.assertTrue(any("travel_distance" in p for p in problems),
                        f"a wrong distance produced no finding: {problems}")

    def test_it_fires_on_a_record_that_reports_zero(self):
        """The case that rules out the 'either 0 or correct' phrasing. An unconverted aggregator
        and a converted one that forgot to populate distance look identical from here, so the
        oracle has to reject zero once it is applied to a converted aggregator."""
        before_terms = self.sln.objective_terms()
        self.route.reverse_customer_chain(range(1, 4))
        after_terms = self.sln.objective_terms()

        problems = raw_record_distance_problems(before_terms, after_terms, RawDeltaRecord())

        self.assertTrue(problems, "a record reporting no distance produced no finding")

    # ---------------------------------------------------------------- the converted aggregators
    def test_chain_reversal_reports_its_distance(self):
        span = range(1, 4)

        def priced():
            record = self.route.cost_deltas_if_customer_chain_reversed(span)
            self.route.reverse_customer_chain(span)
            return record

        self.assertNotAlmostEqual(self.check(priced), 0, places=6,
                                  msg="the reversal moved no distance, so nothing was proven")

    def test_permutation_reports_its_distance(self):
        permutation = [4, 0, 3, 1, 2]

        def priced():
            record = self.route.cost_deltas_for_permutation(permutation)
            self.route.permute(permutation)
            return record

        self.assertNotAlmostEqual(self.check(priced), 0, places=6,
                                  msg="the permutation moved no distance, so nothing was proven")

    def test_subpermutation_reports_its_distance(self):
        subpermutation = [3, 1, 0]

        def priced():
            record = self.route.cost_deltas_for_subpermutation(subpermutation)
            self.route.sub_permute(subpermutation)
            return record

        self.assertNotAlmostEqual(self.check(priced), 0, places=6,
                                  msg="the subpermutation moved no distance, so nothing was proven")

    def test_adjacent_customer_swap_reports_its_distance(self):
        def priced():
            first = self.route.path[1]
            record = self.route.cost_deltas_for_adjacent_customer_swap_starting_with(first)
            self.route.swap_customers(1, 2)
            return record

        self.assertNotAlmostEqual(self.check(priced), 0, places=6,
                                  msg="the swap moved no distance, so nothing was proven")


if __name__ == "__main__":
    unittest.main()
