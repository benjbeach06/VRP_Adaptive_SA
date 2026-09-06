"""
Route, and the two sentinels that bracket a vehicle's chain of routes.

  VehicleNode -- abstract base: owns `vehicle`, `prev_route`, `next_route`
  FirstRoute  -- head sentinel; carries the depot the vehicle starts its day at
  LastRoute   -- tail sentinel; carries the depot the vehicle finishes at
  Route       -- a real route: a start depot, a doubly-linked path of CustomerVisits, an end depot

Route is the largest object in the model, and it carries two distinct halves. The `travel_delta_*`
and `cost_deltas_*` methods PRICE a mutation in O(1) from the arcs at its boundary and mutate
nothing. Everything below `#region Basic object operations` APPLIES one. Every operator move is
one of the first followed by one of the second.

Pricing returns a RawDeltaRecord and writes no accounting state whatsoever. That contract is what
this module exists to hold; see design/raw_delta_accounting/.
"""
import copy
from abc import ABC
from typing import TYPE_CHECKING, Mapping, Sequence

from .basics import Chain, Num, as_chain_range
from .nodes import VIRTUAL_DEPOT, Customer, Depot, Node, VirtualDepot
from .records import NO_CHANGES, RawDeltaRecord
from .visits import (CustomerLike, CustomerVisit, DepotLike, FirstRouteVisit, LastRouteVisit,
                     NextRouteKind, RouteVisit)

if TYPE_CHECKING:
    from .vehicle import Vehicle

# region Route-like objects, including start-route and end-route
class VehicleNode(ABC):
    # Annotations only -- each concrete subclass initializes these in its own __init__.
    # VehicleNode has no __init__ of its own (subclasses don't chain to one), so defaults here
    # would be shared class state rather than per-instance.
    __slots__ = "vehicle", "prev_route", "next_route"
    vehicle: Vehicle | None

    prev_route: VehicleNode | None
    next_route: VehicleNode | None
    # Only field guarantees are vehicle, prev_route, and next_route.

    def is_adjacent_with(self, other: Route | None):
        return other is not None and other == self.prev_route or other == self.next_route

    @staticmethod
    def link(node1: FirstRoute | Route, node2: Route | LastRoute):
        node1.next_route = node2
        node2.prev_route = node1

    #region type-checkers
    @property
    def is_route(self):
        return isinstance(self, Route)

    @property
    def is_first_route(self):
        return isinstance(self, FirstRoute)

    @property
    def is_last_route(self):
        return isinstance(self, LastRoute)

    def is_virtual(self):
        return not self.is_route
    #endregion


class FirstRoute(VehicleNode):
    __slots__ = "end_depot"
    # First src_route is the start of a vehicle's path, and an "end" to the virtual src_route preceding the vehicle's path
    prev_route: None    # always None: nothing precedes the head sentinel
    next_route: Route | LastRoute

    end_depot: Depot

    def __init__(self, depot: Depot):
        self.end_depot = depot

        self.vehicle = None      # set by Vehicle.__init__/__copy__
        self.prev_route = None   # structurally always None
        self.next_route = None   # type: ignore # immediately overwritten by LastRoute._link_after

    def __copy__(self):
        new_route = FirstRoute.__new__(FirstRoute)

        new_route.end_depot = self.end_depot
        # __new__ bypasses __init__: no class-level defaults remain, so set these explicitly.
        new_route.vehicle = None      # reassigned by Vehicle.__copy__
        new_route.prev_route = None
        new_route.next_route = None   # type: ignore # relinked by Vehicle.__copy__

        return new_route

    # Routes cannot set end_depot directly, (have to go through last_visit), so this redirector is useful.
    def set_end_depot(self, new_depot: Depot):
        self.end_depot = new_depot


class LastRoute(VehicleNode):
    __slots__ = "start_depot"
    # Last src_route is the end of a vehicle's path, and a "start" to the virtual src_route succeeding the vehicle's path
    prev_route: FirstRoute | Route
    next_route: None    # always None: nothing follows the tail sentinel

    start_depot: Depot

    def __init__(self, prev_route: FirstRoute | Route):
        self.vehicle = None      # set by Vehicle.__init__/__copy__
        self.next_route = None   # structurally always None

        self._link_after(prev_route)   # sets self.prev_route and start_depot

    # We use only _link_after and not _link_before: Anytime a src_route links to a prior src_route, it inherits its start depot
    def _link_after(self, route: FirstRoute | Route):
        # Since depot is an
        self.prev_route = route
        route.next_route = self

        self.start_depot = route.end_depot

    def __copy__(self):
        new_route = LastRoute.__new__(LastRoute)

        new_route.start_depot = self.start_depot
        # __new__ bypasses __init__: no class-level defaults remain, so set these explicitly.
        new_route.vehicle = None       # reassigned by Vehicle.__copy__
        new_route.prev_route = None    # type: ignore # relinked by Vehicle.__copy__
        new_route.next_route = None

        return new_route

    # Routes cannot set start_depot directly (have to go through first_visit), so this redirector is useful.
    def set_start_depot(self, new_depot: Depot):
        self.start_depot = new_depot


class Route(VehicleNode):
    __slots__ = ("path", "first_visit", "last_visit", "current_load", "current_travel")

    # NOTE: Equality and hashing are identity-based to ensure performance in sets/lists, and to
    #   guarantee stability despite field mutability. Uniqueness is managed externally.

    # NOTE 2: All src_route-based operators herein assume you don't operate with empty routes - except for removing them from their vehicle!
    #   Thus: If combining with a src_route, or inserting self in a list, etc: we
    #   assume the moving src_route is nonempty. This simplifies the logic quite a bit in some places.
    #   HOWEVER: To ensure dynamic initial src_route building still works: we allow adding customers to an empty src_route

    # List choice: We will often want to swap a customer range or permute customers, requiring a fixed-order data structure.
    path: list[CustomerVisit]
    vehicle: Vehicle | None
    first_visit: FirstRouteVisit
    last_visit: LastRouteVisit

    prev_route: Route | FirstRoute | None # None iff unassigned
    next_route: Route | LastRoute  | None # None iff unassigned
    current_load: Num
    # Sink-written cache of total_distance(), which stays as the recompute twin. Maintained the
    # same way current_load is: the raw record carries the delta, the processor passes it
    # through, apply_accounting adds it. No mutator touches it.
    current_travel: Num

    def __init__(self, path: list[CustomerVisit], end_depot: Depot):
        # MUST come first: populate_derived_data/count_load_change below read self.vehicle,
        # and there is no class-level default to fall back on.
        self.vehicle = None
        self.prev_route = None   # None iff unassigned; set when linked into a vehicle
        self.next_route = None

        self.path = path # List of customer visits

        self.first_visit = FirstRouteVisit(VIRTUAL_DEPOT, self)
        self.last_visit = LastRouteVisit(end_depot, self)

        self.current_load = 0
        # Load changes are populated once after full solution creation, then only by operator apply() methods.

        self.link_visits()

        # AFTER link_visits: total_distance() reads the visit chain. An empty route (the hot
        # construction, one per SplitRandomRoute proposal) is O(1) here; a route built with a
        # path pays one walk at construction, which is the honest starting value for a cache
        # nothing else will recompute.
        self.current_travel = self.total_distance()
        # Start_depot and vehicle will be filled out when the src_route is added to a vehicle.

    def set_values(self, path: list[CustomerVisit]|None =None, vehicle: Vehicle|None=None, start_depot:Depot|None=None, end_depot:Depot|None=None):
        if path is not None:
            self.path = path
            self.link_visits()
        if vehicle is not None:
            self.vehicle = vehicle
        if start_depot is not None:
            # Start depot must be where the vehicle left off.
            # So this is a derived quantity, but useful for reference nonetheless.
            self.first_visit.replace_depot(start_depot)
        if end_depot is not None:
            self.set_end_depot(end_depot)

    #region Core state-tracking properties and methods

    #region Path-related properties/methods (depots/customers)
    @property
    def start_depot(self) -> Depot:
        return self.first_visit.source_depot

    @property
    def used_start_depot(self) -> Depot:
        # Start depot if active, VirtualDepot otherwise
        return self.first_visit.source_depot if self.is_active else VIRTUAL_DEPOT

    @property
    def end_depot(self) -> Depot:
        return self.last_visit.source_depot

    @property
    def path_len(self) -> int: return len(self.path)

    @property
    def num_customers(self) -> int: return len(self.path)

    def get_visit_at(self, i: int) -> RouteVisit:
        # More robust version of get_visit that returns first/last visit if index is out of bounds
        if i<0:
            return self.first_visit

        if i>=len(self.path):
            return self.last_visit

        return self.path[i]

    def closest_non_adjacent_customer(self, index: int) -> int | None:
        """
        Index of the customer nearest to path[index], excluding itself and its two immediate
        neighbours. None when no such customer exists (a route of 2 or fewer, or an interior
        index on a route of 3).

        The exclusion is what makes this useful rather than degenerate. The nearest customer
        in a route is very often the one already beside it, and a move anchored on an adjacent
        pair has nothing to change -- an empty interval to relocate, or a zero-length reversal.

        O(n). The route is a path, not a cycle (a depot sits at each end), so adjacency does
        not wrap.
        """
        path = self.path
        anchor = path[index]

        best_index, best_distance = None, float('inf')
        for i in range(len(path)):
            if abs(i - index) <= 1:
                continue
            distance = anchor.distance(path[i])
            if distance < best_distance:
                best_index, best_distance = i, distance

        return best_index

    @property
    def path_is_cycle(self) -> bool: return self.start_depot == self.end_depot

    @property
    def is_empty(self) -> bool: return self.path_len == 0

    @property
    def has_customers(self) -> bool: return self.path_len > 0

    @property
    def is_trivial(self) -> bool: return self.is_empty and self.path_is_cycle

    #region Path distance computations
    # Any of these could be useful in computing cost deltas within solution operators.
    def total_distance(self):
        # Vehicle assignment is NOT required. Travel distance is a function of start_depot,
        # path and end_depot only -- start_depot reads through first_visit.source_depot, which
        # is route-local and survives unlinking. The old guard also demanded self.vehicle,
        # which made it impossible to price a route while it was detached: exactly what an
        # operator that measures by mutating has to do, and what ruin-and-recreate will need
        # while customers are in flight.
        if self.start_depot is None:
            raise Exception("Route must have a start depot to compute total distance")

        return self.first_move_distance() + self.tail_distance()

    def first_move_distance(self):
        return self.first_visit.distance_out

    def last_move_distance(self):
        return self.last_visit.distance_in

    def first_and_last_move_distance(self):
        if len(self.path) == 0:
            return self.first_move_distance()  # There can be only one (move)

        return self.first_move_distance() + self.last_move_distance()

    def path_distance(self, start: int, stop: int) -> Num:
        """
        Sum of the arcs strictly INSIDE path[start:stop]. Zero for a chain of 0 or 1.

        THE ONLY PLACE A SUB-CHAIN LENGTH IS COMPUTED. Three callers need one: the two
        cross-route chain aggregators and the split. Every other aggregator attributes travel
        from boundary arcs it already computes.

        It exists as one function so the O(k) can be traded away later without touching an
        aggregator -- a slice sum over cached arcs, or a prefix difference over a cumsum, both
        drop in here. Measured before choosing the loop: the chain queries this serves cost
        about 0.2% of wall time, and a maintained cumsum costs 0.09-0.35% to replace them.
        """
        path = self.path
        curr = path[start]
        total = 0.0
        for i in range(start+1, stop):
            nxt = path[i]
            total += curr.distance(nxt)
            curr = nxt
        return total

    @staticmethod
    def visits_distance(visits: Sequence[CustomerVisit]) -> Num:
        """path_distance for DETACHED visits -- the ruin-and-recreate half, where the chain no
        longer belongs to a route but its interior arcs are still the arcs it carries."""
        total: Num = 0
        for i in range(len(visits) - 1):
            total += visits[i].distance(visits[i + 1])
        return total

    def recompute_current_travel(self) -> Num:
        """Ground truth for current_travel. The oracle twin, and what initialize_accounting
        writes."""
        return self.total_distance()

    def mid_distance(self):
        path = self.path
        path_len = len(path)

        if path_len == 0:
            return 0 # Nothing to see here!

        return sum(path[i].distance(path[i + 1]) for i in range(path_len - 1))

    def tail_distance(self):
        # Returns total distance, minus first node

        path = self.path
        path_len = len(path)
        end_depot = self.end_depot

        if path_len == 0:
            return 0 # Nothing to see here!

        end_dist = end_depot.distance(path[-1])
        mid_dist = sum(path[i].distance(path[i+1]) for i in range(path_len-1))
        return mid_dist + end_dist
    #endregion

    #endregion

    #region Vehicle-dependent properties and methods
    # NOTE: A src_route is active if it's nonempty and assigned to a vehicle.
    @property
    def is_active(self) -> bool:
        # Nontrivial and assigned to an active vehicle.
        return self.vehicle is not None and self.path_len > 0

    @property
    def is_inactive(self) -> bool:
        return self.vehicle is None or self.path_len == 0

    @property
    def is_assigned(self) -> bool:
        vehicle = self.vehicle
        return vehicle is not None

    @property
    def is_assigned_to_active_vehicle(self) -> bool:
        vehicle = self.vehicle
        return vehicle is not None and vehicle.is_active

    @property
    def is_overloaded(self) -> bool:
        vehicle = self.vehicle
        return vehicle is not None and self.current_load > vehicle.capacity

    @property
    def amount_overloaded(self) -> Num:
        vehicle = self.vehicle
        return max(0, self.current_load - vehicle.capacity) if vehicle is not None else 0

    def is_adjacent_with(self, other: Route| FirstRoute | LastRoute | None):
        return other is not None and other == self.prev_route or other == self.next_route

    def shares_vehicle_with(self, other: Route):
        # If self.vehicle is None, vehicle not shared. Otherwise, self.vehicle==dest_route.vehicle covers
        # both "dest_route has vehicle" and "dest_route has no vehicle" cases.
        return self.vehicle is not None and self.vehicle == other.vehicle

    def recompute_current_load(self) -> Num:
        if not self.path:
            return 0

        return sum(customer.demand for customer in self.path)

    #endregion

    #endregion

    #region Delta computations

    #region Basic operations

    #region Changing end depot
    def travel_delta_if_end_depot_changes(self, new_end_depot: Depot) -> Num:
        # Includes relinking the depot for the last move of this route and the first move of any next route
        return self.last_visit.get_replacement_travel_delta(new_end_depot)

    # Since we don't allow operations (except removal and customer insertion) for empty routes:
    #   if we're changing the end depot, this src_route is nonempty, and so our vehicle is active and will remain so.

    def cost_deltas_if_end_depot_changes(self, new_end_depot: Depot) -> RawDeltaRecord:
        # Two routes move and each half is route-local: this route's last arc, and the next
        # route's first arc (a route's end depot IS the next route's start depot).
        own_travel, next_travel = self.last_visit.get_replacement_travel_deltas(new_end_depot)

        # THIS ROUTE DOES NOT CHANGE. A route's end depot IS the next route's start depot, so
        # set_end_depot -> last_visit.replace_depot moves the NEXT route's start_depot and
        # leaves this one alone. Measured, not inferred. End-depot use is not tracked until
        # step 4, so this route's own entry would be unchanged and would drop anyway.
        start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = NO_CHANGES
        next_route = self.next_route

        # isinstance, not `is not None`: the tail route's next_route is the LastRoute sentinel.
        if isinstance(next_route, Route) and next_route.start_depot != new_end_depot and len(next_route.path) > 0:
            # Next route start depot change is counted if it has customers and the depot changes (Assignment guaranteed)
            start_depots = {next_route : (next_route.start_depot, new_end_depot)}

        travels: dict[Route, Num] | Mapping = {self: own_travel} if own_travel else {}
        if next_travel and isinstance(next_route, Route):
            assert isinstance(travels, dict)
            travels[next_route] = next_travel

        return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                              start_depot_changes=start_depots)
    #endregion

    #region Route operations: removing, inserting, and appending self to/from a vehicle.
    # Possibilities: Travel distance could change. Vehicle could be activated/deactivated.
    #   Depot could be activated/deactivated. Route loads could change.

    #region Travel-related computations
    def travel_delta_if_removed(self) -> Num:
        if self.is_trivial or not self.is_assigned:
            return 0

        # Travel deltas are: from removing the first move, and from changing the start depot of the next src_route
        return self.first_visit.start_travel_delta_if_route_removed() + self.last_visit.end_travel_delta_if_route_removed()

    def travel_delta_if_inserted_before(self, next_route: Route | LastRoute) -> Num:
        # REQUIRE adjacent case to be gatekept by parent, calling full delta-comp fcn for swapping adjacent routes.
        assert not self.is_adjacent_with(next_route), "Wrong function for adjacent routes."
        if self.is_empty or next_route is self:
            # We don't insert or shift around empty routes. Just remove, dispose, or combine.
            # If moving to current location no change!
            return 0

        # Nonadjacent case only! Cleanly remove from current location and insert at new.

        # Travel deltas are from:
        # 1) Changing the start depot of self's OLD successor, now that self has vacated its old spot
        # 2) Replacing self's own entry edge: old_start->first_customer becomes new_start->first_customer
        # 3) Changing the start depot of the next src_route (self's new successor), or 0 if appending (LastRoute)
        # NOTE: Internal travel deltas for the src_route are always counted in the global objective, and
        # are not explicitly tracked per-src_route.
        # IMPORTANT: item 1 uses only last_visit.end_travel_delta_if_route_removed(), NOT the full
        # travel_delta_if_removed() -- that also includes first_visit.start_travel_delta_if_route_removed()
        # (self's own entry edge disappearing), which would double-count against item 2 below, which
        # already nets out the change to self's own entry edge (old_start -> new_start).
        new_start_depot = next_route.start_depot
        end_depot = self.end_depot

        remove_delta = self.last_visit.end_travel_delta_if_route_removed()
        start_delta = self.first_visit.start_travel_delta_if_depot_swapped(new_start_depot)
        end_delta = 0 if isinstance(next_route, LastRoute) else next_route.first_visit.start_travel_delta_if_depot_swapped(end_depot)

        return remove_delta + start_delta + end_delta

    def travel_delta_if_appended_to(self, vehicle: Vehicle):
        return self.travel_delta_if_inserted_before(vehicle.last_route)
    #endregion

    #region Full delta computations
    def cost_deltas_if_removed(self):
        # Also doubles as "travel delta if disposed"
        # Returns: travel_delta, depot_used_delta, vehicle_used_delta, load_delta
        if self.vehicle is None:
            return RawDeltaRecord() # Cannot remove a src_route if it's unassigned!

        start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}

        if self.is_active:
            # If self is active, start_depot becomes unused
            start_depots[self] = (self.start_depot, VIRTUAL_DEPOT)

        vehicles: dict[Route, tuple[Vehicle, Vehicle|None]] = {self: (self.vehicle, None)}

        next_route = self.next_route
        # isinstance, not `is not None`: the tail route's next_route is the LastRoute sentinel,
        # which has no start depot to inherit anything.
        if isinstance(next_route, Route) and next_route.start_depot != self.start_depot and len(next_route.path) > 0:
            assert isinstance(start_depots, dict) # Make linter glad
            # Next used start depot changes if next route has customers and its start depot changes (Assignment guaranteed)
            start_depots[next_route] = (next_route.start_depot, self.start_depot)

        if not start_depots:
            start_depots = NO_CHANGES

        if self.is_trivial:
            return RawDeltaRecord(start_depot_changes=start_depots, vehicle_changes=vehicles) # Delta = 0, but the structure still moves.

        # Two halves, already route-local. The first is this route losing its own entry arc --
        # an unassigned route starts at a VirtualDepot, and FirstRouteVisit.distance returns 0
        # from one, so the route's own total drops by exactly that arc. The second is the next
        # route inheriting this one's start depot.
        own_travel = self.first_visit.start_travel_delta_if_route_removed()
        next_travel = self.last_visit.end_travel_delta_if_route_removed()

        travels: dict[Route, Num] | Mapping = {self: own_travel} if own_travel else {}
        if next_travel and isinstance(next_route, Route):
            assert isinstance(travels, dict)
            travels[next_route] = next_travel

        return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                              start_depot_changes=start_depots, vehicle_changes=vehicles)

    def cost_deltas_if_inserted_before(self, other: Route|LastRoute) -> RawDeltaRecord:
        vehicle = other.vehicle
        assert vehicle is not None, "Cannot insert before unassigned route"

        # If currently assigned to a vehicle: this DOES NOT include deltas for removal stage
        if self.is_adjacent_with(other):
            # route1 is earlier of self or dest_route, route2 = route1.next_route is the later.
            # Since the two are adjacent... both exist.
            route1 = self if other is self.next_route else other
            assert isinstance(route1, Route)
            return route1.cost_deltas_if_swapped_with_next_route()

        # Returns: travel_delta, depot_used_delta, vehicle_used_delta, load_delta
        if self.is_empty:
            return RawDeltaRecord() # Delta = 0. (We don't allow inserting empty stuff - so return 0.)

        # Three routes move their entry arc, and travel_delta_if_inserted_before already
        # computes the three pieces separately before adding them. Keep them apart.
        insert_start_depot = other.start_depot
        insert_end_depot = self.end_depot
        old_successor_travel = self.last_visit.end_travel_delta_if_route_removed()
        own_travel = self.first_visit.start_travel_delta_if_depot_swapped(insert_start_depot)
        other_travel = (0 if isinstance(other, LastRoute)
                        else other.first_visit.start_travel_delta_if_depot_swapped(insert_end_depot))

        # Up to three routes move their start depot, and NONE of them changes load or customer
        # count -- relinking carries a route's customers with it. The adjacent case never gets
        # here (it returned above), so self's old successor is never `other`.
        #   self          -- starts where `other` used to start; joins `vehicle`
        #   old successor -- inherits self's old start depot, now that self has vacated
        #   other         -- starts at self's end depot, now that self sits in front of it
        # LastRoute successors get no entry: they are sentinels, not routes.
        has_customers = len(self.path) > 0

        start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}

        self_start = self.used_start_depot
        self_end = self.end_depot
        other_start = other.start_depot
        if has_customers and self_start != other_start:
            # Start depot changes if has customers and changes start depots. (Assignment guaranteed)
            start_depots[self] = (self_start, other_start)

        old_successor = self.next_route
        if isinstance(old_successor, Route) and len(old_successor.path) > 0\
           and (old_successor_start := old_successor.start_depot) != self_start:
            # Successor start depot changes if it has customers and changes start depots. (Assignment guaranteed)
            start_depots[old_successor] = (old_successor_start, self_start)
        if isinstance(other, Route) and len(other.path) > 0 \
           and other_start != self_end:
            # Other start depot changes if it has customers and changes start depots. (Assignment guaranteed)
            start_depots[other] = (other_start, self_end)

        if not start_depots:
            start_depots = NO_CHANGES

        self_vehicle = self.vehicle
        vehicle_changes = {self: (self_vehicle, vehicle)} if self_vehicle != vehicle else NO_CHANGES

        travels: dict[Route, Num] = {}
        if own_travel:
            travels[self] = own_travel
        if old_successor_travel and isinstance(old_successor, Route):
            travels[old_successor] = travels.get(old_successor, 0) + old_successor_travel
        if other_travel and isinstance(other, Route):
            travels[other] = travels.get(other, 0) + other_travel

        return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                              start_depot_changes=start_depots,
                              vehicle_changes=vehicle_changes)

    def cost_deltas_if_appended_to(self, vehicle: Vehicle) -> RawDeltaRecord:
        # Returns: travel_delta, depot_used_delta, vehicle_used_delta
        return self.cost_deltas_if_inserted_before(vehicle.last_route)
    #endregion
    #endregion

    #region Basic customer operations (within a src_route): Remove, pop, insert, append

    #region Travel-related deltas
    @staticmethod
    def travel_delta_if_customer_removed(customer: CustomerVisit) -> Num:
        return customer.travel_delta_if_removed

    def travel_delta_if_customer_popped(self, index: int) -> Num:
        if index >= self.path_len:
            raise IndexError("Customer index out of range.")
        return self.travel_delta_if_customer_removed(self.path[index])

    @staticmethod
    def travel_delta_if_customer_inserted_before(customer: CustomerVisit, insert_visit: CustomerVisit | LastRouteVisit,
                                                 customer_route: Route) -> Num:
        # For efficiency: callers need to gate for no-ops
        assert insert_visit is not customer and insert_visit.prev_visit is not customer, "Travel delta mini-method called on no-op."
        adjacent = customer.is_adjacent_with(insert_visit)

        return (customer.travel_delta_if_swapped_with(insert_visit)) if adjacent and isinstance(insert_visit, CustomerVisit) \
            else customer_route.travel_delta_if_customer_removed(customer) + insert_visit.travel_delta_if_inserting_customer_before_this(customer)

    def travel_delta_if_unassigned_customer_appended(self, customer: CustomerVisit, customer_route: Route) -> Num:
        return Route.travel_delta_if_customer_inserted_before(customer, self.last_visit, customer_route)
    #endregion

    #region Full deltas
    def cost_deltas_if_customer_removed(self, customer: CustomerVisit) -> RawDeltaRecord:
        travel_delta = self.travel_delta_if_customer_removed(customer)

        # A chain of one has no interior, so the link delta IS this route's whole change.
        raw = RawDeltaRecord.for_customers_changing((self, travel_delta, -customer.demand, -1))
        return raw

    def cost_deltas_if_customer_popped(self, index: int) -> RawDeltaRecord:
        travel_delta = self.travel_delta_if_customer_popped(index)

        raw = RawDeltaRecord.for_customers_changing(
            (self, travel_delta, -self.path[index].demand, -1))
        return raw

    def cost_deltas_if_customer_inserted_before(self, customer: CustomerVisit, insert_visit: CustomerVisit | LastRouteVisit) -> RawDeltaRecord:
        if insert_visit is customer or insert_visit is customer.next_visit:
            return RawDeltaRecord() # No-op!

        customer_route: Route | None = customer.route

        assert isinstance(insert_visit, CustomerVisit|LastRouteVisit)
        assert isinstance(customer_route, Route)

        # DECISION: We don't compute full cost deltas explicitly for unassigned customers.
        # IN THE EVENT we choose to add support for this (e.g. for multi-day delivery plans where some customers don't get deliveries):
        # We will split into "Unassigned" and "Assigned" versions for add/insert operations, and this method
        # will triage between the two.


        if customer_route is self:
            # Same route: nothing crosses a boundary, so the whole link delta is this route's.
            assert isinstance(customer_route, Route)
            travel_delta = Route.travel_delta_if_customer_inserted_before(
                customer, insert_visit, customer_route)
            return RawDeltaRecord(travel_changes={self: travel_delta})

        # CROSS-ROUTE, and the two halves are already route-local: the source closes the gap
        # the customer leaves, the destination opens one for it. A single customer carries no
        # interior arcs, so no sub-chain sum is needed here.
        assert isinstance(customer_route, Route)
        source_travel = customer_route.travel_delta_if_customer_removed(customer)
        dest_travel = insert_visit.travel_delta_if_inserting_customer_before_this(customer)

        raw = RawDeltaRecord.for_customers_changing(
            (self, dest_travel, customer.demand, 1),
            (customer_route, source_travel, -customer.demand, -1))

        return raw


    def cost_deltas_if_customer_appended(self, customer):
        return self.cost_deltas_if_customer_inserted_before(customer, self.last_visit)

    #region Sequential halves: remove, then insert
    # cost_deltas_if_customer_chain_moved prices a move as ONE joint quantity, because it
    # prices before performing anything: its depot and vehicle terms are literally
    # "activates at the destination MINUS deactivates at the source" (see
    # depot_activation_delta_if_customers_added). That is unavoidable when nothing has
    # happened yet, and it is also what makes the move impossible to reuse -- a ruin step
    # removes k customers now and decides where they land much later.
    #
    # These two price the same thing as two independent halves. Remove is charged against the
    # live route; insert is then charged against the state the removal LEFT, so the two sum.
    # Overload is nonlinear in load, so that ordering is a correctness requirement, not a
    # convenience.
    #
    # The insert half is destination-only. It takes detached visits and never asks where they
    # came from, which is what the note on cost_deltas_if_customer_inserted_before called the
    # "Unassigned" version it did not yet have.

    def travel_delta_if_customer_chain_removed(self, chain: Chain) -> Num:
        """Closing the gap a chain leaves behind. Orientation-independent."""
        rng = as_chain_range(chain)
        path = self.path
        first = path[rng.start]
        last = path[rng.stop - 1]
        before_chain = first.prev_visit
        after_chain = last.next_visit

        return (before_chain.distance(after_chain)
                - before_chain.distance(first) - last.distance(after_chain))

    def cost_deltas_if_customer_chain_removed(self, chain: Chain) -> RawDeltaRecord:
        """
        Price taking `chain` out of this route, charged BEFORE the removal happens.

        A chain of one is the single-customer removal, so this widens
        cost_deltas_if_customer_removed rather than sitting beside it.
        """
        rng = as_chain_range(chain)
        k = len(rng)
        if k == 0:
            return RawDeltaRecord()

        path = self.path
        chain_load = sum(path[i].demand for i in rng)

        # The link delta closes the gap the chain leaves. The route ALSO loses the chain's
        # interior arcs, which travel with the detached visits, so this route's own change is
        # the link delta minus that interior. The matching insert half adds it back.
        travel_delta = (self.travel_delta_if_customer_chain_removed(rng)
                        - self.path_distance(rng.start, rng.stop))

        # Only this route moves. The visits come out DETACHED -- they belong to no route until
        # someone inserts them -- so there is no second entry to make here. Start depot and
        # vehicle are untouched even when the route empties completely: an empty route is still
        # an assigned route, and whether it still COUNTS as using its depot is a step function
        # of the customer count, which the processor resolves. Reported, not decided.
        raw = RawDeltaRecord.for_customers_changing((self, travel_delta, -chain_load, -k))

        return raw

    @staticmethod
    def travel_deltas_if_customer_chain_inserted_before(
            visits: Sequence[CustomerVisit],
            insert_visit: CustomerVisit | LastRouteVisit) -> tuple[Num, Num]:
        """
        (not_reversed, reversed) travel for splicing detached `visits` in before insert_visit.

        The chain's INTERIOR arcs are identical either way -- Node.distance is Euclidean and
        therefore symmetric -- so orientation reaches exactly the two boundary arcs.
        """
        first, last = visits[0], visits[-1]
        prev_insert = insert_visit.prev_visit
        reconnect = -prev_insert.distance(insert_visit)

        return (prev_insert.distance(first) + last.distance(insert_visit) + reconnect,
                prev_insert.distance(last) + first.distance(insert_visit) + reconnect)

    def cost_deltas_if_customer_chain_inserted_before(
            self, visits: Sequence[CustomerVisit],
            insert_visit: CustomerVisit | LastRouteVisit
    ) -> tuple[RawDeltaRecord, RawDeltaRecord]:
        """
        Price splicing detached `visits` into THIS route before insert_visit.

        Returns (not_reversed, reversed); only travel_distance differs between them. Makes no
        decision -- the caller picks, exactly as cost_deltas_if_customer_chain_moved does.

        Destination-only by design: `visits` are detached, so there is no source route to
        offset against. Whoever detached them already charged that side.
        """
        k = len(visits)
        if k == 0:
            return RawDeltaRecord(), RawDeltaRecord()

        chain_load = sum(visit.demand for visit in visits)

        fwd_travel, rev_travel = Route.travel_deltas_if_customer_chain_inserted_before(
            visits, insert_visit)

        # The chain brings its own interior arcs with it. Orientation does not change their
        # total: Node.distance is symmetric, so a reversed chain has the same interior.
        interior = Route.visits_distance(visits)
        fwd_travel += interior
        rev_travel += interior

        # Destination-only, matching the price above: `visits` are detached, so no source route
        # appears here. The two orientations differ only in distance, but each gets its OWN
        # record -- the caller keeps whichever it picks, and a shared dict would alias.


        # changes = (route, travel_change, load_change, customer_count_change)
        raw_fwd = RawDeltaRecord.for_customers_changing((self, fwd_travel, chain_load, k))
        raw_rev = RawDeltaRecord.for_customers_changing((self, rev_travel, chain_load, k))

        return raw_fwd, raw_rev
    #endregion

    def travel_deltas_if_customer_chain_moved(self, chain: Chain,
                                              insert_visit: CustomerVisit | LastRouteVisit) -> tuple[Num, Num]:
        # Returns (not_reversed, reversed), in that order.
        rng = as_chain_range(chain)
        path = self.path
        first = path[rng.start]
        last = path[rng.stop - 1]
        before_chain = first.prev_visit
        after_chain = last.next_visit
        prev_insert = insert_visit.prev_visit

        # Closing the gap the chain leaves behind. Identical for both orientations.
        removal = (before_chain.distance(after_chain)
                   - before_chain.distance(first) - last.distance(after_chain))

        # Opening the gap at the destination. The chain's INTERIOR arcs are unchanged either
        # way, because the metric is symmetric (Node.distance is Euclidean), so orientation
        # reaches exactly these two arcs and nothing else.
        reconnect = -prev_insert.distance(insert_visit)
        forward = prev_insert.distance(first) + last.distance(insert_visit) + reconnect
        backward = prev_insert.distance(last) + first.distance(insert_visit) + reconnect

        return removal + forward, removal + backward

    def cost_deltas_if_customer_chain_moved(self, chain: Chain, dest_route: Route,
                                            dest_idx: int) -> tuple[RawDeltaRecord, RawDeltaRecord]:
        # Returns (not_reversed, reversed). The two differ ONLY in travel_distance: the other
        # four terms depend on which customers moved and where to, never on their order.
        # This makes no decision -- it hands back both prices and the caller picks.
        rng = as_chain_range(chain)
        k = len(rng)
        same_route = dest_route is self

        # Mirrors ReassignCustomerAt's pre-removal precedent fetch, widened from one customer
        # to k: moving right within a route, everything from dest_idx on shifts left by k once
        # the chain is gone, so before the removal the visit to insert before sits k further on.
        insert_visit = dest_route.get_visit_at(
            dest_idx + k if same_route and rng.start <= dest_idx else dest_idx)
        assert isinstance(insert_visit, CustomerVisit | LastRouteVisit)

        fwd_travel, rev_travel = self.travel_deltas_if_customer_chain_moved(rng, insert_visit)

        if same_route:
            # No customer crosses a route boundary, so load, depot and vehicle are untouched --
            # and the whole travel delta belongs to this one route.
            return (RawDeltaRecord(travel_changes={self: fwd_travel}),
                    RawDeltaRecord(travel_changes={self: rev_travel}))

        chain_load = sum(self.path[i].demand for i in rng)

        # CROSS-ROUTE. The link deltas are only jointly correct: the source genuinely loses the
        # chain's interior arcs and the destination genuinely gains them, and neither half
        # names them. Split by moving that interior across, which is the one sub-chain sum this
        # aggregator needs.
        interior = self.path_distance(rng.start, rng.stop)
        source_travel = self.travel_delta_if_customer_chain_removed(rng) - interior
        fwd_dest_travel = fwd_travel - source_travel
        rev_dest_travel = rev_travel - source_travel

        # The chain crosses a boundary: k customers leave self and join dest_route. The
        # same-route case returned above, so these are always two distinct entries.

        # changes = (route, travel_change, load_change, customer_count_change)
        self_changes = (self, source_travel, -chain_load, -k)

        raw_fwd = RawDeltaRecord.for_customers_changing(
                self_changes, (dest_route, fwd_dest_travel, chain_load, k))
        raw_rev = RawDeltaRecord.for_customers_changing(
            self_changes, (dest_route, rev_dest_travel, chain_load, k))

        return raw_fwd, raw_rev
    #endregion

    #endregion

    #endregion

    #region Composite operations: Swapping customers, permuting/subpermuting, combining, and splitting

    #region Customer swaps
    # can only change travel distance or route loads)
    @staticmethod
    def cost_deltas_for_adjacent_customer_swap_starting_with(customer1: CustomerVisit):
        customer2 = customer1.next_visit
        if not isinstance(customer2, CustomerVisit):
            raise ValueError("Specified customer is at the end of a src_route.")

        # Swapping adjacent customers affects only travel distance:
        # No depots/vehicles are activated and no src_route loads change.

        travel_delta = customer1.travel_delta_if_swapped_with(customer2)
        # INTRA-ROUTE: distance and nothing else. No customer crosses a route boundary, so
        # load, count, start depot and vehicle all end where they started, and the whole travel
        # delta belongs to the one route the two customers share.
        route = customer1.route
        assert isinstance(route, Route)
        return RawDeltaRecord(travel_changes={route: travel_delta})

    def cost_deltas_for_adjacent_customer_swap_starting_at(self, index: int):
        # Get cost for swapping customer at index with the next one.
        if index >= self.path_len - 1 or index < 0:
            if index == self.path_len - 1:
                raise ValueError("Specified customer has no next customer.")
            else:
                raise ValueError("Customer index out of range.")

        path = self.path
        customer1 = path[index]

        return self.cost_deltas_for_adjacent_customer_swap_starting_with(customer1)

    @staticmethod
    def total_load_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit) -> tuple[Num, Num]:
        # Returns (route1 delta, route2 delta)
        route1 = customer1.route
        route2 = customer2.route

        if route1 is None or route2 is None:
            raise ValueError("Cannot swap customers that aren't assigned to routes!")

        # current_route_load_delta_if_swapped_with, not a bare demand difference: it reduces
        # numerical error when both customers share a route.
        route1_load_delta = customer1.current_route_load_delta_if_swapped_with(customer2)
        return route1_load_delta, -route1_load_delta

    # Any two customers
    @staticmethod
    def cost_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit):
        # Implement all deltas in one place to prevent rework such as recomputing load deltas.

        # A swap moves LOAD but not COUNT: each route gives one customer and takes one back.
        # Intra-route swaps move nothing at all, and their entries cancel to unchanged.
        route1, route2 = customer1.route, customer2.route
        assert route1 is not None and route2 is not None
        if route1 is route2:
            raw = RawDeltaRecord(
                travel_changes={route1: customer1.travel_delta_if_swapped_with(customer2)})
        else:
            # Two routes, and the two halves are already route-local: each side is one
            # customer replaced by another in place. Neither carries an interior.
            travel1, travel2 = customer1.travel_deltas_if_swapped_with(customer2)
            route1_load_delta = customer1.current_route_load_delta_if_swapped_with(customer2)
            raw = RawDeltaRecord.for_customers_changing(
                (route1, travel1, route1_load_delta, 0),
                (route2, travel2, -route1_load_delta, 0))

        # Swapping customers does not change vehicle or depot activation. So we're ready to return.
        return raw

    def cost_deltas_for_intra_route_customer_swap_at(self, i: int, j: int):
        customer1 = self.path[i]
        customer2 = self.path[j]

        return self.cost_deltas_for_customer_swap(customer1, customer2)

    def cost_deltas_for_inter_route_customer_swap_at(self, i: int, other: Route, j: int):
        customer1 = self.path[i]
        customer2 = other.path[j]

        return self.cost_deltas_for_customer_swap(customer1, customer2)

    def customer_chains_are_adjacent(self, chain: Chain, other: Route, other_chain: Chain) -> bool:
        # Only possible within one route. Adjacent chains share a boundary arc, which makes
        # the two reversals interact -- see cost_deltas_for_customer_chain_swap.
        if self is not other:
            return False
        rng1, rng2 = as_chain_range(chain), as_chain_range(other_chain)
        return rng1.stop == rng2.start or rng2.stop == rng1.start

    def cost_deltas_for_customer_chain_swap(self, chain: Chain, other: Route, other_chain: Chain
                                            ) -> tuple[RawDeltaRecord, RawDeltaRecord,
                                                       RawDeltaRecord, RawDeltaRecord]:
        """
        TODO(swap-len1-shortcut): when both chains have length 1 the four travels are equal,
        because reversing a single customer changes nothing. Detect that and compute one.

        Four deltas in fixed order: (fwd_fwd, rev1_fwd, fwd_rev2, rev1_rev2). rev1 reverses
        THIS route's chain as it lands in `other`; rev2 reverses other's chain as it lands
        here. Only travel_distance differs between the four. Makes no decision -- the caller
        picks.
        """
        rng1, rng2 = as_chain_range(chain), as_chain_range(other_chain)
        path1, path2 = self.path, other.path

        c1_first, c1_last = path1[rng1.start], path1[rng1.stop - 1]
        c2_first, c2_last = path2[rng2.start], path2[rng2.stop - 1]

        if len(rng1) == 1 and len(rng2) == 1:
            # Reversing one customer changes nothing, so all four are equal. The
            # single-customer swap delta already covers adjacency, load and overload, so
            # delegate rather than re-derive any of it here.
            delta = Route.cost_deltas_for_customer_swap(c1_first, c2_first)
            return delta, delta, delta, delta

        if self.customer_chains_are_adjacent(rng1, other, rng2):
            # The chains touch, so the arc between them depends on BOTH reversals and the two
            # sides do not separate. Compose rather than recompute: moving the EARLIER chain
            # past the later one is exactly cost_deltas_if_customer_chain_moved, which is
            # already verified. Reversing the other chain then adds a term that depends on the
            # first chain's orientation -- evaluating that term once per case is what captures
            # the coupling.
            if rng1.stop == rng2.start:
                early, late = rng1, rng2
                e_first, e_last, l_first, l_last = c1_first, c1_last, c2_first, c2_last
                early_is_chain1 = True
            else:
                early, late = rng2, rng1
                e_first, e_last, l_first, l_last = c2_first, c2_last, c1_first, c1_last
                early_is_chain1 = False

            a_visit = e_first.prev_visit
            # Same-route move, so these carry travel_distance only.
            # Index [1], the RAW RECORD, not [0]: since step 1 the aggregators no longer put
            # travel_distance in the ObjectiveTermDelta -- the processor derives it from the
            # record. Reading [0] here returns 0 and silently prices every adjacent chain swap
            # as if the move cost nothing.
            moved = self.cost_deltas_if_customer_chain_moved(early, self, early.start + len(late))
            moved_travel = moved[0].travel_distance, moved[1].travel_distance

            def reverse_late_delta(head_early):
                # The late chain ends up at [early.start, early.start + len(late)), bracketed
                # by a_visit and whichever end of the early chain now leads.
                return (a_visit.distance(l_last) + l_first.distance(head_early)
                        - a_visit.distance(l_first) - l_last.distance(head_early))

            def travel(reverse1, reverse2):
                rev_early, rev_late = (reverse1, reverse2) if early_is_chain1 else (reverse2, reverse1)
                total = moved_travel[1 if rev_early else 0]
                if rev_late:
                    total += reverse_late_delta(e_last if rev_early else e_first)
                return total

            # One route throughout: both chains live here, so the whole delta is this
            # route's and there is no interior to move anywhere.
            travels = tuple((t, 0) for t in (travel(False, False), travel(True, False),
                                             travel(False, True), travel(True, True)))
        else:
            # Disjoint slots: rev1 only touches other's slot and rev2 only touches this one,
            # so the four totals are sums of two independent halves. 12 distance calls.
            a1, b1 = c1_first.prev_visit, c1_last.next_visit
            a2, b2 = c2_first.prev_visit, c2_last.next_visit

            removed_here = a1.distance(c1_first) + c1_last.distance(b1)
            removed_there = a2.distance(c2_first) + c2_last.distance(b2)

            # chain1 lands in other's slot
            there_fwd = a2.distance(c1_first) + c1_last.distance(b2) - removed_there
            there_rev = a2.distance(c1_last) + c1_first.distance(b2) - removed_there
            # chain2 lands in this route's slot
            here_fwd = a1.distance(c2_first) + c2_last.distance(b1) - removed_here
            here_rev = a1.distance(c2_last) + c2_first.distance(b1) - removed_here

            if self is other:
                # Two disjoint chains inside ONE route. Both slots belong here, so the sum is
                # this route's whole change and the interiors never cross a boundary.
                travels = tuple((t, 0) for t in
                                (there_fwd + here_fwd, there_rev + here_fwd,
                                 there_fwd + here_rev, there_rev + here_rev))
            else:
                # CROSS-ROUTE. here_* and there_* are each one slot's boundary change, so they
                # are already route-local -- but each route also swaps which interior it
                # carries. This route gives up chain1's interior and takes chain2's; the other
                # route does the reverse. Orientation does not change an interior, because the
                # metric is symmetric.
                interior1 = self.path_distance(rng1.start, rng1.stop)
                interior2 = other.path_distance(rng2.start, rng2.stop)
                swing = interior2 - interior1
                travels = ((here_fwd + swing, there_fwd - swing),   # fwd_fwd
                           (here_fwd + swing, there_rev - swing),   # rev1_fwd
                           (here_rev + swing, there_fwd - swing),   # fwd_rev2
                           (here_rev + swing, there_rev - swing))   # rev1_rev2

        # No vehicles_activated or depots_activated terms. Both chains are non-empty (the BL
        # guards it), so each route keeps at least one customer and neither can empty. If that
        # guard ever goes, these terms come back.
        chain1_load = sum(path1[i].demand for i in rng1)
        chain2_load = sum(path2[j].demand for j in rng2)

        # Each route gives its chain and takes the other's, so load and count both move by the
        # difference. Intra-route swaps exchange nothing across a boundary, so no entries.
        # Each orientation gets its OWN record: the caller keeps whichever it picks, and a
        # shared dict would alias.
        def raw(travel: tuple[Num, Num]) -> RawDeltaRecord:
            own_travel, other_travel = travel
            if self is other:
                return RawDeltaRecord(travel_changes={self: own_travel} if own_travel
                                      else NO_CHANGES)
            return RawDeltaRecord.for_customers_changing(
                (self, own_travel, chain2_load - chain1_load, len(rng2) - len(rng1)),
                (other, other_travel, chain1_load - chain2_load, len(rng1) - len(rng2)))

        return tuple(  # type: ignore - fixed length 4, built from a 4-tuple
            raw(t) for t in travels)
    #endregion

    #region Permutation (travel distance only)
    def cost_deltas_for_permutation(self, permutation: Sequence[int]) -> RawDeltaRecord:
        # WARNING: Must permute anyway to get the cost delta. Could be cheaper to apply the operator, compute, then unapply.
        if len(permutation) != len(self.path):
            raise ValueError("Permutation has wrong length")

        if set(permutation) != set(range(len(self.path))):
            raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

        path = self.path
        old_distance = self.total_distance()
        new_path = [self.first_visit] + [path[i] for i in permutation] + [self.last_visit]
        new_distance = sum(new_path[i].distance(new_path[i+1]) for i in range(len(new_path)-1))

        travel_delta = new_distance - old_distance

        # INTRA-ROUTE: distance and nothing else. No customer crosses a route boundary, so
        # load, count, start depot and vehicle all end where they started, and the whole
        # travel delta belongs to this one route.
        return RawDeltaRecord(travel_changes={self: travel_delta})
    #endregion

    #region Splitting this src_route
    def cost_deltas_for_split_at(self, split_index: int, refill_depot: Depot,
                                 new_route: Route) -> RawDeltaRecord:

        # `new_route` is the empty, unassigned route the split will fill -- the SAME object
        # split_at receives. Splitting creates a route, and the raw record keys transitions
        # on route objects, so the created one has to exist before pricing can describe it.
        path = self.path

        # split_index is the index of the new (second-half) route's first customer -- same
        # convention as split_at and split2_load below -- so the customer this function prices
        # the depot-stop insertion after (the first half's last customer) is at split_index - 1.
        split_customer = self.get_visit_at(split_index - 1)
        # use isinstance instead of is_customer_visit for linter's sanity
        if not isinstance(split_customer, CustomerVisit):
            # First split src_route must end with customer
            return RawDeltaRecord()

        if not split_customer.next_visit.is_customer_visit:
            # Second split src_route must begin with customer
            # Note: next_visit is guaranteed to exist since split_customer is a customer visit
            return RawDeltaRecord()

        vehicle = self.vehicle
        if vehicle is None:
            return RawDeltaRecord() #  Cannot split unassigned routes


        ## Compute each relevant delta

        # Travel
        travel_delta = split_customer.travel_delta_if_depot_stop_added_after_this(refill_depot)

        # No new vehicles will be activated, so we skip vehicle activation delta

        # ONE WALK over the tail, for load and distance together. The load sum was always
        # here; the distance sum rides along, so the split gains a second O(tail) quantity
        # without a second pass. split2_travel is everything the new route will own except its
        # own entry arc: the arcs between the tail customers, plus the arc to the end depot
        # that self is handing over.
        split2_load: Num = 0
        split2_travel: Num = 0
        previous = None
        for customer in path[split_index:]:
            split2_load += customer.demand
            if previous is not None:
                split2_travel += previous.distance(customer)
            previous = customer
        assert previous is not None, "split2 is empty; the guards above should have caught it"
        split2_travel += self.end_depot.distance(previous)

        split1_load = self.current_load - split2_load

        # new_route starts at refill_depot once split_at links it after self, so it owns that
        # entry arc too. What self loses is exactly what new_route gains, minus the priced
        # join, so self's share is the remainder of the total.
        new_route_travel = refill_depot.distance(path[split_index]) + split2_travel
        self_travel = travel_delta - new_route_travel

        # Two entries, and only two. The route AFTER self keeps its start depot: new_route was
        # constructed carrying self's ORIGINAL end depot, and it lands between them, so the
        # successor still starts where it started. refill_depot re-points the FIRST half only.
        split2_count = self.num_customers - split_index
        # self keeps its start depot and its vehicle, so it appears only in the two numeric
        # maps. new_route is CREATED: it gains a depot and a vehicle, so it appears in all four.


        assert split_index > 0 # We NEVER price wasteful splits. Caller must catch this degenerate case.
        assert split2_count > 0

        raw = RawDeltaRecord(
            travel_changes={self: self_travel, new_route: new_route_travel},
            load_changes={self: (self.current_load, split1_load),
                                new_route: (new_route.current_load, split2_load)},
            customer_deltas={self: (self.num_customers, split_index),
                                   new_route: (new_route.num_customers, split2_count)},
            start_depot_changes={new_route: (new_route.start_depot, refill_depot)},
            vehicle_changes={new_route: (new_route.vehicle, vehicle)})

        return raw
    #endregion

    #region Combining another src_route with this one
    def travel_delta_for_combine_with(self, other: Route) -> Num:
        # Note: new end depot comes from dest_route src_route. And we don't combine routes with themselves.
        if self is other:
            return 0

        if other == self.next_route:
            return self.travel_delta_for_combine_with_next()

        if other == self.prev_route:
            return self.travel_delta_for_combine_with_prev()

        # CAVEAT: if dest_route == self.prev_route and self is empty, then
        # prev_start->...->prev_last->start->last becomes prev_start->...->last. So must treat combines with previous src_route differently for travel computations.
        return self.travel_delta_for_combine_with_nonadjacent(other)

    def travel_delta_for_combine_with_nonadjacent(self, other: Route) -> Num:
        # Note: new end depot comes from dest_route src_route.
        assert self is not other, "Cannot combine with self"

        # Travel for dest_route's tail_distance was already accounted for.
        # This delta comes from a few changes:
        # 1) Other src_route: disconnected from its vehicle
        # 2) This src_route: end-1->end_depot becomes end-1->other_start+1
        # 3) Next src_route: start depot is swapped to dest_route.end_depot
        curr_visit_before_end = self.last_visit.prev_visit
        other_visit_after_start = other.first_visit.next_visit

        travel_delta = other.travel_delta_if_removed()

        old_distance = self.last_move_distance()
        new_distance = curr_visit_before_end.distance(other_visit_after_start)

        travel_delta += new_distance - old_distance

        next_route = self.next_route
        if isinstance(next_route, Route):
            travel_delta += next_route.first_visit.start_travel_delta_if_depot_swapped(other.end_depot)

        return travel_delta

    def travel_delta_for_combine_with_next(self) -> Num:
        other = self.next_route
        # Note: new end depot comes from dest_route src_route. And we don't combine inactive routes.
        assert other is not None, "Next src_route does not exist."
        assert self is not other, "Cannot combine with self"
        assert isinstance(other, Route), "Can only combine with Routes"

        # Combining with the immediate successor collapses the shared depot stop, which is TWO
        # visit objects at the same location: self's last_visit (end depot) and other's
        # first_visit (start depot). Both disappear, replaced by one direct edge from self's
        # last customer to other's first customer.
        # NOTE: self.last_visit.travel_delta_if_removed is NOT usable here -- it removes a
        # single node, and that node's next_visit is other.first_visit, sitting at the very
        # same location, so it always evaluates to exactly 0.
        # Both routes are guaranteed non-empty by the callers (CombineRoutes rejects empty
        # operands), so prev/next visits below are real customers.
        curr_visit_before_end = self.last_visit.prev_visit
        other_visit_after_start = other.first_visit.next_visit

        old_distance = self.last_move_distance() + other.first_move_distance()
        new_distance = curr_visit_before_end.distance(other_visit_after_start)

        return new_distance - old_distance

    def travel_delta_for_combine_with_prev(self) -> Num:
        other = self.prev_route
        # Note: new end depot comes from dest_route src_route.
        assert other is not None, "Previous src_route does not exist."
        assert self is not other, "Cannot combine with self"
        assert isinstance(other, Route), "Can only combine with Routes"

        # This one is by far the most complicated because of empty src_route interactions. Appending prev to end of self is a bit messy.

        # Neither empty:
        # Before: other_start->other_start+1->...->other_end->start+1->...->end-1->end->next_start+1
        # After: other_start->start+1->...->end-1->other_start+1->...->other_end->next_start+1

        # Other empty only:
        # Before: other_start->other_end->start+1->...->end-1->end->next_start+1
        # After:  other_start->start+1->...->end-1->other_start+1=other_end->next_start+1
        # COMPARE TO Neither empty: Just lose ->...->other_end - the tail of dest_route. But that was already counted, so no logical change!

        # Self empty (regardless of dest_route empty)
        # Before: other_start->other_start+1->...->other_end->end->next_start+1
        # After:  other_start->other_start+1->...->other_end->next_start+1 -> Equal to replacing self end depot with other_end!

        if self.is_empty:
            # Then combine_with_prev just removes this route, in effect: other_end->end pops out.
            return self.travel_delta_if_removed()

        # If self is not empty, Break it down:
        # 1) Route starts: Lose other_start->other_start+1 and other_end->start+1, gain other_start->start+1
        # 2) Path combine: Lose end-1->end, gain end-1->other_start+1
        # 3) Next src_route changed start: Lost end->next_start+1, gain other_end->next_start+1 (next changes start depot)
        curr_visit_before_end = self.last_visit.prev_visit
        curr_visit_after_start = self.first_visit.next_visit
        other_visit_after_start = other.first_visit.next_visit

        # 1) Route starts
        old_distance = other.first_move_distance() + self.first_move_distance()
        new_distance = other.first_visit.distance(curr_visit_after_start)  # Can't query start depot replace: if this src_route is empty you'll count new_start->end, which isn't used.
        travel_delta = new_distance - old_distance

        # 2) Path combine
        old_distance = self.last_move_distance()
        new_distance = curr_visit_before_end.distance(other_visit_after_start)

        travel_delta += new_distance - old_distance

        # 3) Next src_route changed start
        next_route = self.next_route
        if isinstance(next_route, Route):
            travel_delta += next_route.first_visit.start_travel_delta_if_depot_swapped(other.end_depot)

        return travel_delta

    def cost_deltas_for_combine_with(self, other: Route) -> RawDeltaRecord:
        if self is other:
            raise ValueError("Cannot combine a src_route with itself")

        # Call assumption: self and other are different and nonempty
        has_customers = self.has_customers
        other_has_customers = other.has_customers
        assert self is not other and has_customers and other_has_customers, "Cannot combine a src_route with itself"

        travel_delta = self.travel_delta_for_combine_with(other)

        # OTHER ENDS AT ZERO DISTANCE: combine_with empties its path and unlinks it, and an
        # unassigned empty route measures zero. Its cached total is the exact amount to remove,
        # so this side needs no walk.
        other_travel = -other.current_travel

        # UP TO THREE ROUTES MOVE, and only the first is obvious.
        #
        #   self        absorbs other's customers, so load and count rise. Its START DEPOT also
        #               moves when other is its PREDECESSOR: the chain is other -> self, so
        #               once other is gone self takes other's slot and therefore other's start
        #               depot. Claiming it unchanged is wrong, and the raw-record oracle caught
        #               exactly that on the adjacency="prev" cases.
        #   other       is emptied AND unlinked in the one call: load and count to zero, start
        #               depot to a VirtualDepot, vehicle to None.
        #   next route  inherits other's end depot, because combine_with gives self that end
        #               depot and a route's end depot IS the next route's start depot. Skipped
        #               when the next route IS other, which is about to disappear anyway.
        #   other's own successor inherits other's START depot, because unlinking other closes
        #               the gap in ITS chain. Only in the NON-ADJACENT case: when other is
        #               self's successor the two effects coincide (self ends up carrying other's
        #               end depot, which is what that successor already started at), and when
        #               other is self's predecessor the successor IS self, handled above.

        start_depot = self.start_depot
        other_start_depot = other.start_depot
        used_start_depot = self.used_start_depot
        other_used_start_depot = other.used_start_depot
        self_start = other_used_start_depot if self.prev_route is other else used_start_depot

        current_load = self.current_load
        loads: dict[Route, tuple[Num, Num]] = {
            self: (current_load, current_load + other.current_load),
            other: (other.current_load, 0)}
        counts: dict[Route, tuple[int, int]] = {
            self: (self.num_customers, self.num_customers + other.num_customers),
            other: (other.num_customers, 0)}
        start_depots: dict[Route, tuple[Depot, Depot]] = {}

        other_active = other.is_active
        split_legal = self.is_active or other_active
        assert split_legal, "Cannot price combine solely between inactive routes"

        if other_active:
            # Uncount other's start depot - it becomes empty and unassigned
            start_depots[other] = (other_used_start_depot, VIRTUAL_DEPOT)

        if self_start is not start_depot and self.vehicle is not None:
            start_depots[self] = (used_start_depot, self_start)

        vehicles: dict[Route, tuple[Vehicle | None, Vehicle | None]] = {
            other: (other.vehicle, None)}

        next_route = self.next_route
        if (isinstance(next_route, Route) and next_route is not other
                and next_route.start_depot != # type: ignore - Linter is an idiot. Gated by isinstance -_-
                other.end_depot):
            assert isinstance(next_route, Route)
            next_final_use_depot = other.end_depot if next_route.is_active else VIRTUAL_DEPOT
            start_depots[next_route] = (next_route.used_start_depot, next_final_use_depot)

        other_successor = other.next_route
        if (isinstance(other_successor, Route) and other_successor is not self
                and other is not next_route
                and other_successor.start_depot != # type: ignore - Linter is an idiot. Gated by isinstance -_-
                other_start_depot):
            assert isinstance(other_successor, Route)
            other_successor_final_use_depot = other_start_depot if other_successor.is_active else VIRTUAL_DEPOT
            start_depots[other_successor] = (other_successor.used_start_depot, other_successor_final_use_depot)

        # The entry-arc changes that belong to neighbours rather than to self or other. Both
        # are start-depot swaps, and both are already inside the priced total. Whatever the
        # total does not account for on other routes is self's, which is right by construction:
        # self absorbs other's whole path plus the join arc.
        travels: dict[Route, Num] = {}
        if other_travel:
            travels[other] = other_travel

        if other is not next_route and other is not self.prev_route:
            # Non-adjacent: other's own successor closes the gap other leaves behind.
            successor_travel = other.last_visit.end_travel_delta_if_route_removed()
            if successor_travel and isinstance(other_successor, Route):
                travels[other_successor] = travels.get(other_successor, 0) + successor_travel

        if isinstance(next_route, Route) and other is not next_route:
            swap_travel = next_route.first_visit.start_travel_delta_if_depot_swapped(
                other.end_depot)
            if swap_travel:
                travels[next_route] = travels.get(next_route, 0) + swap_travel

        self_travel = travel_delta - sum(travels.values())
        if self_travel:
            travels[self] = travels.get(self, 0) + self_travel
        travels = {route: delta for route, delta in travels.items() if delta}

        raw = RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                             load_changes=loads,
                             customer_deltas=counts,
                             start_depot_changes=start_depots,
                             vehicle_changes=vehicles)

        return raw
    #endregion

    #region Reversing/reassigning subpaths

    #region Reversing a subpath
    def cost_deltas_if_customer_chain_reversed(self, chain: Chain) -> RawDeltaRecord:
        rng = as_chain_range(chain)
        assert 0 <= rng.start and rng.stop <= self.num_customers and len(rng) > 1, (
            f"cost_deltas_if_customer_chain_reversed {rng} out of range for "
            f"{self.num_customers} customers, or too short to change anything.")

        path = self.path

        # Delta just disconnects ends and reconnects in reverse!
        first_customer = path[rng.start]
        last_customer = path[rng.stop - 1]

        # Old: prev->first->...->last->next
        # New: prev->last->...->first->next
        old_distance = first_customer.distance_in + last_customer.distance_out
        new_distance = first_customer.prev_visit.distance(last_customer) + last_customer.next_visit.distance(first_customer)

        # INTRA-ROUTE: the whole travel delta belongs to this one route.
        travel_delta = new_distance - old_distance
        return RawDeltaRecord(travel_changes={self: travel_delta})


    #endregion

    #endregion

    def cost_deltas_if_swapped_with_next_route(self) -> RawDeltaRecord:
        # These deltas come exclusively from changes in the start_depot of each src_route.
        # So? We simply ask the routes for the travel deltas when swapping their start depots.
        # This includes the src_route after next if it exists.
        # The routes affected are: this src_route, the next src_route, and the src_route after next.

        route1 = self
        route2 = self.next_route

        # isinstance, not `is not None`: next_route is None only when unassigned -- once
        # assigned it is a real Route OR the vehicle's LastRoute sentinel, and LastRoute has
        # no is_empty/end_depot/first_visit. A `is not None` check lets the sentinel through
        # and raises AttributeError two lines down. (route3 below already gets this right.)
        if not isinstance(route2, Route):
            if route2 is None:
                raise ValueError("No next src_route to swap with.")
            # route2 is the LastRoute sentinel: self is the vehicle's final route, so there
            # is nothing after it to swap with. No-op rather than an error, matching the
            # empty-route case below (soft rule on calculate, hard on operate).
            return RawDeltaRecord()

        if route1.is_empty or route2.is_empty:
            # Cannot swap with empty routes (soft rule on calculate, hard on operate)
            return RawDeltaRecord()

        # Before swap: routes are route0->route1->route2->route3
        # After swap: routes are route0->route2->route1->route3
        # So:
        # 1) src_route 1 starts at end of route2
        # 2) src_route 2 starts at original start for route1
        # 3) src_route 3 starts at end of route1

        end_depot_1 = route1.end_depot
        end_depot_2 = route2.end_depot
        route3 = route2.next_route

        # Load these once for efficiency
        route3_exists = isinstance(route3, Route)
        route1_first_visit = route1.first_visit
        route2_first_visit = route2.first_visit
        route3_first_visit = route3.first_visit if route3_exists else None # type: ignore

        start_depot_1 = route1.start_depot
        start_depot_2 = route2.start_depot
        start_depot_3 = route3.start_depot if route3_exists else VIRTUAL_DEPOT # type: ignore

        # TRAVEL DELTAS
        travel_delta_1 = route1_first_visit.start_travel_delta_if_depot_swapped(end_depot_2)
        travel_delta_2 = route2_first_visit.start_travel_delta_if_depot_swapped(start_depot_1)
        travel_delta_3 = route3_first_visit.start_travel_delta_if_depot_swapped(end_depot_1) if route3_exists else 0 # type: ignore

        # Already one piece per route. Keep them apart rather than summing.
        travels: dict[Route, Num] = {}
        if travel_delta_1:
            travels[route1] = travel_delta_1
        if travel_delta_2:
            travels[route2] = travel_delta_2
        if travel_delta_3 and route3_exists:
            assert isinstance(route3, Route)
            travels[route3] = travel_delta_3

        # Vehicle activation delta = 0: Vehicles are considered active if they have customers,
        # which is unaffected by src_route order.

        # Vehicle overloading and total amount of overloading are 0: src_route swapping within a vehicle does not affect src_route/vehicle overloading

        # Exactly the three start-depot moves the numbered comment above lists, and nothing
        # else: swapping two adjacent routes carries each one's customers with it, so load,
        # customer count and vehicle are all unchanged for every route involved.

        start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}
        if route1.is_active and start_depot_1 != end_depot_2:
            assert isinstance(start_depots, dict)
            start_depots[route1] = (start_depot_1, end_depot_2)
        if route2.is_active and start_depot_2 != start_depot_1:
            assert isinstance(start_depots, dict)
            start_depots[route2] = (start_depot_2, start_depot_1)
        if route3_exists and route3.is_active and start_depot_3 != end_depot_1: # type: ignore - route3 is a Route if route3_exists
            assert isinstance(route3, Route) and isinstance(start_depots, dict)
            start_depots[route3] = (start_depot_3, end_depot_1)

        if not start_depots:
            start_depots = NO_CHANGES

        return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                              start_depot_changes=start_depots)

    #endregion

    #endregion

    #region Basic object operations

    #region Linkage and internal data maintenance# We use only link_after and not link_before: Anytime a src_route links to a prior src_route, it inherits its start depot

    # Intermediate operations of Atomic linking/unlinking only done internally; must enforce:
    # An unassigned routes has no neighbors, and an assigned src_route has both neighbors
    def _link_after(self, route: Route | FirstRoute):
        # Create a single src_route link.
        self.prev_route = route
        route.next_route = self

        self.first_visit.replace_depot(route.end_depot)

    def _unlink_from_surrounding_routes(self):
        if self.prev_route is None:
            return # already unlinked

        assert self.next_route is not None

        self.next_route._link_after(self.prev_route)
        self.next_route = None
        self.prev_route = None

    def unlink_from_vehicle(self):
        # Call as part of popping from vehicle. Takes care of bookkeeping.
        # Note: depot usages update immediately when src_route start depots are swapped out! Ez bookkeeping
        if self.vehicle is None:
            return # No-op!

        # Update next_route depot and linkage
        self._unlink_from_surrounding_routes()

        # Unlink this src_route from the vehicle
        self.vehicle.routes.remove(self)

        self.set_start_depot(VIRTUAL_DEPOT)
        self.prev_route = None # type: ignore
        self.next_route = None # type: ignore
        self.vehicle = None # type: ignore

    def _add_to_vehicle(self, old_vehicle: Vehicle | None, new_vehicle: Vehicle):
        # Unlinks from current vehicle if needed, or from current position in vehicle otherwise.
        # Add to new vehicle and updates accounting if vehicle changed.
        # DOES NOT link to any src_route in the vehicle.
        assert new_vehicle is not None # Gatekept by callers

        if old_vehicle == new_vehicle:
            # Just link current prev<=>next in preparation to re-link to new location
            self._unlink_from_surrounding_routes()
        else:
            # Adding to a new vehicle
            if old_vehicle is not None:
                # Unlink from old vehicle if linked
                self.unlink_from_vehicle()

            # Add to new vehicle and Update accounting
            self.vehicle = new_vehicle
            new_vehicle.routes.add(self)

    def link_to_vehicle_before(self, other: Route | LastRoute):
        if other is self or other is self.next_route:
            return # Can't link before self; no-op if already before dest_route

        vehicle = other.vehicle
        if vehicle is None:
            raise ValueError("Target successor is not assigned to a vehicle!")

        # Ensure self is added to vehicle, unlinked from any routes.
        # Handles any required unlinking and accounting updates.
        self._add_to_vehicle(self.vehicle, vehicle)


        # Link src_route to target location:
        # Link src_route after dest_route's predecessor, and link dest_route src_route to after self
        assert other.prev_route is not None # assigned non-first routes have previous routes
        self._link_after(other.prev_route)
        other._link_after(self)

    def link_to_vehicle_after(self, other: Route | FirstRoute):
        if other is self or other is self.prev_route:
            return # Can't link after self; no-op if already after dest_route

        vehicle = other.vehicle
        if vehicle is None:
            raise ValueError("Target successor is not assigned to a vehicle!")

        # Ensure self is added to vehicle, unlinked from any routes.
        # Handles any required unlinking and accounting updates.
        self._add_to_vehicle(self.vehicle, vehicle)

        # Link src_route to target location:
        # Link dest_route's successor to after self, and link self to after dest_route
        # (order matters: self._link_after(other) overwrites other.next_route, so it must run
        # second or the first line would read the wrong, already-updated successor)
        assert other.next_route is not None # assigned non-first routes have previous routes
        other.next_route._link_after(self)
        self._link_after(other)

    def link_visits(self):
        # For use during copy or similar:
        # Relink visits without updating any accounting
        path = self.path

        if len(path) == 0:
            self.first_visit.next_visit = self.last_visit
            self.last_visit.prev_visit = self.first_visit
            return

        curr_visit = self.first_visit
        last_visit = self.last_visit

        for visit in path:
            # Assign src_route
            visit.route = self

            # link c <=> curr_visit
            curr_visit.next_visit = visit
            visit.prev_visit = curr_visit

            # Update curr_visit
            curr_visit = visit

        # Link last_visit with curr_visit (last customer if there are any, first_visit otherwise)
        curr_visit.next_visit = last_visit
        last_visit.prev_visit = curr_visit


    # IMPORTANT: Linking customers will only occur after inserting or deleting customers, currently.
    # If you wish to just update a customer's linkage data instead, use relink_customer.
    def link_customer(self, i: int):
        # Called at the end of insert or append operation
        path_len = self.path_len
        if i < 0 or i >= path_len:
            raise IndexError("Customer index out of range.")

        prev_visit = self.get_visit_at(i-1)
        c = self.get_visit_at(i)
        next_visit = self.get_visit_at(i+1)

        c.route = self

        c.prev_visit = prev_visit
        prev_visit.next_visit = c

        c.next_visit = next_visit
        next_visit.prev_visit = c

    def relink_customer(self, i: int):
        # Called at the end of insert or append operation
        path_len = self.path_len
        if i < 0 or i >= path_len:
            raise IndexError("Customer index out of range.")

        prev_visit = self.get_visit_at(i - 1)
        c = self.get_visit_at(i)
        next_visit = self.get_visit_at(i + 1)

        c.route = self

        c.prev_visit = prev_visit
        prev_visit.next_visit = c

        c.next_visit = next_visit
        next_visit.prev_visit = c

    @staticmethod
    def unlink_customer(customer: CustomerVisit):
        # Called at the end of remove operation
        customer.unlink_from_route()

    def unlink_customer_at(self, i: int):
        # Called at the end of pop operation
        if i >= self.path_len or i < 0:
            raise IndexError("Customer index out of range.")

        self.unlink_customer(self.path[i])

    #endregion

    #region Disposal
    def should_dispose(self):
        # This method returns true if the src_route should be disposed: it is trivial
        # Routes here can be disposed with 0 cost delta and thus don't require an operator or such an analog.
        return self.is_trivial

    def can_dispose(self):
        # Routes disposal can only be triggered by an SA operator - and only if they serve no customers.
        # This method returns true if src_route disposal won't eliminate customers from the working src_route.
        return self.is_empty

    def dispose(self):
        # Note: this may sometimes be called if the end depot mismatches the start depot. However, the src_route pop
        #   should take care of all accounting for depot src_route-starting-counting logic in any case.
        #   In this case, also, travel distances and (possibly) vehicle usage counts will be affected by disposal.
        #   pop_route calls unlink_from_vehicle - which helps with disposal.
        if self.vehicle is not None:
            self.unlink_from_vehicle()

    #endregion

    #region Change start and end depot
    def set_end_depot(self, new_end_depot: Depot):
        # last_visit.replace_node takes care of updating the next src_route's first depot too,
        # including all depot usage bookkeeping. So this is a one-liner!
        self.last_visit.replace_depot(new_end_depot)

    def set_start_depot(self, new_start_depot: Depot):
        # New depot is derived from "previous node" information during dest_route operations.
        # First_visit handles its depot usage and dest_route bookkeeping, this is a one-liner!
        self.first_visit.replace_depot(new_start_depot)
    #endregion

    #region Customer move operations
    def insert_customer(self, customer: CustomerVisit, index):
        # Just inserts the customer.
        self.path.insert(index, customer)
        self.link_customer(index)

    def append_customer(self, customer):
        # Just appends the customer.
        self.path.append(customer)
        self.link_customer(self.path_len-1)

    def remove_customer(self, customer):
        # Caution: This is more expensive than pop_customer_at:
        #   It requires an unordered search for customer in path, on top of
        #   the normal list removal cost.
        #   Updates start depot's "num_used" if the src_route becomes trivial post-remove.

        customer.unlink_from_route()
        self.path.remove(customer)

    def pop_customer_at(self, index: int) -> CustomerVisit:
        # Pops the src_route customer at index and returns it.
        self.unlink_customer_at(index)
        customer = self.path.pop(index)

        return customer

    #endregion

    def __copy__(self):
        new_route = Route.__new__(Route)

        # Copy path and node info
        new_route.path = [copy.copy(visit) for visit in self.path]
        new_route.first_visit = copy.copy(self.first_visit)
        new_route.last_visit = copy.copy(self.last_visit)

        # Link visits for new src_route without triggering any accounting
        new_route.link_visits()

        # Now link first and last visits. (link_visits doesn't link these because __init__ does instead.)
        new_route.first_visit.route = new_route
        new_route.last_visit.route = new_route

        # SKIP prev and next src_route linkage: MUST access copy routes via parent vehicle.
        # For an unassigned route (no parent vehicle to relink it), explicitly default these
        # to None rather than leaving the attribute unset (Route declares them as bare
        # annotations with no class-level default).
        new_route.prev_route = None
        new_route.next_route = None
        # Likewise for vehicle: Vehicle.__copy__ overwrites this for assigned routes, but an
        # unassigned copy would otherwise have no vehicle attribute at all.
        new_route.vehicle = None

        # Can't use count_load_change here: Parent vehicle already copies correct overload info during its copy
        new_route.current_load = self.current_load
        new_route.current_travel = self.current_travel

        # SKIP depot_route_starts: MUST be linked by FullSolution
        return new_route

    #endregion

    #region Composite object operations: Customer swap, Permute/subpermute, Split, Combine, Swap with next src_route

    def swap_customers(self, i: int, j: int):
        path = self.path
        path_len = len(path)

        if i>=path_len or j>=path_len:
            raise IndexError("Path index out of range")
        if i==j:
            return

        path[i].swap_customers(path[j])

    def swap_customers_with(self, i: int, other: Route, j: int):
        # Validation
        if self == other and i == j:
            return # No-op!

        if i>=self.path_len or j>=other.path_len or min(i,j) < 0:
            raise IndexError("Path index out of range")

        # Swap customers directly
        self.path[i].swap_customers(other.path[j])

    def permute(self, permutation: Sequence[int], start: int = 0):
        """
        Reorder path[start : start+len(permutation)] in place.

        `permutation` is RELATIVE to start: entry i names the source offset for new offset i.
        CS convention -- [2,3,4,1] means new is [path[2], path[3], path[4], path[1]], not
        "path[1] moves to 2".

        start defaults to 0, so a whole-path permutation is unchanged. A sub-range permutation
        touches only that range, which is what lets an operator reorder a short span of a long
        route without building a full-length identity array first.
        """
        path = self.path
        span_len = len(permutation)
        if span_len <= 1 or len(path) <= 1:
            return  # nothing to permute!

        if start < 0 or start + span_len > len(path):
            raise ValueError("Permutation range falls outside the path")

        if set(permutation) != set(range(span_len)):
            raise ValueError("Permutation indices must be in the range from 0 to its length - 1.")

        new_path = [path[start + i].source_customer for i in permutation]

        for i in range(span_len):
            path[start + i].replace_customer(new_path[i])

    def split_at(self, split_index: int, refill_depot: Depot, new_route: Route | None = None) -> Route:
        # Removes the customers at or after the index. Then returns a new src_route with those customers and
        # the given end depot. Idea is that vehicle will handle the insertion of the new src_route.
        # `new_route` IS the identity-preserving path that TODO(revert-identity) asked for:
        # pass the original object and it gets refilled with the tail customers instead of a
        # fresh one being constructed. CombineRoutes._revert_impl passes route2 through, so a
        # caller holding a reference across an apply -> revert cycle -- an evaluated Move's
        # operands, an undo stack, a debug re-evaluate -- still names a live route.
        path = self.path
        path_len = self.path_len

        if split_index < 0 or split_index >= path_len:
            raise IndexError("split_index out of range")

        if split_index == 0 or 1 >= path_len or path_len == split_index:
            raise ValueError("Invalid split: After split, both routes must have a customer.")

        # Make the new src_route. First customer of new src_route will link with new FirstVisit on creation.
        # Broken linkages will update on new src_route add.
        if new_route is None:
            # new_route is not a legal destination: make a new one
            new_route = Route(path[split_index:], self.end_depot)
        else:
            assert not (new_route.is_assigned or new_route.has_customers), "Invalid route specified for split: target route must be empty and unassigned"
            new_route.set_values(path = path[split_index:])

        # Remove the tail of the path from the original src_route, and update customer linkages.
        self.path = path[:split_index]
        self.relink_customer(split_index-1)
        new_route.relink_customer(0)

        # Replace end depot of this src_route with refill_depot
        # We use set_end_depot to ensure that all depot accounting is correct (and self.end_depot=next_route.start_depot
        # as expected) before we insert the new src_route after this one.
        self.set_end_depot(refill_depot)

        # Add new route after self
        new_route.link_to_vehicle_after(self)

        return new_route  # Return it for addition to all_routes

    def combine_with(self, other: Route):
        # other must have customers to relink at the boundary index below; is_empty (not just
        # is_trivial) is the real requirement -- an empty-but-not-trivial other (zero customers,
        # start_depot != end_depot) would relink out of range just the same.
        # Mirrors the split guard: split_at never produces an empty half, so combine --
        # its inverse -- must never consume one. self.is_trivial was too weak: an
        # empty-but-not-trivial self (no customers, start_depot != end_depot) passed here and
        # then failed on revert, because undoing the combine calls split_at(0, ...).
        if other.is_empty or self.is_empty:
            raise ValueError("Cannot combine using empty routes")

        if self is other:
            raise ValueError("Cannot combine a src_route with itself")

        # Operate before removing dest_route so that the remove operation sees the correct end depot - and thus correctly updates
        #   the end_depot for the next pop.
        #   ("pop" triggers "self.unlink_from_vehicle" - which will set the current start depot as the next src_route's
        #       start_depot, among dest_route key changes. So we need to ensure data is correct when we pop!)
        # Also, increment current vehicle's overload count if this src_route is newly overloaded. (Un-overloading is not possible since demands>0!)
        start_len = self.path_len

        self.path += other.path
        self.set_end_depot(other.end_depot)

        # Relink dest_route's first customer in self (links src_route ends together), and reassign others' routes as self
        self.relink_customer(start_len)
        # Relink the new final customer to SELF's last_visit too. The appended customers still
        # carry other's internal links, so without this the tail stays wired to
        # other.last_visit and self.last_visit.prev_visit keeps pointing at self's OLD last
        # customer -- which silently corrupts every delta computed off last_visit
        # (get_replacement_travel_delta, distance_in, ...). Only a no-op when other had
        # exactly 1 customer, in which case relink_customer(start_len) already did it.
        self.relink_customer(self.path_len - 1)
        for i in range(start_len+1, self.path_len):
            self.path[i].route = self

        other.unlink_from_vehicle() # Also uncounts its customers from the dest_route src_route's vehicle

        # Clear dest_route src_route
        other.set_values(path=[])

    # region Customer chain operations
    # Three paths, split by route relationship. They rewrite Customer VALUES in place wherever
    # they can (the trick permute already uses) rather than splicing the path list, because a
    # list splice is O(n) -- doing one per customer would make a k-chain O(k*n).
    def reverse_customer_chain(self, chain: Chain):
        rng = as_chain_range(chain)
        assert 0 <= rng.start and rng.stop <= self.num_customers, (
            f"reverse_customer_chain {rng} out of range for {self.num_customers} customers.")

        if len(rng) <= 1:
            return   # a chain of 0 or 1 reverses to itself

        path = self.path
        reversed_customers = [visit.source_customer for visit in reversed(path[rng.start:rng.stop])]
        for offset, customer in enumerate(reversed_customers):
            path[rng.start + offset].replace_customer(customer)

    def reassign_customer_chain(self, chain: Chain, dest: int, reverse: bool = False):
        # SAME-ROUTE move. No customer crosses a route boundary, so there is no load, depot or
        # vehicle accounting to do at all -- only the ordering changes. Both the chain and the
        # customers it displaces get rewritten in place across one contiguous span; everything
        # outside that span is untouched, where a remove-then-insert would shift the tail twice.
        #
        # `dest` is the chain's start index AFTER removal, matching reassign-customer semantics.
        rng = as_chain_range(chain)
        k = len(rng)
        start = rng.start
        assert 0 <= start and rng.stop <= self.num_customers, (
            f"reassign_customer_chain {rng} out of range for {self.num_customers} customers.")
        assert 0 <= dest <= self.num_customers - k, (
            f"reassign_customer_chain dest={dest} out of range for a {k}-chain in "
            f"{self.num_customers} customers.")

        path = self.path
        if dest != start and k > 0:
            # Read every source value BEFORE writing any of them: the span being rewritten is
            # the same span being read from.
            if dest < start:
                # Chain moves left; the customers it passes shuffle right by k.
                span_start = dest
                new_customers = ([path[i].source_customer for i in rng] +
                                 [path[i].source_customer for i in range(dest, start)])
            else:
                # Chain moves right; the customers it passes shuffle left by k.
                span_start = start
                new_customers = ([path[i].source_customer for i in range(start + k, dest + k)] +
                                 [path[i].source_customer for i in rng])

            for offset, customer in enumerate(new_customers):
                # ..._from_same_route skips the load bookkeeping, which is exactly right here:
                # the demand never leaves this route, so the full replace_customer would add
                # and subtract the same amount.
                path[span_start + offset].replace_customer(customer)

        if reverse:
            self.reverse_customer_chain(range(dest, dest + k))

    def remove_customer_chain(self, chain: Chain) -> list[CustomerVisit]:
        # CROSS-ROUTE move, first half. Returns the detached visits for insert_customer_chain.
        rng = as_chain_range(chain)
        k = len(rng)
        if k == 0:
            return []
        assert 0 <= rng.start and rng.stop <= self.num_customers, (
            f"remove_customer_chain {rng} out of range for {self.num_customers} customers.")

        path = self.path
        removed = path[rng.start:rng.stop]

        # Capture the NEIGHBOURS before the splice. After it, the only record of the boundary
        # is on the removed visits themselves, and those links are about to be cleared.
        prev_visit = removed[0].prev_visit
        next_visit = removed[-1].next_visit

        path[rng.start:rng.stop] = []
        prev_visit.next_visit = next_visit
        next_visit.prev_visit = prev_visit

        for visit in removed:
            visit.route = None
        removed[0].prev_visit = None    # type: ignore - None only until the matching insert
        removed[-1].next_visit = None   # type: ignore - None only until the matching insert
        return removed

    def insert_customer_chain(self, visits: list[CustomerVisit], dest_idx: int, reverse: bool = False):
        # CROSS-ROUTE move, second half. Mirrors insert_customer, including the order of the
        # three accounting calls: all of them read path_len, so all precede the splice.
        k = len(visits)
        if k == 0:
            return
        assert 0 <= dest_idx <= self.num_customers, (
            f"insert_customer_chain dest_idx={dest_idx} out of range for "
            f"{self.num_customers} customers.")

        # Reverse the LIST before splicing rather than calling reverse_customer_chain after.
        # Reversing afterward rewrites source_customer in every slot -- a second pass, plus
        # per-visit load bookkeeping that nets to zero within one route. Reversing the list
        # puts the visits in already ordered, so link_customer relinks them once.
        self.path[dest_idx:dest_idx] = reversed(visits) if reverse else visits
        for i in range(dest_idx, dest_idx + k):
            self.link_customer(i)

    def swap_customer_chains_with(self, chain: Chain, other: Route, other_chain: Chain,
                                  rev1: bool = False, rev2: bool = False):
        # This route's chain lands in other's slot (reversed if rev1); other's lands here
        # (reversed if rev2). Callers must have rejected empty and overlapping chains.
        rng1, rng2 = as_chain_range(chain), as_chain_range(other_chain)
        k1, k2 = len(rng1), len(rng2)

        if k1 == k2:
            # Slots line up, so rewrite values in place -- no splice, no index shift. Read
            # every source BEFORE writing: the two ranges are also the two destinations.
            path1, path2 = self.path, other.path
            src1 = [path1[i].source_customer for i in rng1]
            src2 = [path2[j].source_customer for j in rng2]
            if rev1:
                src1.reverse()
            if rev2:
                src2.reverse()
            for offset in range(k1):
                path1[rng1.start + offset].replace_customer(src2[offset])
                path2[rng2.start + offset].replace_customer(src1[offset])
            return

        if self is not other:
            visits1 = self.remove_customer_chain(rng1)
            visits2 = other.remove_customer_chain(rng2)
            self.insert_customer_chain(visits2, rng1.start, rev2)
            other.insert_customer_chain(visits1, rng2.start, rev1)
            return

        # Same route, unequal sizes. Remove the LATER chain first so the earlier chain's
        # indices stay valid, then rebuild: the later chain's customers take the earlier slot.
        if rng1.start < rng2.start:
            early, late, early_rev, late_rev = rng1, rng2, rev1, rev2
        else:
            early, late, early_rev, late_rev = rng2, rng1, rev2, rev1

        gap = late.start - early.stop
        late_visits = self.remove_customer_chain(late)
        early_visits = self.remove_customer_chain(early)

        self.insert_customer_chain(late_visits, early.start, late_rev)
        # The untouched middle segment (length gap) now sits directly after the inserted block.
        self.insert_customer_chain(early_visits, early.start + len(late) + gap, early_rev)
    # endregion


    def __str__(self):
        return (str(self.start_depot.dID) + '->' +
                '->'.join(str(customer.cID) for customer in self.path) + '->' +
                str(self.end_depot.dID))

    def __repr__(self):
        return str(self)

    #endregion
#endregion
