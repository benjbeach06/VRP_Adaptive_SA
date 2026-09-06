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
