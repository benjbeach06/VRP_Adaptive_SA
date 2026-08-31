"""
The processor's own derivations, tested against cases the operator contract suite cannot reach.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author. Design input from the repository author: the
decision that the overload hinge must read each end of the vehicle transition rather than one
shared capacity.

WHY THIS FILE EXISTS SEPARATELY FROM THE CONTRACT SUITE
------------------------------------------------------
tests/test_operator_contracts.py already checks every term against ground truth, by diffing two
calls to objective_terms() around a real mutation. That is the stronger check wherever it applies,
and it is where a wrong derivation normally gets caught.

It cannot catch ONE thing: its instance gives every vehicle the SAME capacity. So a processor that
resolved overload against a single shared capacity -- instead of against each end of the route's
vehicle transition -- would price every one of those moves correctly and be green. The bug only
appears when a route crosses between vehicles whose capacities differ, which the contract instance
never constructs.

These tests therefore drive AccountingProcessor.process directly, with records built by hand over
vehicles of DELIBERATELY different capacity. Building the record by hand is the point: it is the
only way to state a transition the live instance will not produce.

THE PROCESSOR READS THE RECORD, NOT THE SOLUTION -- and that is why a hand-built record is a fair
test rather than a fiction. For steps 1 and 2 both terms are resolved entirely from the transitions
the record carries, so `sln` is passed only to satisfy the signature. Step 3 changes that, and
these tests will need a solution whose aggregate state actually matches the record.
"""
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import Customer, SeededTestCase, Vehicle, make_depots, make_solution, route_of
from SimAnn_VRP_Accounting import AccountingProcessor
from SimAnn_VRP_Core_Model import RawDeltaRecord


class OverloadDerivation(SeededTestCase):
    """total_route_overload: max(0, load - capacity) differenced across each route's transition."""

    def setUp(self):
        super().setUp()
        self.depots = make_depots()
        customers = [Customer(i, (i * 7 % 40, i * 13 % 31), 1) for i in range(4)]
        # Two routes, used only as record KEYS. The processor never reads a route's own state.
        self.route_a = route_of(customers, [0], self.depots[0])
        self.route_b = route_of(customers, [1], self.depots[1])

        # THE CAPACITIES DIFFER BY DESIGN. That is the whole reason this file exists.
        self.sln = make_solution(self.depots, customers, [100, 10])
        self.roomy, self.tight = self.sln.vehicles[0], self.sln.vehicles[1]
        self.assertNotEqual(self.roomy.capacity, self.tight.capacity,
                            "these tests are vacuous unless the two vehicles differ")

    def overload_of(self, loads=None, vehicles=None) -> float:
        """The processor's total_route_overload for a record carrying no distance.

        Only the two maps the hinge reads are populated. A route absent from one of them kept that
        field, and the processor reads it off the route -- which is exactly the behaviour under
        test, so the omissions here are deliberate rather than shorthand.
        """
        record = RawDeltaRecord(0, loads or {}, {}, {}, vehicles or {})
        terms, _ = AccountingProcessor.process(record, self.sln)
        return terms.total_route_overload

    def test_the_same_load_overloads_a_smaller_vehicle(self):
        """
        THE CASE THE CONTRACT SUITE CANNOT SEE. Load does not move at all; only the vehicle does.

        A processor using one shared capacity reports 0 here, whichever capacity it picked, because
        the two loads are equal. The correct answer is +40: 50 units fit in the roomy vehicle and
        overflow the tight one by 40.
        """
        self.assertEqual(
            self.overload_of({self.route_a: (50, 50)}, {self.route_a: (self.roomy, self.tight)}), 40)

    def test_moving_to_a_roomier_vehicle_relieves_the_overload(self):
        """The same transition backwards, so a sign error cannot pass both this and the last."""
        self.assertEqual(
            self.overload_of({self.route_a: (50, 50)}, {self.route_a: (self.tight, self.roomy)}), -40)

    def test_a_route_leaving_the_solution_charges_its_whole_overload_back(self):
        """
        Disposal: vehicle -> None. A route on no vehicle contributes 0, exactly as
        Route.amount_overloaded returns 0 when self.vehicle is None.

        A shared-capacity formula would compute max(0, 50 - 10) on the final end too and report no
        change, leaving the overload charged forever against a route that no longer exists.
        """
        self.assertEqual(
            self.overload_of({self.route_a: (50, 0)}, {self.route_a: (self.tight, None)}), -40)

    def test_a_route_entering_the_solution_charges_from_zero(self):
        """Creation: None -> vehicle. The mirror of disposal, and SplitRoute's live case."""
        self.assertEqual(
            self.overload_of({self.route_a: (0, 50)}, {self.route_a: (None, self.tight)}), 40)

    def test_a_route_on_no_vehicle_at_either_end_is_free(self):
        """Unassigned load is not overloaded load. There is no capacity to exceed."""
        self.assertEqual(
            self.overload_of({self.route_a: (0, 50)}, {self.route_a: (None, None)}), 0)

    def test_load_below_capacity_costs_nothing(self):
        """The flat half of the hinge. Only the amount ABOVE capacity is charged."""
        self.assertEqual(
            self.overload_of({self.route_a: (1, 9)}, {self.route_a: (self.tight, self.tight)}), 0)

    def test_crossing_the_capacity_boundary_charges_only_the_excess(self):
        """The hinge itself: load rises by 8 but only the 3 units past capacity are charged."""
        self.assertEqual(
            self.overload_of({self.route_a: (5, 13)}, {self.route_a: (self.tight, self.tight)}), 3)

    def test_every_route_in_the_record_contributes(self):
        """
        Two routes, each against its OWN vehicle. A load swap that is neutral by volume is not
        neutral by overload once the two vehicles differ -- which is the non-additivity the whole
        refactor exists to resolve in one place.
        """
        overload = self.overload_of(
            {self.route_a: (50, 20), self.route_b: (20, 50)},
            {self.route_a: (self.tight, self.tight),
             self.route_b: (self.roomy, self.roomy)})
        # route_a: max(0, 20-10) - max(0, 50-10) = 10 - 40 = -30. route_b never exceeds 100.
        self.assertEqual(overload, -30)

    def test_an_empty_record_moves_nothing(self):
        terms, _ = AccountingProcessor.process(RawDeltaRecord.empty(), self.sln)
        self.assertEqual(terms.total_route_overload, 0)
        self.assertEqual(terms.travel_distance, 0)

    def test_distance_passes_through_untouched_alongside_the_overload(self):
        """Step 1's term must survive step 2. Both are produced by the one call."""
        record = RawDeltaRecord(7.5, {self.route_a: (50, 50)}, {}, {},
                                {self.route_a: (self.roomy, self.tight)})
        terms, _ = AccountingProcessor.process(record, self.sln)
        self.assertAlmostEqual(terms.travel_distance, 7.5, places=9)
        self.assertEqual(terms.total_route_overload, 40)

    def test_a_route_joining_an_idle_vehicle_activates_and_overloads_it(self):
        """
        The three coupled terms, resolved from one record. This replaced a step-2 test that
        asserted they stayed ZERO -- true only while the aggregators still produced them.

        route_a carries one customer and 50 units onto `tight`, whose capacity is 10. The vehicle
        was idle and unloaded, so it crosses zero on both counters at once.
        """
        record = RawDeltaRecord(1.0, {self.route_a: (0, 50)}, {}, {},
                                {self.route_a: (None, self.tight)})
        terms, accounting = AccountingProcessor.process(record, self.sln)

        self.assertEqual(terms.vehicles_activated, 1)
        self.assertEqual(terms.vehicles_overloaded, 1)
        # NOT 1. route_a was never linked to a vehicle, so its start depot is still the
        # VirtualDepot placeholder, and a virtual depot is never counted as used. It is also
        # unhashable, so a processor that failed to skip it would raise rather than miscount --
        # which is how the missing guard was found.
        self.assertEqual(terms.depots_activated, 0)
        self.assertEqual(dict(accounting.start_depot_changes), {})

        # One route, overloaded, joining an idle vehicle: each counter moves by exactly one.
        self.assertEqual(dict(accounting.vehicle_delta_routes_overloaded), {self.tight: 1})
        self.assertEqual(dict(accounting.vehicle_delta_active_routes), {self.tight: 1})
        self.assertEqual(dict(accounting.vehicle_delta_num_customers), {self.tight: 1})


if __name__ == "__main__":
    unittest.main()
