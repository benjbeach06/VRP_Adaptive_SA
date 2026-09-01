"""
The raw-delta accounting processor: resolves a RawDeltaRecord plus current solution state into an
ObjectiveTermDelta and an AccountingRecord. Reads state, writes nothing.

This is the one place a step function is evaluated. The core model reports raw structural
transitions, this module resolves them, Operator applies the result, and FullSolution is the sink.

See design/raw_delta_accounting/ for the four-layer split, why this is a separate module, and how
the outputs are derived.
"""
from collections import defaultdict

# Oddly: Route doesn't need to be imported: we never create any new Route-type variables!
# We can use route-type objects contained within other imports without importing Route directly.
# Same for C#. In C#, you can use "var"/"dynamic" to initialize types you didn't import!

# All our aggregation is vehicle-level or depot-level; route-level is our starting point.
from SimAnn_VRP_Core_Model import (AccountingRecord, Depot, FullSolution, VIRTUAL_DEPOT,
                                   Num, ObjectiveTermDelta, RawDeltaRecord,
                                   Vehicle)

class AccountingProcessor:
    """
    Resolves raw structural deltas into objective terms and cache updates. Static and stateless: it
    reads the solution's current aggregate state, so a composed record is reconstructed once rather
    than after every step.

    See design/raw_delta_accounting/processor.md.
    """

    @staticmethod
    def process(record: RawDeltaRecord,
                sln: FullSolution) -> tuple[ObjectiveTermDelta, AccountingRecord]:
        """
        Resolve `record` against `sln`, returning the objective delta and the cache updates.

        MUST NOT MUTATE `sln`. It runs during evaluate(), which pricing expects to leave the
        solution alone even for the two _evaluates_by_applying operators.

        One pass builds each touched route's (initial, final) transitions from the record where it
        speaks and the live route where it stays silent; every term and cache update falls out of
        those. The bases read off `sln` must hold the pre-mutation value, which is why current load
        and vehicle customer count travel in the accounting record rather than staying
        mutator-maintained.

        See design/raw_delta_accounting/processor.md.
        """
        loads = record.load_changes
        counts = record.customer_deltas
        depots = record.start_depot_changes
        vehicles = record.vehicle_changes
        travels = record.travel_changes

        # Every route any map speaks about. A route absent from all four moved nothing, so it can
        # contribute to no term and needs no entry to stand in for it.

        overload_delta : Num = 0
        num_vehicles_overloaded_delta: int = 0
        num_active_vehicles_delta: int = 0
        num_depots_used_delta: int = 0

        depot_usage_deltas: defaultdict[Depot, int] = defaultdict(int)

        # VEHICLE accounting records: routes_overloaded, routes_with_customers, num_customers.
        vehicle_delta_routes_overloaded: defaultdict[Vehicle, int] = defaultdict(int)
        vehicle_delta_active_routes: defaultdict[Vehicle, int] = defaultdict(int)
        vehicle_delta_num_customers: defaultdict[Vehicle, int] = defaultdict(int)
        vehicle_delta_travel: defaultdict[Vehicle, Num] = defaultdict(float)

        # ROUTE accounting records: Just raw loads. Counts are accounted via path length.

        # DEPOT accounting records: just raw depot changes, since depot_starts must be fully updated.

        # Process net overload and customer count changes. NOTE: counts and loads usually change in tandem,
        # except for rare edge cases, like swapping a fixed-load-sum, different-customer count chain or vice-versa
        # Note also: we keep accounting changes that aggregate to no-changes, since they're cheap to apply and not really cheaper to check-and-remove (set removal).
        # Conversely, we remove raw delta changes that aggregate to no-changes, since they add expensive work, and removing them is cheap (just set to NO_CHANGE)
        for route in loads.keys() | counts.keys() | vehicles.keys():
            # Load dats changes if routes swap vehicles or change their load
            vehicle = route.vehicle
            load = route.current_load
            count = route.num_customers

            count_i, count_f = counts[route] if route in counts else (count, count)
            load_i, load_f = loads[route] if route in loads else (load, load)
            veh_i, veh_f = vehicles[route] if route in vehicles else (vehicle, vehicle)

            veh_i_exists = veh_i is not None
            veh_f_exists = veh_f is not None

            # Route overloading
            old_overload = max(0, load_i - veh_i.capacity) if veh_i_exists else 0 # type: ignore
            new_overload = max(0, load_f - veh_f.capacity) if veh_f_exists else 0 # type: ignore

            # net overload
            overload_delta += new_overload - old_overload

            # Vehicle num routes overloaded and customer count changes
            same_vehicle = veh_i_exists and veh_f_exists and veh_i == veh_f
            # Key: we don't want to populate dictionary entries when there are no changes
            # Cost for key is extra branching. Benefit is reduced dictionary bloat.
            if same_vehicle:
                assert veh_i is not None
                old_was_overloaded = old_overload > 0
                new_is_overloaded = new_overload > 0
                # just process the diff into veh_i if there is one
                if old_was_overloaded != new_is_overloaded:
                    vehicle_delta_routes_overloaded[veh_i] += new_is_overloaded - old_was_overloaded

                if count_i != count_f:
                    vehicle_delta_num_customers[veh_i] += count_f - count_i
                    vehicle_delta_active_routes[veh_i] += (count_f > 0) - (count_i > 0)
            else:
                # The route's whole distance moves with it. current_travel is sink-written, so
                # it still holds the pre-move value here even when an operator priced by mutating
                # -- the same reason load and the customer count travel in the record.
                travel_carried = route.current_travel
                if veh_i_exists:
                    assert veh_i is not None
                    if travel_carried:
                        vehicle_delta_travel[veh_i] -= travel_carried

                    old_was_overloaded = old_overload > 0
                    if old_was_overloaded:
                        vehicle_delta_routes_overloaded[veh_i] -= 1

                    if count_i > 0:
                        vehicle_delta_num_customers[veh_i] -= count_i
                        vehicle_delta_active_routes[veh_i] -= 1

                if veh_f_exists:
                    assert veh_f is not None
                    if travel_carried:
                        vehicle_delta_travel[veh_f] += travel_carried

                    new_is_overloaded = new_overload > 0
                    if new_is_overloaded:
                        vehicle_delta_routes_overloaded[veh_f] += 1

                    if count_f > 0:
                        vehicle_delta_num_customers[veh_f] += count_f
                        vehicle_delta_active_routes[veh_f] += 1

        # Travel. Each entry is a plain delta on one route, so the solution-level term is their
        # sum and the per-vehicle aggregate is the same sum grouped by the vehicle each route ENDS
        # on. A route that also changed vehicle already had its whole pre-move distance moved
        # across in the loop above, so adding the delta to the destination lands the final value
        # on the right vehicle.
        travel_delta: Num = 0
        for (route, route_travel) in travels.items():
            travel_delta += route_travel
            final_vehicle = vehicles[route][1] if route in vehicles else route.vehicle
            if final_vehicle is not None:
                vehicle_delta_travel[final_vehicle] += route_travel

        # Process vehicle is_overloaded and is_active delta changes
        # NOTE: Vehicle is_active and has_overloaded_route are tracked implicitly,
        # via vehicle.num_customers and vehicle, respectively. So activations/overloading
        # deltas can be aggregated.
        for (vehicle, num_routes_overloaded_delta) in vehicle_delta_routes_overloaded.items():
            num_overloaded = vehicle.num_routes_overloaded
            old_was_overloaded = num_overloaded > 0
            new_is_overloaded = num_overloaded + num_routes_overloaded_delta > 0

            num_vehicles_overloaded_delta += new_is_overloaded - old_was_overloaded

        for (vehicle, num_customers_delta) in vehicle_delta_num_customers.items():
            num_customers = vehicle.num_customers
            vehicle_was_active = num_customers > 0
            vehicle_is_active = num_customers + num_customers_delta > 0

            num_active_vehicles_delta += vehicle_is_active - vehicle_was_active

        # Now, net depot activation accounting. Raw depot reassignments pass through directly to accounting,
        # as they are necessary to reconstruct the route-sets per depot.
        for (route, (start_depot_i, start_depot_f)) in depots.items():
            if start_depot_i == start_depot_f: continue

            if start_depot_i is not VIRTUAL_DEPOT:
                depot_usage_deltas[start_depot_i] -= 1
            if start_depot_f is not VIRTUAL_DEPOT:
                depot_usage_deltas[start_depot_f] += 1

        # Now aggregate depot activations/deactivations
        depot_starts = sln.depot_route_starts
        for (depot, depot_usage_delta) in depot_usage_deltas.items():
            uses = len(depot_starts[depot])
            was_used = uses > 0
            is_used = uses + depot_usage_delta > 0

            num_depots_used_delta += is_used - was_used

        # Finally, construct objective term and accounting
        objective_deltas = ObjectiveTermDelta(
            travel_distance=travel_delta,
            total_route_overload=overload_delta,
            depots_activated=num_depots_used_delta,
            vehicles_activated=num_active_vehicles_delta,
            vehicles_overloaded=num_vehicles_overloaded_delta)

        accounting_record = AccountingRecord(vehicle_delta_routes_overloaded = vehicle_delta_routes_overloaded,
                                            vehicle_delta_active_routes = vehicle_delta_active_routes,
                                            vehicle_delta_num_customers = vehicle_delta_num_customers,
                                            vehicle_delta_travel = vehicle_delta_travel,
                                            route_loads = loads,
                                            route_delta_travel = travels,
                                            start_depot_changes = depots)

        return objective_deltas, accounting_record
