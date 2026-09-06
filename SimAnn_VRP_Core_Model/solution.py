"""
FullSolution: the top of the model, and the single sink for every accounting write.

It owns the instance (customers, depots, vehicles), the objective coefficients, the neighbor
tables, and every cached objective term. Two responsibilities are worth separating when reading
it:

  THE INSTANCE -- set_customers / set_depots / set_objectives / add_vehicle, and the neighbor
                  tables built from them.
  THE SINK     -- apply_accounting is the ONLY place a cached objective quantity is written.
                  Every cached quantity also has a recompute-from-scratch twin used for
                  verification; most real bugs here surfaced as a disagreement between the two.

Vehicle-duration pricing lives here rather than on Vehicle because the bands are a solution-level
objective, not a vehicle property. See design/objective/objective_terms.md.
"""
import copy
from collections import defaultdict
from math import ceil
from typing import Collection, List, Mapping

from .basics import Num, from_iterable
from .neighbors import (CUSTOMER_DEPOTS_K, CUSTOMER_NEIGHBORS_K, _locations_array,
                        _require_dense_ids, nearest_indices)
from .nodes import VIRTUAL_DEPOT, Customer, Depot
from .randomness import rand_choice, rand_index
from .records import NO_CHANGES, AccountingRecord, ObjectiveTermDelta, RawDeltaRecord
from .route_set import RouteSet
from .routes import LastRoute, Route
from .vehicle import Vehicle

# Named rather than a bare `inf`: the modules that `import *` from here also `import *` from the
# solver, and two bare `inf` names collide.
NO_TIME_LIMIT: Num = float("inf")


class FullSolution:
    __slots__ = "all_routes", "vehicles", "empty_routes", "unit_travel_cost", "cost_per_vehicle", "cost_per_depot", \
                "unit_overload_penalty", "vehicle_overload_penalty", "depots", "customers", "capacity_per_vehicle", \
                "total_customer_capacity", "mean_customer_capacity", "min_vehicle_capacity", "max_vehicle_capacity", \
                "mean_vehicle_capacity", "total_vehicle_capacity", "num_routes_lb", "depot_route_starts", "version", \
                "neighbors", "neighbor_rank", "depot_neighbors", "customer_depots", \
                "travel_time_per_distance", "service_time_per_customer", "load_time_per_route", \
                "overtime_threshold", "time_limit", "vehicle_hourly_rate", "vehicle_overtime_rate", \
                "vehicle_excess_hour_rate", "vehicle_time_limit_penalty", "duration_terms_active"

    # NOTE: annotations only -- no values. Every field is initialized per-instance in __init__.
    # These must never carry defaults: a class-level `vehicles: list = []` (or RouteSet()/defaultdict())
    # is created ONCE and shared by every FullSolution ever built, so in-place mutation
    # (all_routes.add, vehicles.append, depot_route_starts[d] += 1) leaks across instances.
    #all_routes: RouteSet
    #vehicles: list[Vehicle]

    #empty_routes: RouteSet

    # Objective terms
    #unit_travel_cost: Num
    #cost_per_vehicle: Num
    #cost_per_depot: Num

    # unit feasibility penalty for overloading a src_route. $1000 per unit to replace a broken truck should suffice XD
    # Strongly encourages splitting or reassigning customers from overloaded routes
    #unit_overload_penalty: Num
    # Strongly discourages temporary src_route overloading. Per-vehicle computation prevents penalization of splitting
    # two severely overloaded routes into one far less overloaded src_route.
    #vehicle_overload_penalty: Num  # activated feasibility penalty for overloading any vehicle in a src_route. Don't wanna replace the truck.

    #region Vehicle duration objective. See design/objective/objective_terms.md.
    # The three duration inputs.
    #travel_time_per_distance: Num
    #service_time_per_customer: Num
    #load_time_per_route: Num

    # The two band thresholds.
    #overtime_threshold: Num
    #time_limit: Num

    # The four prices.
    #vehicle_hourly_rate: Num
    #vehicle_overtime_rate: Num
    #vehicle_excess_hour_rate: Num
    #vehicle_time_limit_penalty: Num

    # True iff any of the three duration INPUTS is nonzero.
    #duration_terms_active: bool
    #endregion

    # Problem data
    #depots: list[Depot]
    #customers: list[Customer]
    #capacity_per_vehicle: list[Num]

    #total_customer_capacity: Num
    #mean_customer_capacity: Num

    #min_vehicle_capacity: Num
    #max_vehicle_capacity: Num
    #mean_vehicle_capacity: Num
    #total_vehicle_capacity: Num

    #num_routes_lb: int

    #depot_route_starts: defaultdict[Depot, RouteSet]

    # Bumped by OperatorBL.apply/revert. A cheap guard against applying a Move that was
    # evaluate()'d against a since-mutated solution.
    # TODO: currently only bumped in OperatorBL.apply/revert. If a hazard ever shows up where
    # something mutates the solution between an evaluate() and its matching apply() outside of
    # that pair (e.g. a future multi-operator lookahead), bump this in the core mutators too
    # (insert_customer, pop_customer_at, swap_customers, permute, set_end_depot,
    # link_to_vehicle_*, unlink_from_vehicle, split_at, combine_with).
    version: int

    #neighbors: list[tuple[int, ...]]
    #neighbor_rank: list[dict[int, int]] = []
    #depot_neighbors: list[tuple[int, ...]]
    #customer_depots: list[tuple[int, ...]]

    def __init__(self):
        self.all_routes: RouteSet = RouteSet()
        self.vehicles: list[Vehicle] = []

        self.empty_routes: RouteSet = RouteSet()

        # Objective terms
        self.unit_travel_cost: Num = 0
        self.cost_per_vehicle: Num = 0
        self.cost_per_depot: Num = 0
        self.unit_overload_penalty: Num = 1000
        self.vehicle_overload_penalty: Num = 100000

        # Vehicle duration objective. Off: no duration accrues, so no band can be priced.
        self.travel_time_per_distance: Num = 0
        self.service_time_per_customer: Num = 0
        self.load_time_per_route: Num = 0
        self.overtime_threshold: Num = NO_TIME_LIMIT
        self.time_limit: Num = NO_TIME_LIMIT
        self.vehicle_hourly_rate: Num = 0
        self.vehicle_overtime_rate: Num = 0
        self.vehicle_excess_hour_rate: Num = 0
        self.vehicle_time_limit_penalty: Num = 0
        self.duration_terms_active: bool = False

        # Problem data
        self.depots: list[Depot] = []
        self.customers: list[Customer] = []
        self.capacity_per_vehicle: List[Num] = []

        self.total_customer_capacity: Num = 0
        self.mean_customer_capacity: Num = 0

        self.min_vehicle_capacity: Num = 1e100
        self.max_vehicle_capacity: Num = -1e100
        self.mean_vehicle_capacity: Num = 0
        self.total_vehicle_capacity: Num = 0

        self.num_routes_lb: int = -1

        self.depot_route_starts: defaultdict[Depot, RouteSet] = defaultdict[Depot, RouteSet](RouteSet)

        # Static geometry, built once by build_neighbor_tables(). Never maintained: customers and
        # depots do not move, so these survive every mutation and are shared by copies.
        self.neighbors: list[tuple[int, ...]] = []
        self.neighbor_rank: list[dict[int, int]] = []
        self.depot_neighbors: list[tuple[int, ...]] = []
        self.customer_depots: list[tuple[int, ...]] = []

        self.version: int = 0

    #region Data setters
    def set_customers(self, customers):
        self.customers = customers
        self.total_customer_capacity = sum(c.demand for c in self.customers)
        self.mean_customer_capacity = self.total_customer_capacity / len(self.customers)
        self._build_neighbor_tables_when_ready()

    def set_depots(self, depots):
        self.depots = depots
        self._build_neighbor_tables_when_ready()

    def _build_neighbor_tables_when_ready(self) -> None:
        """Two of the four tables span both node kinds, so wait until both lists have arrived."""
        if self.customers and self.depots:
            self.build_neighbor_tables()

    def build_neighbor_tables(self) -> None:
        """
        Precompute the four nearest-neighbor tables. Idempotent; call again to rebuild.

        `neighbors` and `neighbor_rank` are a linked pair and must be built in tandem -- the rank
        map is derived from the list so the two cannot drift.
        """
        _require_dense_ids(self.customers, "cID", "Customer")
        _require_dense_ids(self.depots, "dID", "Depot")

        customer_locations = _locations_array(self.customers)
        depot_locations = _locations_array(self.depots)

        self.neighbors = nearest_indices(customer_locations, customer_locations,
                                         CUSTOMER_NEIGHBORS_K, exclude_self=True)
        self.neighbor_rank = [{cid: rank for rank, cid in enumerate(row)} for row in self.neighbors]

        # Sized well below the full customer list: construction consumes one depot-nearest customer
        # per new route, so a row that is too short would be exhausted early. grow_depot_neighbors
        # doubles a row on exhaustion rather than dropping to a linear scan.
        depot_k = max(1, len(self.customers) // (len(self.depots) * 2))
        self.depot_neighbors = nearest_indices(depot_locations, customer_locations,
                                               depot_k, exclude_self=False)

        self.customer_depots = nearest_indices(customer_locations, depot_locations,
                                               CUSTOMER_DEPOTS_K, exclude_self=False)

    def grow_depot_neighbors(self, depot_id: int) -> bool:
        """
        Double one depot's customer row. Returns False when it already spans every customer.

        Called when a construction pass walks a row to its end. Rebuilding one row is cheap because
        depots are few, and it keeps the lookup O(1) afterwards instead of falling back to a scan.
        """
        current = len(self.depot_neighbors[depot_id])
        if current >= len(self.customers):
            return False

        wider = min(len(self.customers), max(1, current * 2))
        depot_location = _locations_array([self.depots[depot_id]])
        self.depot_neighbors[depot_id] = nearest_indices(
            depot_location, _locations_array(self.customers), wider, exclude_self=False)[0]
        return True

    def set_objectives(self, unit_travel_cost: Num = 0, cost_per_vehicle: Num = 0, cost_per_depot: Num = 0,
                       unit_overload_penalty: Num = 1000, vehicle_overload_penalty: Num = 100000):
        self.unit_travel_cost = unit_travel_cost
        self.cost_per_vehicle = cost_per_vehicle
        self.cost_per_depot = cost_per_depot
        self.unit_overload_penalty = unit_overload_penalty
        self.vehicle_overload_penalty = vehicle_overload_penalty

    def set_vehicle_duration_objectives(self,
                                        travel_time_per_distance: Num = 0,
                                        service_time_per_customer: Num = 0,
                                        load_time_per_route: Num = 0,
                                        overtime_threshold: Num = -1,
                                        time_limit: Num = -1,
                                        vehicle_hourly_rate: Num = -1,
                                        vehicle_overtime_rate: Num = -1,
                                        vehicle_excess_hour_rate: Num = -1,
                                        vehicle_time_limit_penalty: Num = -1) -> None:
        """
        Set every vehicle-duration constant. -1 means unspecified.

        EVERY CALL IS A FULL RESET, not a patch: an argument left out reverts to its unspecified
        meaning rather than keeping what a previous call set.

        See design/objective/objective_terms.md for the bands and how a default resolves.
        """
        self.travel_time_per_distance = travel_time_per_distance
        self.service_time_per_customer = service_time_per_customer
        self.load_time_per_route = load_time_per_route

        self.overtime_threshold = NO_TIME_LIMIT if overtime_threshold == -1 else overtime_threshold
        self.time_limit = NO_TIME_LIMIT if time_limit == -1 else time_limit
        # Only when BOTH are real: an unset overtime threshold means there is no overtime band.
        if self.overtime_threshold != NO_TIME_LIMIT and self.overtime_threshold > self.time_limit:
            raise ValueError(f"overtime_threshold ({self.overtime_threshold}) must not exceed "
                             f"time_limit ({self.time_limit}): overtime starts before the legal "
                             f"bound, never after it.")

        self.vehicle_hourly_rate = 0 if vehicle_hourly_rate == -1 else vehicle_hourly_rate
        self.vehicle_overtime_rate = 0 if vehicle_overtime_rate == -1 else vehicle_overtime_rate

        limit_is_set = self.time_limit != NO_TIME_LIMIT
        if vehicle_excess_hour_rate != -1:
            self.vehicle_excess_hour_rate = vehicle_excess_hour_rate
        elif limit_is_set:
            # Whichever rate the caller actually gave. Both zero leaves the excess band unpriced,
            # and the flat per-vehicle penalty below still fires.
            self.vehicle_excess_hour_rate = 10 * (self.vehicle_overtime_rate
                                                  or self.vehicle_hourly_rate)
        else:
            self.vehicle_excess_hour_rate = 0

        if vehicle_time_limit_penalty != -1:
            self.vehicle_time_limit_penalty = vehicle_time_limit_penalty
        else:
            self.vehicle_time_limit_penalty = 1000 if limit_is_set else 0

        self.duration_terms_active = bool(travel_time_per_distance or service_time_per_customer
                                          or load_time_per_route)

    def is_vehicle_duration_priced_or_limited(self):
        time_tracked = not (self.travel_time_per_distance == self.service_time_per_customer == self.load_time_per_route == 0)
        time_priced = self.vehicle_hourly_rate > 0
        overtime_priced = self.vehicle_overtime_rate > 0 and (self.overtime_threshold > 0 or self.time_limit > 0)
        time_limited =  self.time_limit > 0 and (self.vehicle_excess_hour_rate > 0 or self.vehicle_time_limit_penalty > 0)
        return time_tracked and (time_priced or overtime_priced or time_limited)

    def add_vehicle(self, vehicle: Vehicle):
        self.vehicles.append(vehicle)
        vehicle_capacity = vehicle.capacity

        self.total_vehicle_capacity += vehicle_capacity
        self.mean_vehicle_capacity = self.total_vehicle_capacity/len(self.vehicles)
        self.min_vehicle_capacity = min(self.min_vehicle_capacity, vehicle_capacity)
        self.max_vehicle_capacity = max(self.max_vehicle_capacity, vehicle_capacity)

        self.num_routes_lb = ceil(self.total_customer_capacity / self.max_vehicle_capacity)

    def remove_vehicle(self, vehicle):
        if vehicle.routes is not None:
            raise ValueError("Must reassign or delete a vehicle's routes before removing it.")

        self.vehicles.remove(vehicle)

        vehicle_capacity = vehicle.capacity
        self.total_vehicle_capacity -= vehicle_capacity
        self.mean_vehicle_capacity = self.total_vehicle_capacity/len(self.vehicles)

        # Warning: This update is expensive! Though removing vehicles doesn't help much with solve, so it shouldn't be used much.
        if len(self.vehicles) == 0:
            # No vehicles? No dice. Everything is awful!
            self.min_vehicle_capacity = 1e100
            self.max_vehicle_capacity = -1e100
            self.mean_vehicle_capacity = 0
            self.total_vehicle_capacity = 0

            self.num_routes_lb = -1
            return

        if vehicle_capacity == self.min_vehicle_capacity:
            # Re-derive min capacity from remaining vehicles
            self.min_vehicle_capacity = min(v.capacity for v in self.vehicles)
        if vehicle_capacity == self.max_vehicle_capacity:
            # Re-derive max capacity from remaining vehicles
            self.max_vehicle_capacity = max(v.capacity for v in self.vehicles)

        self.num_routes_lb = ceil(self.total_customer_capacity / self.max_vehicle_capacity)
    #endregion

    #region Delta computations (Just removing all empty routes for now)

    @staticmethod
    def cost_deltas_for_removing_empty_routes(routes: RouteSet) -> RawDeltaRecord:
        # Walks prev_route/next_route chains within the set of routes being removed, so adjacent
        # removals aren't double-counted, then accounts for each maximal chain's successor (if a
        # real Route) now starting where the chain started instead of where it ended.
        assert all(len(route.path) == 0 for route in routes)

        routes_remaining = routes.copy()
        num_routes = len(routes_remaining)
        if num_routes == 0:
            return RawDeltaRecord()

        travel_delta = 0
        travels: dict[Route, Num] = {}
        routes_to_remove = []
        raw_start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}
        raw_vehicles: dict[Route, tuple[Vehicle | None, Vehicle | None]] | Mapping = {}

        while num_routes > 0:
            first_in_sequence = routes_remaining[0]
            last_in_sequence = first_in_sequence

            predecessor = first_in_sequence.prev_route
            while predecessor in routes_remaining:
                assert isinstance(predecessor, Route)

                # Mark back-step to start of predecessor as distance no longer traveled, then slide backwards and mark predecessor for removal
                # An empty assigned route measures exactly its own start-to-end arc, so losing
                # that arc IS the whole of its distance going to zero.
                own = predecessor.first_move_distance()
                travel_delta -= own
                if own:
                    travels[predecessor] = travels.get(predecessor, 0) - own
                routes_to_remove.append(predecessor)

                first_in_sequence = predecessor
                predecessor = first_in_sequence.prev_route

            successor = last_in_sequence.next_route
            while successor in routes_remaining:
                assert isinstance(successor, Route)

                # Mark forward-step to start of successor as distance no longer traveled, then slide forwards and mark last_in_sequence for removal
                own = last_in_sequence.first_move_distance()
                travel_delta -= own
                if own:
                    travels[last_in_sequence] = travels.get(last_in_sequence, 0) - own
                routes_to_remove.append(last_in_sequence)

                last_in_sequence = successor
                successor = last_in_sequence.next_route # type: ignore - successor in routes_remaining implies... it's a Route

            # Here: last_in_sequence is the last route in the chain contained in remaining_routes. But: its move hasn't yet been counted!
            own = last_in_sequence.first_move_distance()
            travel_delta -= own
            if own:
                travels[last_in_sequence] = travels.get(last_in_sequence, 0) - own
            routes_to_remove.append(last_in_sequence)

            # The chain's successor (if a real Route, not a LastRoute sentinel) now starts where
            # the chain started, instead of where the chain ended.
            if isinstance(successor, Route):
                chain_start_depot = first_in_sequence.start_depot
                successor_travel = successor.first_visit.start_travel_delta_if_depot_swapped(
                    chain_start_depot)
                travel_delta += successor_travel
                if successor_travel:
                    travels[successor] = travels.get(successor, 0) + successor_travel

                successor_start = successor.start_depot
                if successor.is_active and successor_start != chain_start_depot and successor not in routes_to_remove:
                    assert isinstance(raw_start_depots, dict)
                    raw_start_depots[successor] = (successor.start_depot, chain_start_depot)

            # Record entries for this chain BEFORE routes_to_remove is cleared below. Every route
            # here is empty by precondition, so load and count are 0 on both sides; the transition
            # that matters is the unlink, which restores a fresh VirtualDepot and drops the vehicle.
            for removed in routes_to_remove:
                # Safeguard: This method is for EMPTY routes only - see method title.
                # Depot use count doesn't budge: Route is empty and is about to be unassigned too, so state change is inactive->inactive
                assert not len(removed.path) > 0 and isinstance(raw_vehicles, dict)
                raw_vehicles[removed] = (removed.vehicle, None)

            # Remove the routes
            routes_remaining.difference_update(routes_to_remove)
            num_routes = len(routes_remaining)
            routes_to_remove.clear()

        if not raw_start_depots:
            raw_start_depots = NO_CHANGES
        if not raw_vehicles:
            raw_vehicles = NO_CHANGES

        return RawDeltaRecord(
            travel_changes={r: d for r, d in travels.items() if d} or NO_CHANGES,
            start_depot_changes=raw_start_depots,
            vehicle_changes=raw_vehicles)

    #endregion

    #region Route operations
    def choose_random_nonempty_route(self) -> Route|None:
        # Leaves all_routes PERMUTED when it passes over empty routes: remove() is swap-with-last
        # and update() appends, so set-aside routes come back at the end rather than where they
        # were. Harmless for callers that only need a route; see
        # choose_random_nonempty_route_ordered() for callers that must not disturb draw order.
        new_empty_routes = RouteSet()
        all_routes = self.all_routes

        num_routes = len(all_routes)

        while num_routes > 0:
            route = all_routes.choose_random()
            if route.is_empty:
                num_routes -= 1
                all_routes.remove(route)
                new_empty_routes.add(route)
            else:
                # Add empty routes back in, and to empty route tracker
                all_routes.update(new_empty_routes)
                self.empty_routes.update(new_empty_routes)
                return route

        # No non-empty route found. The solution died. Utterly dead. Decimated. Destroyed. Desolate. Disintegrated. Diabolically dismantled.
        # All routes are agon and in empty_routes. But we don't care. We will crash and burn.
        return None

    def readd_set_aside_routes(self, routes_to_readd: list[tuple[Route, int]]) -> None:
        """
        Undo a sequence of all_routes.remove() calls, restoring positions EXACTLY.

        Each entry is (route, swap_index) as remove() returned it. Unwound LIFO, because a swap
        index is relative to the RouteSet state at the moment of its own removal.

        A method rather than a closure inside the caller: a nested def allocates a new function
        object on every call, on a path that runs once per proposal.
        """
        all_routes = self.all_routes
        for route, swap_index in reversed(routes_to_readd):
            all_routes.undo_remove(route, swap_index)
            self.empty_routes.add(route)

    def choose_random_nonempty_route_ordered(self) -> Route|None:
        """
        As choose_random_nonempty_route, but leaves all_routes in exactly the order it found it.

        Separate method on purpose. Most operators do not care where a set-aside empty route lands,
        and making them pay for undo_remove bookkeeping they will never read would be a tax on the
        common path. Callers that DO care are the ones whose revert is checked for exact structural
        round-trip: operands are drawn POSITIONALLY via rand_choice, so a permuted RouteSet changes
        which route a later draw returns. Selection alone then diverts the search while leaving
        cost, vehicle chains and depot membership perfectly intact -- correct by every value check
        and still wrong.
        """
        set_aside: list[tuple[Route, int]] = []
        all_routes = self.all_routes
        num_routes = len(all_routes)

        while num_routes > 0:
            route = all_routes.choose_random()
            if route.is_empty:
                num_routes -= 1
                set_aside.append((route, all_routes.remove(route)))
            else:
                self.readd_set_aside_routes(set_aside)
                return route

        # Nothing non-empty exists, but the RouteSet still comes back intact -- a caller handling
        # None must not be handed a mutated solution as a side effect.
        self.readd_set_aside_routes(set_aside)
        return None

    def choose_random_route_insertion_destination(self) -> Route | LastRoute | None:
        # Choose a random route OR last_route for a vehicle
        vehicles = self.vehicles
        num_vehicles = len(vehicles)
        if num_vehicles == 0:
            # WE HAVE NO VEHICLES WE'RE ALL GONNA DIE
            return None

        all_routes = self.all_routes
        num_routes = len(all_routes)

        # Not going to pick strictly the corresponding index per vehicle, unless is the end: vehicle.route[2] isn't the third in the route, but an arbitrary entry in vehicle.
        unassigned_routes: RouteSet | None = None
        num_options = num_vehicles + num_routes

        empty_routes = self.empty_routes

        while True:
            # >=1 vehicle so eventually num_routes=0, num_options>0, and a vehicle's end is selected.
            idx = rand_index(num_options)
            if idx >= num_routes:
                route = vehicles[idx-num_routes].last_route
                break
            else:
                route = all_routes[idx]
                if route.is_assigned:
                    break
                else:
                    unassigned_routes = RouteSet() if unassigned_routes is None else unassigned_routes
                    assert isinstance(unassigned_routes, RouteSet) # Linter is dumb hurr durr
                    unassigned_routes.add(route)

                    if route.is_empty:
                        empty_routes.add(route)
                    all_routes.remove(route)
                    num_routes -= 1
                    num_options -= 1

        if unassigned_routes:
            all_routes.update(unassigned_routes)
        return route
        


    @property
    def has_empty_routes(self):
        return len(self.empty_routes)>0

    def remove_routes(self, routes: Collection[Route]):
        for route in routes:
            route.dispose()
        self.all_routes.difference_update(routes)

    def remove_trivial_routes(self):
        self.remove_routes([route for route in self.all_routes if route.is_trivial])

    def remove_empty_routes(self):
        self.remove_routes([route for route in self.all_routes if route.is_empty])

    def add_route_to_vehicle(self, route: Route, vehicle: Vehicle):
        # We assume vehicle is in self.vehicles already.
        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        vehicle.append_route(route)
        self.all_routes.add(route)

    def add_route_to_vehicle_with_id(self, route: Route, vehicle_id: int):
        if vehicle_id >= len(self.vehicles) or vehicle_id < 0:
            raise ValueError("vehicle_id out of range")

        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        vehicle = self.vehicles[vehicle_id]
        vehicle.append_route(route)
        self.all_routes.add(route)

    #endregion

    #region Accounting application
    def initialize_accounting(self) -> None:
        """
        Build every derived cache directly from the structure, before anything reads the objective.
        Idempotent: every write is an absolute value recomputed from the structure, never a delta.

        See design/raw_delta_accounting/tracking_for_cached_accounting.md.
        """
        # Loads first. The vehicle counters below read route.is_overloaded, which reads
        # current_load, so this ordering is required rather than stylistic.
        for route in self.all_routes:
            route.current_load = route.recompute_current_load()
            route.current_travel = route.recompute_current_travel()

        # depot_usage_breakdown() is the oracle's own definition of which routes start where, so
        # the build path and the check that grades it cannot disagree. __copy__ rebuilds it the
        # same way, for the same reason.
        self.depot_route_starts = self.depot_usage_breakdown()

        for vehicle in self.vehicles:
            # Reads route.current_travel, so it has to follow the route loop above.
            vehicle.current_travel = sum(route.current_travel for route in vehicle.routes)
            vehicle.num_customers = sum(route.num_customers for route in vehicle.routes)
            vehicle.num_routes_with_customers = sum(route.num_customers > 0
                                                    for route in vehicle.routes)
            vehicle.num_routes_overloaded = sum(route.is_overloaded for route in vehicle.routes)

    def apply_accounting(self, record: AccountingRecord):
        """
        Write one resolved accounting record. The only place a derived cache is written, and it
        decides nothing: assignment and arithmetic over numbers the processor already resolved.

        See design/raw_delta_accounting/accounting_record.md.
        """

        # Unpack the record
        vehicle_delta_routes_overloaded, vehicle_delta_active_routes, vehicle_delta_num_customers,\
            vehicle_delta_travel, route_loads, route_delta_travel, start_depot_changes = record

        # Update vehicle route overload counts
        if vehicle_delta_routes_overloaded != NO_CHANGES:
            for (vehicle, route_overloaded_delta) in vehicle_delta_routes_overloaded.items():
                vehicle.num_routes_overloaded += route_overloaded_delta

        if vehicle_delta_active_routes != NO_CHANGES:
            for (vehicle, delta_active_routes) in vehicle_delta_active_routes.items():
                vehicle.num_routes_with_customers += delta_active_routes

        if vehicle_delta_num_customers != NO_CHANGES:
            for (vehicle, delta_num_customers) in vehicle_delta_num_customers.items():
                vehicle.num_customers += delta_num_customers

        if vehicle_delta_travel != NO_CHANGES:
            for (vehicle, delta_travel) in vehicle_delta_travel.items():
                vehicle.current_travel += delta_travel

        if route_loads != NO_CHANGES:
            for route, (_, final_load) in route_loads.items():
                route.current_load = final_load

        # Travel is a plain delta on both levels: adding on apply and subtracting on revert is the
        # whole of it, because distance has no threshold of its own for the processor to resolve.
        if route_delta_travel != NO_CHANGES:
            for route, delta_travel in route_delta_travel.items():
                route.current_travel += delta_travel

        depot_starts = self.depot_route_starts
        if start_depot_changes != NO_CHANGES:
            for route, (init_depot, final_depot) in start_depot_changes.items():
                # Could pre-aggregate by depot to save internal self calls, but:
                # Would either create a new set/list (defeats the point of aggregation),
                # Or (via iterable) searches the whole changeset per depot (bad complexity)
                if init_depot is not VIRTUAL_DEPOT:
                    depot_starts[init_depot].remove(route)
                if final_depot is not VIRTUAL_DEPOT:
                    depot_starts[final_depot].add(route)

    #endregion

    #region Objective computations
    def vehicles_used(self) -> int:
        return sum(vehicle.is_active for vehicle in self.vehicles)

    def depots_used(self) -> int:
        return sum(len(self.depot_route_starts[depot]) >= 1 for depot in self.depots)

    def recompute_depots_used(self) -> int:
        return len(set(route.start_depot for route in self.all_routes if route.is_active))

    def depot_usage_breakdown(self) -> defaultdict[Depot, RouteSet]:
        """Ground truth for depot_route_starts: which ACTIVE routes start at each depot.

        Also used by __copy__ to rebuild the map rather than remap identities, so the copy path
        and the oracle share one definition of "which routes start where" and cannot drift."""
        usage = defaultdict[Depot, RouteSet](RouteSet)
        for route in self.all_routes:
            if route.is_active:
                usage[route.start_depot].add(route)
        return usage

    def total_path_len(self) -> Num:
        return sum(route.total_distance() for route in self.all_routes)

    def num_overloaded_routes(self) -> int:
        return sum(route.is_overloaded for route in self.all_routes)

    def num_overloaded_vehicles(self) -> int:
        return sum(vehicle.has_overloaded_route for vehicle in self.vehicles)

    def total_overload(self):
        return sum(route.amount_overloaded for route in self.all_routes)

    #region Vehicle duration
    def vehicle_duration(self, vehicle: Vehicle) -> Num:
        """One vehicle's accrued hours, from its three SINK-WRITTEN caches.

        All three are sink-written, so they still hold the pre-mutation value when an operator
        priced by mutating. recompute_vehicle_duration is the twin that walks the structure.
        """
        return (self.travel_time_per_distance * vehicle.current_travel +
                self.service_time_per_customer * vehicle.num_customers +
                self.load_time_per_route * vehicle.num_routes_with_customers)

    def recompute_vehicle_duration(self, vehicle: Vehicle) -> Num:
        """Ground truth for vehicle_duration: the same three inputs, walked from the structure.

        Shares NO cache with vehicle_duration, so a stale cache cannot hide behind it.
        """
        routes = vehicle.routes
        return (self.travel_time_per_distance * sum(route.total_distance() for route in routes) +
                self.service_time_per_customer * sum(route.num_customers for route in routes) +
                self.load_time_per_route * sum(route.num_customers > 0 for route in routes))

    def duration_bands(self, duration: Num) -> tuple[Num, Num, Num, int]:
        """Cut one vehicle's duration into the four priced quantities.

        THE SINGLE DEFINITION OF THE BANDS, shared by the processor's prediction and
        objective_terms()' measurement so the two cannot drift apart. See
        design/objective/objective_terms.md.

        Every branch below degrades correctly at an unset NO_TIME_LIMIT threshold: min(t, inf) is
        t, max(0, t - inf) is 0, and t > inf is False.
        """
        overtime_threshold = self.overtime_threshold
        time_limit = self.time_limit
        regular = duration if duration < overtime_threshold else overtime_threshold
        overtime = duration - overtime_threshold if duration > overtime_threshold else 0
        excess = duration - time_limit if duration > time_limit else 0
        return regular, overtime, excess, duration > time_limit

    def vehicle_duration_terms(self) -> tuple[Num, Num, Num, int]:
        """The four duration quantities summed over every vehicle, measured from the structure."""
        if not self.duration_terms_active:
            return 0, 0, 0, 0

        regular_total: Num = 0
        overtime_total: Num = 0
        excess_total: Num = 0
        over_limit_total: int = 0
        for vehicle in self.vehicles:
            regular, overtime, excess, over_limit = self.duration_bands(
                self.recompute_vehicle_duration(vehicle))
            regular_total += regular
            overtime_total += overtime
            excess_total += excess
            over_limit_total += over_limit
        return regular_total, overtime_total, excess_total, over_limit_total
    #endregion

    def solution_cost(self):
        regular_hours, overtime_hours, excess_hours, over_limit = self.vehicle_duration_terms()
        return (self.cost_per_vehicle * self.vehicles_used() +
                self.cost_per_depot * self.depots_used() +
                self.unit_travel_cost * self.total_path_len() +
                self.unit_overload_penalty * self.total_overload() +
                self.vehicle_overload_penalty * self.num_overloaded_vehicles() +
                self.vehicle_hourly_rate * regular_hours +
                self.vehicle_overtime_rate * overtime_hours +
                self.vehicle_excess_hour_rate * excess_hours +
                self.vehicle_time_limit_penalty * over_limit)

    def objective_terms(self) -> ObjectiveTermDelta:
        # Absolute totals in the same 5-field shape as ObjectiveTermDelta, so deltas can be
        # checked against ground truth by diffing two calls to this. Also the measurement
        # available to operators that set _evaluates_by_applying because they can't price a move
        # without performing it.
        regular_hours, overtime_hours, excess_hours, over_limit = self.vehicle_duration_terms()
        return ObjectiveTermDelta(
            travel_distance=self.total_path_len(), vehicles_activated=self.vehicles_used(),
            depots_activated=self.depots_used(), total_route_overload=self.total_overload(),
            vehicles_overloaded=self.num_overloaded_vehicles(),
            vehicle_regular_hours=regular_hours, vehicle_overtime_hours=overtime_hours,
            vehicle_excess_hours=excess_hours, vehicles_over_time_limit=over_limit)
    #endregion

    def __copy__(self):
        # No fancy inheritance version for now. Plain and simple.
        new_sln = FullSolution.__new__(FullSolution)

        # Core solution data
        # Copy vehicles, including their routes.
        new_sln.vehicles = [copy.copy(vehicle) for vehicle in self.vehicles]
        new_sln.all_routes = RouteSet(from_iterable((vehicle.routes for vehicle in new_sln.vehicles)))

        # Copy unassigned routes
        unassigned_routes = {copy.copy(route) for route in self.all_routes if not route.is_assigned}
        new_sln.all_routes.update(unassigned_routes)

        # Copy Objective terms
        new_sln.unit_travel_cost = self.unit_travel_cost
        new_sln.cost_per_vehicle = self.cost_per_vehicle
        new_sln.cost_per_depot = self.cost_per_depot
        new_sln.unit_overload_penalty = self.unit_overload_penalty
        new_sln.vehicle_overload_penalty = self.vehicle_overload_penalty

        # Vehicle duration objective. Plain constants, taken by value.
        new_sln.travel_time_per_distance = self.travel_time_per_distance
        new_sln.service_time_per_customer = self.service_time_per_customer
        new_sln.load_time_per_route = self.load_time_per_route
        new_sln.overtime_threshold = self.overtime_threshold
        new_sln.time_limit = self.time_limit
        new_sln.vehicle_hourly_rate = self.vehicle_hourly_rate
        new_sln.vehicle_overtime_rate = self.vehicle_overtime_rate
        new_sln.vehicle_excess_hour_rate = self.vehicle_excess_hour_rate
        new_sln.vehicle_time_limit_penalty = self.vehicle_time_limit_penalty
        new_sln.duration_terms_active = self.duration_terms_active

        # Copy problem data
        new_sln.depots = self.depots
        new_sln.customers = self.customers
        new_sln.capacity_per_vehicle = self.capacity_per_vehicle

        # Neighbor tables are static geometry over the shared customer and depot lists, so a copy
        # shares them by reference exactly as it shares those lists. Nothing mutates them except
        # grow_depot_neighbors, which only ever widens a row with more of the same answer.
        new_sln.neighbors = self.neighbors
        new_sln.neighbor_rank = self.neighbor_rank
        new_sln.depot_neighbors = self.depot_neighbors
        new_sln.customer_depots = self.customer_depots

        # Copy calculations derived from core solution and problem data
        new_sln.total_customer_capacity = self.total_customer_capacity
        new_sln.mean_customer_capacity = self.mean_customer_capacity

        new_sln.min_vehicle_capacity = self.min_vehicle_capacity
        new_sln.max_vehicle_capacity = self.max_vehicle_capacity
        new_sln.mean_vehicle_capacity = self.mean_vehicle_capacity
        new_sln.total_vehicle_capacity = self.total_vehicle_capacity

        new_sln.num_routes_lb = self.num_routes_lb

        # REBUILT, not copied: a RouteSet stores route identity, and every route here is a new
        # object. Rebuilding over the copies is O(routes) -- the same cost as threading an
        # old-to-new mapping through the copy loops, and it reuses the oracle's own definition.

        # __new__ bypasses __init__, so EVERY field must be set explicitly here -- there are no
        # class-level defaults to fall back on any more. These two are easy to forget:
        new_sln.empty_routes = RouteSet(route for route in new_sln.all_routes if route.is_empty)
        # version numbers a state within ONE solution's own history, so a copy starts a new
        # branch at 0 rather than inheriting the parent's count. A Move evaluated against the
        # original is meaningless here anyway -- it names route objects this copy doesn't own.
        #
        # This is what makes a copy a genuine BRANCH ROOT rather than just a backup: it owns its
        # whole object graph and its own version line, so it can be solved forward independently.
        # TODO(parallel-solve): with that plus a per-branch undo stack (see OperatorBL.commit),
        # snapshots become the natural unit of work for a parallel/portfolio solver -- fan out
        # from the retained top-k snapshots, solve each branch, keep the best. Nothing ties a
        # branch to THIS solver either: because a branch is just a self-contained FullSolution,
        # each one can be driven by a different approach (a different operator roster or cooling
        # schedule, a ruin-and-recreate pass, or an exact method on a sub-problem) and the
        # portfolio compared on the objective they all share.
        new_sln.version = 0

        # Rebuild depot_route_starts over the COPIED routes, then re-link. A RouteSet stores
        # route identity and every route here is a new object, so copying the map would leave it
        # pointing at the original's routes. depot_usage_breakdown() is the oracle's own
        # definition of which routes start where, so using it here means the copy path and the
        # check can never disagree.
        new_sln.depot_route_starts = new_sln.depot_usage_breakdown()

        return new_sln


    def take_snapshot(self, obj: Num | None):
        # copy.copy invokes FullSolution.__copy__, which is much cheaper than deepcopy for a
        # solution of any real size. Only safe now that the Vehicle.__copy__ linkage bug is fixed
        # (see Phase 0) -- before that fix, copies had corrupted prev_route backlinks.
        obj = obj if obj is not None else self.solution_cost()
        snapshot = copy.copy(self)
        return obj, snapshot

    def __str__(self) -> str:
        return '\n'.join(str(vehicle) for vehicle in self.vehicles)

    def __repr__(self):
        return str(self)
