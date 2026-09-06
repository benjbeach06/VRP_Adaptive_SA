"""
Vehicle: an ordered chain of routes, bracketed by a FirstRoute and a LastRoute sentinel.

A vehicle does not run one loop out of one depot. It runs a SEQUENCE of routes across depots, each
beginning where the previous one ended. That chain is what this class owns, together with the
cached per-vehicle aggregates the objective reads: travel, customer count, active-route count and
overloaded-route count.

Those caches are written ONLY through apply_counter_change, driven by the accounting sink on
FullSolution. Nothing else in the model may touch them.
"""
import copy
from typing import TYPE_CHECKING

from .basics import Num
from .nodes import Depot
from .route_set import RouteSet
from .routes import FirstRoute, LastRoute, Route

if TYPE_CHECKING:
    from .solution import FullSolution

class Vehicle:
    __slots__ = "vID", "initial_depot", "capacity", "routes", "num_routes_overloaded", "current_travel",\
                "num_routes_with_customers", "num_customers", "first_route", "last_route"

    # Unique vehicle id
    #vID: int

    # Start depot for src_route
    #initial_depot: Depot

    # Demand serviceable by vehicle on one src_route
    #capacity: Num

    # Vehicle's part of core solution: RouteSet of routes
    # RouteSet choice: We never really care about "add/remove third src_route", only "add/remove src_route from vehicle, before/after target src_route, or at start/end"
    # RouteSet still lets us pick random routes from the vehicle, so that's all we really need. Routes maintain linkages.
    #routes: RouteSet

    # Number of overloaded routes, carrying too much supply.
    #num_routes_overloaded: int

    # Number of nonempty (active) routes. (NOTE: active routes can still be nontrivial! Another op will be required to deactivate them.)
    #num_routes_with_customers: int

    # Total number of customers. A vehicle is active iff it serves customers.
    #num_customers: int

    # Sink-written cache of get_total_distance(), which stays as the recompute twin. The processor
    # aggregates the per-route travel deltas into this; no mutator touches it.
    #current_travel: Num

    # First and last routes (head and tail)
    #first_route: FirstRoute
    #last_route: LastRoute

    # Currently does not access num_depot_uses, so we skip.

    def __init__(self, i=0, initial_depot: Depot=Depot(), capacity = -1): # type:ignore
        self.vID: int = i # data
        self.initial_depot: Depot = initial_depot # type:ignore # data
        self.capacity: Num = capacity # data
        self.routes: RouteSet = RouteSet() # Core decision for the vehicle

        # Running counters, maintained incrementally by register_*_change_in_vehicle
        self.num_routes_overloaded: int = 0
        self.num_routes_with_customers: int = 0
        self.num_customers: int = 0
        self.current_travel: Num = 0

        first_route = FirstRoute(initial_depot)
        last_route = LastRoute(first_route)

        self.first_route: FirstRoute = first_route
        self.last_route: LastRoute = last_route

        first_route.vehicle = self
        last_route.vehicle = self

        last_route._link_after(first_route)

    #region Core state-tracking properties
    @property
    def num_routes(self) -> int:
        return len(self.routes)

    @property
    def is_empty(self) -> bool:
        return self.num_routes == 0

    @property
    def is_active(self) -> bool:
        return self.num_customers > 0

    @property
    def is_inactive(self) -> bool:
        return self.num_customers == 0

    @property
    def final_depot(self) -> Depot:
        # last_route.start_depot always tracks the vehicle's current end position,
        # whether or not any real routes have been added yet -- avoids relying on
        # RouteSet order, which isn't meaningful.
        return self.last_route.start_depot

    @property
    def has_overloaded_route(self) -> bool:
        return self.num_routes_overloaded > 0

    def apply_counter_change(self, routes_overloaded: int, routes_with_customers: int,
                             num_customers: int) -> None:
        """Write already-resolved deltas to this vehicle's cached counters.

        Reached only through FullSolution.apply_accounting. It decides nothing -- every argument
        arrives resolved, so there is no threshold to compare against here.
        """
        self.num_routes_overloaded += routes_overloaded
        self.num_routes_with_customers += routes_with_customers
        self.num_customers += num_customers
    #endregion

    #region Index-safe src_route and depot getters
    def route_at(self, i: int) -> Route | None:
        # Index-safe src_route getter. Index out of bounds returns None 0 no src_route there yet.
        routes = self.routes
        if i >= len(routes) or i <= -1:
            # Past end of path or before its beginning; return None to signify none exists
            return None

        return routes[i]

    def get_start_depot_at(self, i: int) -> Depot:
        # Index-safe start-depot getter. Returns start or end depot for vehicle if index is out of bounds.
        routes = self.routes

        if i <= 0:
            # Vehicle start point!
            return self.initial_depot

        if i >= len(routes):
            # Past vehicle end.
            # Return last depot
            return self.final_depot

        # If we're here, vID is in range
        return routes[i].start_depot

    def get_end_depot_at(self, i: int) -> Depot:
        return self.get_start_depot_at(i-1)
    #endregion

    #region Object operations

    #region Route operations
    # NOTE: Routes know how to fully link to, and unlink from, their vehicles.
    def prepend_route(self, route: Route):
        route.link_to_vehicle_after(self.first_route)

    def append_route(self, route: Route):
        route.link_to_vehicle_before(self.last_route)

    def insert_route_before(self, src_route: Route, dest_route: Route):
        if dest_route.vehicle is not self:
            raise ValueError("dest_route not assigned to current vehicle.")

        src_route.link_to_vehicle_before(dest_route)

    def insert_route_after(self, src_route: Route, dest_route: Route):
        if dest_route.vehicle is not self:
            raise ValueError("dest_route not assigned to current vehicle.")

        src_route.link_to_vehicle_after(dest_route)

    def remove_route(self, route: Route):
        if route.vehicle is not self:
            raise ValueError("route not assigned to current vehicle.")

        # Here, the src_route is unassigned - but its data still exists.
        route.unlink_from_vehicle()
    #endregion

    #region Split and combine routes
    def split_route(self, route: Route, split_index: int, refill_depot: Depot, new_route: Route | None = None) -> Route:
        if route.vehicle is not self:
            raise ValueError("route not assigned to current vehicle.")

        return route.split_at(split_index, refill_depot, new_route)

    #endregion

    def __copy__(self):
        new_vehicle = Vehicle.__new__(Vehicle)

        #region Invariant data
        new_vehicle.vID = self.vID
        new_vehicle.initial_depot = self.initial_depot
        new_vehicle.capacity = self.capacity
        #endregion

        #region Core solution

        #region First and last src_route
        first_route = self.first_route
        last_route = self.last_route

        new_first_route = copy.copy(first_route)
        new_last_route = copy.copy(last_route)

        new_vehicle.first_route = new_first_route
        new_vehicle.last_route = new_last_route
        new_first_route.vehicle = new_vehicle
        new_last_route.vehicle = new_vehicle
        #endregion

        #region Routes list: traverse list, copying and linking relevant data as we go

        new_routes = RouteSet()
        new_vehicle.routes = new_routes

        curr_route = first_route
        new_curr_route = new_first_route

        for i in range(self.num_routes):
            # Copy all the routes and link them to prev
            next_route: Route = curr_route.next_route # type: ignore - first num_routes next_route links are... Routes.
            new_next_route = copy.copy(next_route)

            new_next_route.vehicle = new_vehicle

            # Link without messing with start or end depot: these were copied via dest_route copy operators!
            #   Via FirstVisit and LastVisit copies for routes, and via self copy for FirstRoute and LastRoute
            new_curr_route.next_route = new_next_route
            new_next_route.prev_route = new_curr_route

            # Add src_route
            new_routes.add(new_next_route)

            # Update current routes
            curr_route = next_route
            new_curr_route = new_next_route

        new_curr_route.next_route = new_last_route
        new_last_route.prev_route = new_curr_route

        #endregion

        #endregion

        #region Objective-related and state tracking
        new_vehicle.num_routes_overloaded = self.num_routes_overloaded
        new_vehicle.num_routes_with_customers = self.num_routes_with_customers
        new_vehicle.num_customers = self.num_customers
        new_vehicle.current_travel = self.current_travel
        #endregion

        return new_vehicle

    def __str__(self):
        curr_route = self.first_route
        str_reps = [str(curr_route.end_depot)]
        curr_route = curr_route.next_route

        while isinstance(curr_route, Route):
            route_rep = '->'.join(str(customer) for customer in curr_route.path) + '->' + str(curr_route.end_depot)
            str_reps.append(route_rep)
            curr_route = curr_route.next_route

        return '->'.join(str_reps)

    def __repr__(self):
        return str(self)

    #endregion

    #region postprocessing
    # Compute total distance traversed by vehicle (postprocessing only)
    def get_total_distance(self):
        if self.num_routes == 0:
            return 0

        return sum(route.total_distance() for route in self.routes)
    #endregion
