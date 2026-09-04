"""
The vehicle-duration objective: band arithmetic, default resolution, and that the terms FIRE.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

A vehicle accrues hours from distance, customers served and routes run. Two thresholds cut that
duration into priced bands: regular pay up to `overtime_threshold`, overtime above it, and past
`time_limit` an excess rate plus a flat per-vehicle penalty for the labour-law violation. The
overtime and excess bands OVERLAP past the limit on purpose, so an hour beyond it costs the sum of
both rates and the objective stays sloped rather than flat.

WHAT THIS FILE DOES NOT COVER, DELIBERATELY
-------------------------------------------
The predicted-versus-measured check over the whole operator roster lives in
test_operator_contracts.RandomisedOperatorContract.test_contract_with_vehicle_duration_objective.
That sweep grades the processor's band arithmetic against a fresh measurement for every operator
the solver runs, which is far stronger than any hand-built case here, and its three fault
injections were confirmed to fail it. This file covers the parts that sweep cannot see: the
resolution rules on the setter, the band boundaries themselves, and the fact that a configured
objective actually moves the cost.

THE POINT OF test_a_tight_limit_actually_costs_something
--------------------------------------------------------
A penalty term that never triggers is indistinguishable from a solver that satisfies the
constraint easily, and the second reading is much more flattering than it deserves. So the limit is
set deliberately below what the solution already does, and the cost is required to move.
"""

import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _harness import (
    SeededTestCase, apply_binding_duration_model, make_depots, make_solution, random_instance,
    route_of,
)
from SimAnn_VRP_Core_Model import NO_TIME_LIMIT, FullSolution


class DurationBands(SeededTestCase):
    """The band split itself, at and around every boundary."""

    def _configured(self) -> FullSolution:
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0,
                                            overtime_threshold=8, time_limit=12,
                                            vehicle_hourly_rate=20, vehicle_overtime_rate=30)
        return sln

    def test_bands_at_and_around_each_boundary(self):
        sln = self._configured()
        # (duration, regular, overtime, excess, over_limit)
        cases = [(0, 0, 0, 0, False),
                 (7.5, 7.5, 0, 0, False),
                 (8, 8, 0, 0, False),      # AT the overtime threshold is still regular
                 (8.5, 8, 0.5, 0, False),
                 (12, 8, 4, 0, False),     # AT the legal limit is not yet a violation
                 (12.5, 8, 4.5, 0.5, True),
                 (20, 8, 12, 8, True)]
        for duration, regular, overtime, excess, over_limit in cases:
            with self.subTest(duration=duration):
                self.assertEqual(sln.duration_bands(duration),
                                 (regular, overtime, excess, over_limit))

    def test_overtime_is_not_capped_at_the_legal_limit(self):
        """Past `time_limit` the overtime band keeps accruing, so the objective stays sloped.

        A capped overtime band would make every duration past the limit cost the same once the
        flat penalty has fired, and the search would have no gradient to walk a violating vehicle
        back down.
        """
        sln = self._configured()
        _, overtime_at_20, _, _ = sln.duration_bands(20)
        _, overtime_at_30, _, _ = sln.duration_bands(30)
        self.assertEqual(overtime_at_30 - overtime_at_20, 10)

    def test_marginal_hour_past_the_limit_costs_both_rates(self):
        """The overlap is the whole design: an hour past the limit is overtime AND excess."""
        sln = self._configured()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0,
                                            overtime_threshold=8, time_limit=12,
                                            vehicle_hourly_rate=20, vehicle_overtime_rate=30,
                                            vehicle_excess_hour_rate=300)

        def cost(duration):
            regular, overtime, excess, over_limit = sln.duration_bands(duration)
            return (sln.vehicle_hourly_rate * regular + sln.vehicle_overtime_rate * overtime
                    + sln.vehicle_excess_hour_rate * excess
                    + sln.vehicle_time_limit_penalty * over_limit)

        self.assertAlmostEqual(cost(14) - cost(13), 30 + 300, places=9)
        # Below the limit only overtime applies, which is what makes the step at the limit real.
        self.assertAlmostEqual(cost(11) - cost(10), 30, places=9)

    def test_unset_thresholds_disable_their_bands(self):
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0)
        self.assertEqual(sln.overtime_threshold, NO_TIME_LIMIT)
        self.assertEqual(sln.time_limit, NO_TIME_LIMIT)
        # Everything is regular time, and nothing is ever a violation.
        self.assertEqual(sln.duration_bands(1000), (1000, 0, 0, False))


class DurationSetterDefaults(SeededTestCase):
    """The -1 resolution rules, which decide what an unspecified argument means."""

    def test_everything_unspecified_leaves_the_objective_off(self):
        sln = FullSolution()
        self.assertFalse(sln.duration_terms_active)
        sln.set_vehicle_duration_objectives()
        self.assertFalse(sln.duration_terms_active)
        self.assertEqual(sln.vehicle_hourly_rate, 0)
        self.assertEqual(sln.vehicle_overtime_rate, 0)
        self.assertEqual(sln.vehicle_excess_hour_rate, 0)
        self.assertEqual(sln.vehicle_time_limit_penalty, 0)

    def test_a_stated_limit_gets_a_stated_consequence(self):
        """A legal bound with no penalty is a bound the search would ignore, so both defaults fire."""
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0, time_limit=12,
                                            vehicle_hourly_rate=20, vehicle_overtime_rate=30)
        self.assertEqual(sln.vehicle_time_limit_penalty, 1000)
        self.assertEqual(sln.vehicle_excess_hour_rate, 300)   # 10x the overtime rate

    def test_excess_rate_falls_back_to_the_hourly_rate(self):
        """With no overtime rate given, 10x the hourly rate is the only rate there is to scale."""
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0, time_limit=12,
                                            vehicle_hourly_rate=20)
        self.assertEqual(sln.vehicle_excess_hour_rate, 200)

    def test_no_limit_means_no_penalty_defaults(self):
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0, vehicle_hourly_rate=20)
        self.assertEqual(sln.vehicle_time_limit_penalty, 0)
        self.assertEqual(sln.vehicle_excess_hour_rate, 0)

    def test_explicit_zero_is_not_treated_as_unspecified(self):
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0, time_limit=12,
                                            vehicle_hourly_rate=20,
                                            vehicle_time_limit_penalty=0,
                                            vehicle_excess_hour_rate=0)
        self.assertEqual(sln.vehicle_time_limit_penalty, 0)
        self.assertEqual(sln.vehicle_excess_hour_rate, 0)

    def test_overtime_threshold_above_the_limit_is_refused(self):
        sln = FullSolution()
        with self.assertRaises(ValueError):
            sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0,
                                                overtime_threshold=14, time_limit=12)

    def test_active_flag_follows_the_inputs_not_the_prices(self):
        """Priced but with no duration accruing is genuinely a zero objective, not a disabled one.

        This is what lets the processor skip the whole block: with every input at zero, every
        vehicle's duration is zero, so every band is zero and there is nothing to predict.
        """
        sln = FullSolution()
        sln.set_vehicle_duration_objectives(vehicle_hourly_rate=20, time_limit=12)
        self.assertFalse(sln.duration_terms_active)
        self.assertEqual(sln.vehicle_duration_terms(), (0, 0, 0, 0))

        sln.set_vehicle_duration_objectives(load_time_per_route=1.0)
        self.assertTrue(sln.duration_terms_active)


class DurationOnARealSolution(SeededTestCase):
    """Against a built solution: the caches agree with the structure, and the cost responds."""

    def _solution(self) -> FullSolution:
        import contextlib, io
        from SimAnn_VRP_Solver import SimAnnVRPSolver
        sln = random_instance(seed=20260903, n_customers=30, n_vehicles=4)
        with contextlib.redirect_stdout(io.StringIO()):
            SimAnnVRPSolver(sln).make_initial_solution()
        return sln

    def test_cached_duration_equals_the_structural_recompute(self):
        """The dual truth. vehicle_duration reads three sink-written caches; the twin walks the
        routes. Nothing else compares them at this level."""
        sln = self._solution()
        apply_binding_duration_model(sln)
        for vehicle in sln.vehicles:
            self.assertAlmostEqual(sln.vehicle_duration(vehicle),
                                   sln.recompute_vehicle_duration(vehicle), places=9,
                                   msg=f"vehicle {vehicle.vID}: cached duration disagrees "
                                       f"with a fresh walk")

    def test_all_three_inputs_reach_the_duration(self):
        """Each input arrives through a different per-vehicle aggregate, so each is switched on
        alone. A term wired to only one of them would still pass a check that left the other two
        at zero."""
        sln = self._solution()
        vehicle = next(v for v in sln.vehicles if v.num_customers > 0)
        for field in ("travel_time_per_distance", "service_time_per_customer",
                      "load_time_per_route"):
            with self.subTest(input=field):
                sln.set_vehicle_duration_objectives(**{field: 1.0})
                self.assertGreater(sln.vehicle_duration(vehicle), 0)
                self.assertAlmostEqual(sln.vehicle_duration(vehicle),
                                       sln.recompute_vehicle_duration(vehicle), places=9)

    def test_the_objective_is_off_and_free_by_default(self):
        sln = self._solution()
        self.assertFalse(sln.duration_terms_active)
        terms = sln.objective_terms()
        self.assertEqual((terms.vehicle_regular_hours, terms.vehicle_overtime_hours,
                          terms.vehicle_excess_hours, terms.vehicles_over_time_limit),
                         (0, 0, 0, 0))

    def test_a_tight_limit_actually_costs_something(self):
        """THE CHECK THIS FEATURE EXISTS TO PASS.

        A term that is silently never triggered looks exactly like a constraint the solver
        satisfies comfortably. So the limit goes deliberately below what the solution already
        does, and all three consequences are required: vehicles over the limit, excess hours
        accrued, and a strictly higher solution cost.
        """
        sln = self._solution()
        before_cost = sln.solution_cost()

        apply_binding_duration_model(sln)
        terms = sln.objective_terms()

        self.assertGreater(terms.vehicles_over_time_limit, 0,
                           "no vehicle broke a limit set below the longest vehicle's duration")
        self.assertGreater(terms.vehicle_excess_hours, 0)
        self.assertGreater(terms.vehicle_overtime_hours, 0)
        self.assertGreater(sln.solution_cost(), before_cost,
                           "the duration objective changed no cost, so nothing prices it")

    def test_raising_the_limit_removes_the_violation(self):
        """The other direction, so the test above cannot pass on an unconditional penalty."""
        sln = self._solution()
        apply_binding_duration_model(sln)
        self.assertGreater(sln.objective_terms().vehicles_over_time_limit, 0)

        longest = max(sln.recompute_vehicle_duration(v) for v in sln.vehicles)
        sln.set_vehicle_duration_objectives(travel_time_per_distance=1.0,
                                            service_time_per_customer=0.5,
                                            load_time_per_route=2.0,
                                            overtime_threshold=longest * 2,
                                            time_limit=longest * 3,
                                            vehicle_hourly_rate=1.0, vehicle_overtime_rate=1.5)
        terms = sln.objective_terms()
        self.assertEqual(terms.vehicles_over_time_limit, 0)
        self.assertEqual(terms.vehicle_excess_hours, 0)
        self.assertEqual(terms.vehicle_overtime_hours, 0)
        self.assertGreater(terms.vehicle_regular_hours, 0)

    def test_a_copied_solution_carries_the_duration_objective(self):
        import copy
        sln = self._solution()
        apply_binding_duration_model(sln)
        clone = copy.copy(sln)
        self.assertTrue(clone.duration_terms_active)
        self.assertEqual(clone.time_limit, sln.time_limit)
        self.assertAlmostEqual(clone.solution_cost(), sln.solution_cost(), places=9)


class DurationOnAHandBuiltSolution(SeededTestCase):
    """One solution whose duration is known by hand, so the arithmetic is checked against a
    number rather than against another derivation of itself."""

    def test_duration_matches_a_hand_computed_value(self):
        from _harness import Customer
        depots = make_depots()
        # Two customers on the axis through depot 0 at (10, 10), so the arcs are exact integers:
        # depot -> (20, 10) -> (30, 10) -> depot, i.e. 10 + 10 + 20 = 40.
        customers = [Customer(0, (20, 10), 1), Customer(1, (30, 10), 1)]
        sln = make_solution(depots, customers, [100], initial_depot_of=lambda i, d: d[0])
        route = route_of(customers, [0, 1], depots[0])
        sln.add_route_to_vehicle(route, sln.vehicles[0])
        sln.initialize_accounting()

        sln.set_vehicle_duration_objectives(travel_time_per_distance=0.5,
                                            service_time_per_customer=2.0,
                                            load_time_per_route=3.0)
        # 0.5 * 40 distance + 2.0 * 2 customers + 3.0 * 1 active route
        self.assertAlmostEqual(sln.vehicle_duration(sln.vehicles[0]), 20 + 4 + 3, places=9)
        self.assertAlmostEqual(sln.recompute_vehicle_duration(sln.vehicles[0]), 27, places=9)

    def test_an_empty_route_costs_no_loading_stage(self):
        """"Routes run" is the ACTIVE route count. An empty route in a vehicle's list is a
        modelling artifact between cleanups; no truck was loaded for it."""
        from _harness import Customer
        depots = make_depots()
        customers = [Customer(0, (20, 10), 1), Customer(1, (30, 10), 1)]
        sln = make_solution(depots, customers, [100], initial_depot_of=lambda i, d: d[0])
        vehicle = sln.vehicles[0]
        sln.add_route_to_vehicle(route_of(customers, [0, 1], depots[0]), vehicle)
        sln.initialize_accounting()

        sln.set_vehicle_duration_objectives(load_time_per_route=3.0)
        self.assertAlmostEqual(sln.vehicle_duration(vehicle), 3.0, places=9)

        empty = route_of(customers, [], depots[0])
        vehicle.append_route(empty)
        sln.all_routes.add(empty)
        sln.initialize_accounting()
        self.assertEqual(vehicle.num_routes, 2)
        self.assertAlmostEqual(sln.vehicle_duration(vehicle), 3.0, places=9)
        self.assertAlmostEqual(sln.recompute_vehicle_duration(vehicle), 3.0, places=9)


if __name__ == "__main__":
    unittest.main()
