import copy
import random
from bisect import bisect_left
from ftplib import all_errors

from itertools import chain

from numpy import cumsum, ndarray

#from Temp_TimeIt import num_trials

from_iterable = chain.from_iterable

from typing import cast, Any, List, DefaultDict, Iterable, Iterator, Sequence, Collection
from collections import defaultdict
from math import hypot, ceil

from functools import lru_cache
from typing import NamedTuple

from abc import ABC, abstractmethod

Num = float | int

#region Global helper functions

def combine_defaultdicts_by_value_sum[T1: int, T2: Num](dict1: defaultdict[T1, T2], dict2: defaultdict[T1, T2]) -> defaultdict[T1, T2]:
    # Copy-combines and returns new
    result = defaultdict(dict1.default_factory)

    all_keys = dict1.keys() | dict2.keys()

    for key in all_keys:
        result[key] = dict1[key] + dict2[key]

    return result

def append_new_defaultdict_by_value_sum(dict1: defaultdict, dict2: defaultdict) -> None:
    for key in dict2.keys():
        dict1[key] += dict2[key]


@lru_cache(maxsize=10000)
def dist(loc1: tuple[Num, Num], loc2: tuple[Num, Num]) -> Num:
    (x1, y1) = loc1
    (x2, y2) = loc2
    return hypot(x2 - x1, y2 - y1)


def sub_permute_list(subpermutation: Sequence[int], lst: List):
    # Applies subpermutation of list in place.
    if len(subpermutation) > len(lst):
        raise ValueError("Subpermutation is longer than the lst")
    if len(subpermutation) <= 1:
        return

    subpermutation_set = set(subpermutation)
    lst_len = len(lst)
    if len(subpermutation) != len(subpermutation_set):
        raise ValueError("Entries of Subpermutation are not unique.")
    if not all(0 <= i < lst_len for i in subpermutation):
        raise ValueError("Subpermutation indices must be in the range from 0 to the given list length - 1.")

    start = lst[subpermutation[0]]
    for i in range(len(subpermutation) - 1):
        lst[subpermutation[i]] = lst[subpermutation[i + 1]]
    lst[subpermutation[-1]] = start

def sub_permute_path(subpermutation: Sequence[int], path: List[CustomerVisit]):
    # Applies subpermutation of list in place.
    if len(subpermutation) > len(path):
        raise ValueError("Subpermutation is longer than the lst")
    if len(subpermutation) <= 1:
        return


    subpermutation_set = set(subpermutation)
    path_len = len(path)
    if len(subpermutation) != len(subpermutation_set):
        raise ValueError("Entries of Subpermutation are not unique.")
    if not all(0 <= i < path_len for i in subpermutation):
        raise ValueError("Subpermutation indices must be in the range from 0 to the given list length - 1.")

    curr_visit = path[subpermutation[0]]
    start_customer = curr_visit.source_customer
    for i in range(len(subpermutation) - 1):
        # Example: subperm = 1, 3, 5 -> put 3 in 1, then 5 in 3. Then need to put original 1 in 5 (after loop).
        next_visit = path[subpermutation[i + 1]]
        curr_visit.replace_customer_with_customer_from_same_route(next_visit.source_customer)
        curr_visit = next_visit

    curr_visit.replace_customer_with_customer_from_same_route(start_customer)

#endregion

class ObjectiveTermDelta(NamedTuple):
    travel_distance: Num = 0
    vehicles_activated: int = 0
    depots_activated: int = 0
    total_route_overload: Num = 0
    vehicles_overloaded: int = 0

    def __pos__(self) -> ObjectiveTermDelta:
        return ObjectiveTermDelta(self.travel_distance, self.vehicles_activated, self.depots_activated, self.total_route_overload, self.vehicles_overloaded)

    def __neg__(self) -> ObjectiveTermDelta:
        return ObjectiveTermDelta(-self.travel_distance, -self.vehicles_activated, -self.depots_activated, -self.total_route_overload, -self.vehicles_overloaded)

    def __add__(self, other: Any) -> Any:
        if isinstance(other, ObjectiveTermDelta):
            return ObjectiveTermDelta(self.travel_distance + other.travel_distance, self.vehicles_activated + other.vehicles_activated,
                                      self.depots_activated + other.depots_activated, self.total_route_overload + other.total_route_overload, self.vehicles_overloaded + other.vehicles_overloaded)

        if isinstance(other, tuple):
            return tuple.__add__(self, other)

        return NotImplemented

    def __sub__(self, other: ObjectiveTermDelta) -> ObjectiveTermDelta:
        return self + (-other)

    def get_cost_delta(self, travel_unit_cost: Num = 0.0, vehicle_cost: Num = 0.0, depot_cost: Num = 0.0, route_overload_penalty: Num = 0.0, vehicle_overload_penalty: Num = 0.0) -> Num:
        """
            Returns the change in cost implied by the deltas stored here, given objective coefficients.
        """
        return travel_unit_cost * self.travel_distance + vehicle_cost * self.vehicles_activated +\
            depot_cost * self.depots_activated + route_overload_penalty * self.total_route_overload +\
            vehicle_overload_penalty * self.vehicles_overloaded

    def get_cost_improvement(self, travel_unit_cost: Num = 0.0, vehicle_cost: Num = 0.0, depot_cost: Num = 0.0, overload_penalty: Num = 0.0, vehicle_overload_penalty: Num = 0.0, minimizing: bool = True) -> Num:
        """
           Returns the improvement value (positive = better) based on cost deltas and weights.
           If minimizing: improvement = -cost_delta (i.e., cost reduction is good).
           If maximizing: improvement = +cost_delta (i.e., increase is good).
        """
        sign = -1 if minimizing else 1
        return sign * self.get_cost_delta(travel_unit_cost, vehicle_cost, depot_cost, overload_penalty, vehicle_overload_penalty)

#region Core node definitions
class Node:
    location: tuple[Num, Num]

    def __init__(self, location: tuple[Num, Num], **kwargs):
        self.location = location

    def distance(self, other: Node | None) -> Num:
        if other is None: return 0 # Trick to help with type safety: distance with None is 0 (e.g. distance with prev visit but prev visit is None)
        return dist(self.location, other.location)

    def __copy__(self):
        cls = self.__class__

        # We bypass constructor since inherited classes may have different constructor arguments
        new_node = cls.__new__(cls)

        # We overwrite _copy_data when we need more data, leaving __copy__ alone
        new_node._copy_data(self)

        return new_node

    def _copy_data(self, source: Node):
        self.location = source.location

    #region  Convenience methods to check if a Node is a specific subclass.
    # Also, a nice reference for Node's subclasses
    @property
    def is_customer(self) -> bool:
        return isinstance(self, Customer)

    @property
    def is_depot(self) -> bool:
        return isinstance(self, Depot)

    @property
    def is_virtual_depot(self) -> bool:
        return isinstance(self, VirtualDepot)

    @property
    def is_first_route_visit(self) -> bool:
        return isinstance(self, FirstRouteVisit)

    @property
    def is_last_route_visit(self) -> bool:
        return isinstance(self, LastRouteVisit)

    @property
    def is_customer_visit(self) -> bool:
        return isinstance(self, CustomerVisit)
    #endregion

_exNode = Node((0,0))
_exNodeVarKeys = vars(_exNode).keys()


class Depot(Node):
    def __init__(self, dID: int=0, location: tuple[Num, Num]=(0, 0), supply_limit: int=-1, vehicle_count: int=-1, **kwargs):
        super().__init__(location=location, **kwargs)
        self.dID: int = dID
        self.supply_limit: Num = supply_limit
        self.vehicle_count: int = vehicle_count

    def _copy_data(self, source: Node):
        assert isinstance(source, Depot)

        super()._copy_data(source)
        self.dID = source.dID
        self.supply_limit = source.supply_limit
        self.vehicle_count = source.vehicle_count

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"DEP{self.dID}"

_exDepot = Depot(dID=0, location=(0, 0))
_exDepot_vars = vars(_exDepot).keys()

# Placeholder end depot for solution builders to pass into Route(...) while a route is still
# under construction and its real end depot hasn't been decided yet (e.g. Solver.make_initial_solution,
# where customers are appended before a real end depot is chosen). Deliberately a real Depot, not a
# VirtualDepot: at that point the route may already have real customers, so it isn't "virtual"/
# unassigned in the sense that skips depot-usage accounting -- it's just end-undecided. Always
# replaced by a real depot via set_end_depot before the route is added to a vehicle. Route itself
# takes end_depot as a required, non-optional argument -- this branching belongs in the builder,
# not in the core data model's hot construction path.
DEFAULT_DEPOT = Depot(dID=-1, location=(0, 0), supply_limit=-1, vehicle_count=-1)


class VirtualDepot(Depot):
    def __init__(self, **kwargs):
        super().__init__(dID=-1, **kwargs)

    def __eq__(self, other):
        # All virtual depots are treated as equal: just the placeholder depot
        # Result is True if both are virtual; matches object.__eq__ otherwise:
        # Cases are:
        # 1) If self is virtual, and dest_route is too, then this __eq__ is called and True is returned
        # 2) If self is virtual, and dest_route is not, this method is called and returns False (matches object.__eq__)
        # 3) if self is not virtual, object.__eq__ is called
        return isinstance(other, VirtualDepot)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"(ᅲ_ᅲ)"


class Customer(Node):
    cID: int
    demand: Num

    def __init__(self, cID:int=0, location: tuple[Num, Num]=(0, 0), demand: Num=5, **kwargs):
        super().__init__(location=location, **kwargs)
        self.cID = cID
        self.demand = demand

    def _copy_data(self, source: Node):
        assert isinstance(source, Customer)
        super()._copy_data(source)

        self.cID = source.cID
        self.demand = source.demand

    def __str__(self):
        return f"c{self.cID}"

    def __repr__(self):
        return str(self)

_exCustomer = Customer(cID=0, location=(0, 0))
_exCustomer_vars = vars(_exCustomer).keys()

#endregion

#region Route visit definitions
class RouteVisit(Node, ABC):
    """
    Abstraction: A visit in the src_route; also inherits from the proper Node type to mirror its fields
    A src_route knows its FirstRouteVisit, LastRouteVisit, and the path of CustomerVisits in between (as a list)
    Advantages over customer-is-a-visit and depot-is-just-a-src_route-number:
      1) To swap 2 visits, you just swap the underlying nodes - no re-linking required unless adding/removing visits
      2) To permute/reverse visits, you can just reassign the nodes for all customers in the range to permute/reverse
      3) To swap depots for a src_route, the corresponding RouteVisit can directly query info from its parent depot
    """

    # Annotations only -- initialized per-instance below (see FullSolution for why defaults here
    # would be shared class state). next_visit is deliberately NOT initialized anywhere:
    #   - LastRouteVisit overrides it as a read-only property (derived from the next route), so
    #     assigning it on every RouteVisit would raise AttributeError.
    #   - CustomerVisit and FirstRouteVisit narrow it to a non-Optional type ("never None"), so
    #     seeding it with None would contradict their own declared invariant.
    # Every construction path links it immediately (Route.__init__ -> populate_derived_data, or
    # insert/append -> link_customer), so there is no window where it is read unset.
    route: Route | None
    prev_visit: RouteVisit | None
    next_visit: RouteVisit | None

    # Populate on linkage
    depot_num_uses: DefaultDict[Depot, int]


    def __init__(self, node: Node, **kwargs):
        assert 'location' not in kwargs or kwargs['location'] == node.location, \
            "location mismatch between node and forwarded kwargs"
        kwargs.setdefault('location', node.location)
        super().__init__(**kwargs)

        # Subclasses overwrite route (and link the visits) after calling super().__init__().
        self.route = None
        self.prev_visit = None

    #region Objective and state-related computations
    # We choose not to use full objective deltas here: full related processing done in Route
    @property
    def distance_in(self) -> Num:
        return self.distance(self.prev_visit)

    @property
    def distance_out(self) -> Num:
        return self.distance(self.next_visit)

    @property
    def distance_surrounding(self) -> Num:
        return self.distance_in + self.distance_out

    @property
    def distance_if_removed(self) -> Num:
        assert self.prev_visit is not None, "Cannot remove nodes at start or end of vehicle or unassigned src_route path."
        return self.prev_visit.distance(self.next_visit)

    @property
    def travel_delta_if_removed(self) -> Num:
        assert self.prev_visit is not None, "Cannot remove nodes at start or end of vehicle or unassigned src_route path."
        # Change to current-src_route travel distance if removing this from src_route
        old_length = self.distance_surrounding
        new_length = self.distance_if_removed
        return new_length - old_length

    def is_adjacent_with(self, other: RouteVisit) -> bool:
        return other == self.prev_visit or other == self.next_visit

    def travel_delta_if_inserting_customer_before_this(self, new_customer: Customer) -> Num:
        # Change to src_route travel distance if inserting new_customer before this
        old_length = self.distance_in
        new_length = new_customer.distance(self.prev_visit) + self.distance(new_customer)
        return new_length - old_length

    def change_depot_uses(self, depot: Depot, num_uses_delta: int):
        if depot.is_virtual_depot:
            raise ValueError("Virtual depots cannot be used.")

        self.depot_num_uses[depot] += num_uses_delta

    #endregion

    #region Object operations

    def _copy_data(self, source: Node):
        # Nothing to copy except node data - location: dest_route Visit fields are linkages.
        super()._copy_data(source)
    #endregion


class CustomerVisit(Customer, RouteVisit):
    prev_visit: RouteVisit # Prev and next visits are guaranteed to exist for customers linked to a src_route.
    next_visit: RouteVisit # CustomersVisits are never unlinked more than temporarily to move between routes.

    def __init__(self, customer: Customer):
        customer_fields = vars(customer).copy()
        super().__init__(node=customer, **customer_fields)
        self.source_customer = customer


    #region Current state
    def is_last_customer_in_route(self) -> bool:
        return self.prev_visit.is_first_route_visit and self.next_visit.is_last_route_visit
    #endregion

    #region Delta computations

    def travel_delta_if_customer_replaced(self, new_customer: Customer) -> Num:
        old_length = self.distance_surrounding
        new_length = self.prev_visit.distance(new_customer) + new_customer.distance(self.next_visit)
        return new_length - old_length

    def travel_delta_if_swapped_with(self, other: CustomerVisit) -> Num:
        # Change to current-src_route travel distance if swapping customers with another CustomerVisit
        if not self.is_adjacent_with(other):
            return self.travel_delta_if_customer_replaced(other) + other.travel_delta_if_customer_replaced(self)

        if other == self.next_visit:
            prev = self.prev_visit
            nxt = other.next_visit

            old_distance = self.distance_in + other.distance_out
            new_distance = prev.distance(other) + self.distance(nxt)

        else: # dest_route == self.prev_visit
            prev = other.prev_visit
            nxt = self.next_visit

            old_distance = other.distance_in + self.distance_out
            new_distance = prev.distance(self) + other.distance(nxt)

        return new_distance - old_distance

    # Route splits
    def travel_delta_if_depot_stop_added_after_this(self, depot_stop: Depot) -> Num:
        next_visit = self.next_visit
        # ASSUME: this is part of a general split delta conversation. Verification that next_visit is a customer
        # has already been done. (We don't want to re-verify this several times.)

        # Add path self->depot->next_visit instead of self->next_visit
        old_distance = self.distance_out
        new_distance = self.distance(depot_stop) + depot_stop.distance(next_visit)
        return new_distance - old_distance

    # For src_route splits: new depot will activate, no need to calculate depot usage changes here. Vehicles won't activate/deactivate.
    # New overloads need to be computed at the src_route level, as full demand lists before and after must be summed

    # Reminder: "Route uses its depot" = "Route has customers and is assigned"
    def will_decrement_depot_usage_if_removed(self) -> bool:
        # If there is no src_route, the operation is invalid
        # If the src_route is inactive, depot usage is already not counted
        route = self.route
        if route is None or route.is_inactive:
            return False

        # If we're here: the src_route is active - so depot usage decrements if the src_route will be inactive
        return route.is_inactive_after_customer_remove()

    def will_deactivate_depot_if_removed(self) -> bool:
        prev_visit: FirstRouteVisit = self.prev_visit # type: ignore # It will only be touched if this customer is the last one, in which case prev is a first visit.
        return self.will_decrement_depot_usage_if_removed() and prev_visit.num_routes_starting_here == 1

    def current_route_load_delta_if_swapped_with(self, other: CustomerVisit) -> Num:
        # Can reduce numerical error compared to "always subtract" if in same src_route:
        # (a-b) + (b-a) may evaluate to a small nonzero value due to numerical errors
        return 0 if self.route == other.route else other.demand - self.demand

    #endregion

    #region Object operations

    def replace_customer_with_customer_from_same_route(self, new_customer: Customer):
        # Called only as part of an intra-src_route swap or permutation. Skips load change computations.

        # Reason to copy values instead of just mirroring a reference: cost comps will happen much more frequently than node replacements.
        # Thus, copying values ("is a" node) removes a layer of indirection

        # 1. Update fields for this visit to match the new customer
        node_fields = vars(new_customer)
        for key in _exCustomer_vars:
            setattr(self, key, node_fields[key])

        # 2. Update the source customer for this visit
        self.source_customer = new_customer

    def replace_customer(self, new_customer: Customer):
        # Reason to copy values instead of just mirroring a reference: cost comps will happen much more frequently than node replacements.
        # Thus, copying values ("is a" node) removes a layer of indirection

        # 1. Update src_route's loading and overloading info. MUST do before changing the fields!
        self.swap_demand_from_route(new_customer)

        # 2. Update fields for this visit to match the new customer
        node_fields = vars(new_customer)
        for key in _exCustomer_vars:
            setattr(self, key, node_fields[key])

        # 3. Update the source customer for this visit
        self.source_customer = new_customer

    def swap_customers(self, other: CustomerVisit):
        """
        Swap customers with dest_route node
        """
        curr_customer = self.source_customer
        other_customer = other.source_customer

        if self.route != other.route:
            self.replace_customer(other_customer)
            other.replace_customer(curr_customer)
        else:
            # Save some computation time: intra-src_route swaps can skip computations of load change deltas.
            self.replace_customer_with_customer_from_same_route(other_customer)
            other.replace_customer_with_customer_from_same_route(curr_customer)

    def add_demand_to_route(self):
        route = self.route
        if route is not None:
            route.count_load_change(self.demand)

    def remove_demand_from_route(self):
        route = self.route
        if route is not None:
            route.count_load_change(-self.demand)

    def swap_demand_from_route(self, other: Customer):
        # Swap load to dest_route's load, and update vehicle overloading info
        route = self.route

        if route is not None:
            load_delta = other.demand - self.demand
            route.count_load_change(load_delta)

    def unlink_from_route(self):
        # Only unlinks src_route and uncounts src_route from vehicle.
        # Does not process loading changes or vehicle accounting, since some of those operations
        # must be performed before the src_route's path is mutated.
        if self.route is None:
            raise ValueError(f"Cannot unlink CustomerVisit {self.cID}: it is already unlinked!")

        # If it's the last in the src_route, the src_route goes inactive and stops using its start depot.
        # NOTE: this is the USAGE-COUNT question ("does depot_num_uses drop by 1"), NOT the
        # activation question ("does the depot go from used to unused"). Gating this on
        # will_deactivate_depot_if_removed() instead would skip the decrement whenever 2+ routes
        # start at that depot, leaving depot_num_uses permanently too high.
        if self.will_decrement_depot_usage_if_removed():
            self.prev_visit.uncount_route_depot_use() # type: ignore - If it decrements: src_route exists and this is its only customer, so prev visit is a FirstRouteVisit

        # Link neighbors
        prev_visit = self.prev_visit
        next_visit = self.next_visit

        prev_visit.next_visit = next_visit
        next_visit.prev_visit = prev_visit

        # Unlink self from src_route
        self.route = None
        self.prev_visit = None # type: ignore # None only for a short bit
        self.next_visit = None # type: ignore # none only for a short bit

    def _copy_data(self, source: Node):
        assert isinstance(source, CustomerVisit)

        # Copy only customer data fields (via super()) and source_depot
        self.source_customer = source.source_customer

        # Note: This calls both Customer and RouteVisit versions of _copy_data
        super()._copy_data(source)

    def __str__(self):
        return str(self.source_customer)

    def __repr__(self):
        return str(self)

    #endregion


class FirstRouteVisit(Depot, RouteVisit):
    # NOTE: Core operations can only focus on changing where a src_route ends, not starts.
    # BUT changing where one src_route ends for a vehicle necessarily changes where the next starts
    prev_visit: LastRouteVisit | None # Prev visit either None or part of previous src_route
    next_visit: CustomerVisit | LastRouteVisit # Next visit never None

    def __init__(self, depot: Depot, route: Route):
        # Restrict to just fields in base Depot class to prevent possible inheritance collisions
        depot_fields = {k: v for k, v in vars(depot).items() if k in _exDepot_vars}

        super().__init__(node=depot, **depot_fields)
        self.source_depot = depot

        self.route: Route = route

        # When this is initializing: the src_route will not yet be assigned to a vehicle, so the depot is not counted.
        # This is a part of ensuring that unused routes do not contribute to the solution

    #region Current state
    def distance(self, other: Node | None):
        if self.source_depot.is_virtual_depot:
            return 0
        return super().distance(other)

    @property
    def num_routes_starting_here(self):
        return self.depot_num_uses[self.source_depot]

    @property
    def prev_node(self) -> LastRouteVisit | None:
        if self.route is not None:
            if isinstance(self.route.prev_route, Route):
                return self.route.prev_route.last_visit

        return None

    @property
    def route_is_assigned(self):
        # Invariant: we enforce that a src_route is assigned iff its start visit's source depot is a real depot.
        # Unassigned routes end somewhere but start nowhere.
        # Assigning a src_route to a vehicle will set source_depot to the current vehicle depot at the point of assignment:
        # Either the starting depot or the end of the previous src_route
        return not self.source_depot.is_virtual_depot

    @property
    def route_is_empty(self):
        # A src_route is empty if it has no customers - vID.e. the node after the start node is a Depot
        # Empty routes have really only 1 use case: move a starting vehicle to another Depot to stock up,
        # if the starting depot has too much strain on its resources and the ending depot needs an extra vehicle
        # NOTE: An unassigned src_route still has the FirstRouteVisit pointing to the first customer (or src_route last visit).
        # It's just that the first visit's source depot will be a VirtualDepot in that case
        return self.next_visit.is_last_route_visit

    @property
    def route_is_trivial(self):
        # A src_route is trivial if it is empty and the start and end depots match. A src_route must be assigned to be trivial!
        next_node: LastRouteVisit = self.next_visit # type: ignore
        return self.route_is_empty and self.depot_is(next_node.source_depot)

    def depot_is(self, node: Depot):
        return self.source_depot == node
    #endregion

    #region Delta computations
    # Reminder: "Route is active" = "src_route moves" and "src_route's vehicle has customers"
    # Reminder 2: "Route uses its start depot" = "Route is active"
    def will_depot_swap_decrement_current_depot_usage(self, new_depot: Depot):
        # Current depot usage decreases exactly when the src_route is active and the depot changes (including to virtual)
        return self.source_depot != new_depot and self.route.is_active

    def will_depot_swap_increment_new_depot_usage(self, new_depot: Depot):
        # Next depot usage increases exactly when the 1) depot changes to a non-virtual one, and 2) the src_route will be active after the change (new depot increments if will be active)
        # Note: "to a non-virtual one" skipped: is_active_after_start_depot_swap requires new_depot is not virtual explicitly in the logic
        return self.source_depot != new_depot and self.route.is_active_after_start_depot_swap(new_depot)

    def num_depot_usage_deltas_if_depot_swapped(self, new_depot: Depot) -> defaultdict[Depot, int]:
        curr_delta = -self.will_depot_swap_decrement_current_depot_usage(new_depot)
        new_delta = self.will_depot_swap_increment_new_depot_usage(new_depot)

        depot_num_use_deltas = defaultdict(int)

        # Assign deltas, but only to non-virtual depots (those deltas would be 0 anyway)
        if self.route_is_assigned:
            depot_num_use_deltas[self.source_depot] = curr_delta

        if not new_depot.is_virtual_depot:
            depot_num_use_deltas[new_depot] = new_delta

        return depot_num_use_deltas

    def start_travel_delta_if_depot_swapped(self, new_node: Depot) -> Num:
        # Change to src_route travel distance if replacing the node here with a new one
        old_length = self.distance_out
        new_length = new_node.distance(self.next_visit)
        return new_length - old_length

    def start_travel_delta_if_route_removed(self):
        if self.route_is_trivial or self.source_depot.is_virtual_depot:
            return 0

        # If src_route is removed: connection first->next no longer occurs.
        # LastRouteVisit can handle the delta from any change in start depot for the next src_route
        return -self.distance(self.next_visit)

    def travel_delta_if_inserting_customer_before_this(self, new_customer: Customer):
        # Change to src_route travel distance if inserting new_customer before this
        raise ValueError("Cannot insert a node before a first src_route visit.")

    #endregion

    #region Object operations

    def count_route_depot_use(self):
        self.change_depot_uses(self.source_depot, 1)

    def uncount_route_depot_use(self):
        self.change_depot_uses(self.source_depot, -1)

    def change_my_depot_uses(self, num_uses_delta: int):
        self.change_depot_uses(self.source_depot, num_uses_delta)

    def replace_depot(self, new_depot: Depot):
        # If the depot is unchanged, return or both current and new depots are virtual
        if self.depot_is(new_depot):
            return

        # 1. If the current src_route is assigned to a vehicle, swap which depot counts this src_route (only for "counted" routes)
        # - Decrements old usage if old src_route was nontrivial and depot changed
        # - Increments new usage if depot changed and new src_route is nontrivial after the change
        # Virtual depots are never counted, so skip the corresponding side entirely rather than
        # asking change_depot_uses to accept a virtual depot.
        if not self.source_depot.is_virtual_depot:
            self.change_my_depot_uses(-self.will_depot_swap_decrement_current_depot_usage(new_depot))
        if not new_depot.is_virtual_depot:
            self.change_depot_uses(new_depot, self.will_depot_swap_increment_new_depot_usage(new_depot))

        # 2. Update fields for this visit to match the new depot
        depot_fields = vars(new_depot)
        for key in _exDepot_vars:
            setattr(self, key, depot_fields[key])

        # 3. Update the source depot for this visit
        self.source_depot = new_depot

    def _copy_data(self, source: Node):
        assert isinstance(source, FirstRouteVisit)

        # Copy only depot data fields (via super()) and source_depot
        self.source_depot = source.source_depot

        # Note: This calls both Customer and RouteVisit versions of _copy_data
        super()._copy_data(source)

    def __str__(self):
        return str(self.source_depot)

    def __repr__(self):
        return str(self)

    #endregion


class LastRouteVisit(Depot, RouteVisit):
    prev_visit: CustomerVisit | FirstRouteVisit # prev visit is never None
    next_visit: FirstRouteVisit | None # next visit is either None or the start of the next src_route

    # NOTE: Core operations can only focus on changing where a src_route ends, not starts.
    # BUT changing where one src_route ends for a vehicle necessarily changes where the next starts
    def __init__(self, depot: Depot, route: Route):
        # Restrict to just fields in base Depot class to prevent possible inheritance collisions
        depot_fields = {k: v for k, v in vars(depot).items() if k in _exDepot_vars}

        super().__init__(node=depot, **depot_fields)
        self.source_depot = depot

        self.route: Route = route


    #region Objective and state-related computations
    @property
    def next_visit(self) -> FirstRouteVisit | None:
        # A route's next_route is a real Route, a LastRoute sentinel (end of vehicle), or None
        # (unassigned). Only a real next Route has a first_visit to chain into.
        next_route = self.route.next_route
        if isinstance(next_route, Route):
            return next_route.first_visit

        return None

    def depot_is(self, node: Depot):
        return self.source_depot == node

    def get_replacement_travel_delta(self, new_depot: Depot):
        # Travel delta if replacing own end depot in place:
        # 1) Relink depot for this route's last move
        # 2) Relink depot for next route's first move
        old_length = self.distance_in
        new_length = self.prev_visit.distance(new_depot)

        travel_delta = new_length - old_length

        next_first_visit = self.next_visit
        if next_first_visit is not None:
            travel_delta += next_first_visit.start_travel_delta_if_depot_swapped(new_depot)

        return travel_delta

    def travel_delta_if_inserting_customer_before_this(self, new_customer: Customer):
        # Change to src_route travel distance if inserting new_customer before this
        old_length = self.distance_in
        new_length = self.prev_visit.distance(new_customer) + new_customer.distance(self)
        return new_length - old_length

    def num_depot_usage_deltas_if_depot_swapped(self, new_depot: Depot) -> defaultdict[Depot, int]:
        depot_num_use_deltas = defaultdict(int)
        # Depot uses are counted if the src_route is active: assigned and has customers.
        # So: end depot change cannot affect counting for current src_route, but could affect counting for next src_route.

        # If the depot doesn't change or the src_route is unassigned, report no changes
        # If the new depot is virtual, return no change: Invalid operation
        route = self.route
        if self.depot_is(new_depot) or route.vehicle is None or new_depot.is_virtual_depot:
            return depot_num_use_deltas

        # Report any depot use changes from changing the next src_route's start depot (if there is a next src_route)
        next_node = self.next_visit
        if next_node is not None:
            depot_num_use_deltas = next_node.num_depot_usage_deltas_if_depot_swapped(new_depot)

        return depot_num_use_deltas

    def end_travel_delta_if_route_removed(self) -> Num:
        # If src_route is removed: the next src_route's start depot will change
        # FirstRouteVisit handles the disconnect from start->next_visit

        # If src_route is a cycle or there is no next src_route, start depot doesn't change
        next_visit = self.next_visit
        route_start = self.route.start_depot
        if next_visit is None or self.depot_is(route_start):
            return 0

        # Otherwise: report travel distance if the next src_route swaps start depots
        return next_visit.start_travel_delta_if_depot_swapped(route_start)

    #endregion

    #region Object operations

    def count_route_in_depot(self):
        self.change_depot_uses(self.source_depot, 1)

    def uncount_route_in_depot(self):
        self.change_depot_uses(self.source_depot, -1)

    def change_my_depot_uses(self, num_uses_delta: int):
        self.change_depot_uses(self.source_depot, num_uses_delta)

    def replace_depot(self, new_depot: Depot):
        """
        Replaces the depot for this LastRouteVisit with new_depot:
        1) Change use from this src_route's start depot if the src_route deactivates. Then update the next src_route's first depot
        2) Update the fields for this visit to match the new depot
        3) Update the source depot for this visit
        :param new_depot: Depot to replace this with
        """
        if self.depot_is(new_depot):
            # No-op!
            return

        # NOTE: This can't trigger a depot activation change for this src_route - just the next one.

        # 1. Update the next src_route's first depot, if there is a next src_route.
        next_start = self.next_visit
        if next_start is not None:
            next_start.replace_depot(new_depot)

        # 2. Update the fields for this visit to match the new depot
        depot_fields = vars(new_depot)
        for key in _exDepot_vars:
            setattr(self, key, depot_fields[key])

        # 3. Update the source depot for this visit
        self.source_depot = new_depot

    def _copy_data(self, source: Node):
        assert isinstance(source, LastRouteVisit)

        # Copy only depot data fields (via super()) and source_depot
        self.source_depot = source.source_depot

        # Note: This calls both Customer and RouteVisit versions of _copy_data
        super()._copy_data(source)


    def __str__(self):
        return str(self.source_depot)

    def __repr__(self):
        return str(self)

    #endregion
#endregion

# Route-like objects, including start-point and end-point
class VehicleNode(ABC):
    # Annotations only -- each concrete subclass initializes these in its own __init__.
    # VehicleNode has no __init__ of its own (subclasses don't chain to one), so defaults here
    # would be shared class state rather than per-instance.
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

        depot_num_uses: defaultdict[Depot, int]

        def __init__(self, path: list[CustomerVisit], end_depot: Depot):
            # MUST come first: populate_derived_data/count_load_change below read self.vehicle,
            # and there is no class-level default to fall back on.
            self.vehicle = None
            self.prev_route = None   # None iff unassigned; set when linked into a vehicle
            self.next_route = None

            self.path = path # List of customer visits

            self.first_visit = FirstRouteVisit(VirtualDepot(), self)
            self.last_visit = LastRouteVisit(end_depot, self)

            self.current_load = 0
            if len(path) > 0:
                self.count_load_change(self.recompute_current_load())

            self.populate_derived_data()

            # Start_depot and vehicle will be filled out when the src_route is added to a vehicle.

        def set_values(self, path: list[CustomerVisit]|None =None, vehicle: Vehicle|None=None, start_depot:Depot|None=None, end_depot:Depot|None=None):
            if path is not None:
                self.path = path
                self.populate_derived_data()
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
            if self.start_depot is None or self.vehicle is None:
                raise Exception("Route must be assigned to a vehicle to compute total distance")

            return self.first_move_distance() + self.tail_distance()

        def first_move_distance(self):
            return self.first_visit.distance_out

        def last_move_distance(self):
            return self.last_visit.distance_in

        def first_and_last_move_distance(self):
            if len(self.path) == 0:
                return self.first_move_distance()  # There can be only one (move)

            return self.first_move_distance() + self.last_move_distance()

        def mid_distance(self):
            # TODO: Track via total_distance field, updated with customer/etc ops, instead of updating each time.
            #  Provide recompute function for debugging.
            #  Not needed yet - but will be needed for constraining total vehicle distance later!
            path = self.path
            path_len = len(path)

            if path_len == 0:
                return 0 # Nothing to see here!

            return sum(path[i].distance(path[i + 1]) for i in range(path_len - 1))

        def tail_distance(self):
            # TODO: Track via total_distance field, updated with customer/etc ops, instead of updating each time.
            #  Provide recompute function for debugging.
            #  Not needed yet - but will be needed for constraining total vehicle distance later!
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

        #region Components of dest_route delta computations

        #region Self triviality, activity and activation predictors: node operations

        #region Triviality
        def is_trivial_after_start_depot_swap(self, depot: Depot) -> bool:
            return self.is_empty and self.end_depot == depot

        def is_trivial_after_end_depot_swap(self, depot: Depot) -> bool:
            # ASSUME here: target end depot is not virtual
            return self.is_empty and self.start_depot == depot

        def is_trivial_after_customer_remove(self) -> bool:
            # ASSUME here: customer removal is valid - we have >= 1 customer
            return self.path_len == 1 and self.start_depot == self.end_depot
        #endregion

        #region Activation tracking: depot swaps and customer moves

        #region Will src_route be active after operations?
        # NOTE: A src_route is active if it has customers and is assigned to a vehicle.
        def is_active_after_start_depot_swap(self, depot: Depot) -> bool:
            # TODO: Consider constraining that, within a solve:
            #  1) All customers must be assigned to a vehicle via a src_route at all times, and
            #  2) We never operate with unassigned routes that have no customers: they can only be deleted
            #  These assumptions would remove a lot of unnecessary None-checking, potentially accelerating computation.
            #  BUT for computations potentially called during initial solution construction, we cannot leverage this constraint.

            return self.is_active and not depot.is_virtual_depot

        def is_active_after_end_depot_swap(self, _: Depot) -> bool:
            # ASSUME here: target end depot is not virtual - illegal target for end depot

            # End depot swaps do not affect src_route activity.
            # TODO: Remove all uses of this after src_route activity definition is finalized
            return self.is_active

        def is_inactive_after_customer_remove(self) -> bool:
            # ASSUME here: customer removal is valid - src_route is nonempty
            # Will be inactive if it is unassigned or has just 1 customer left
            return self.vehicle is None or self.path_len == 1 # Can't remove a customer from an empty src_route but we deal with that elsewhere.

        def is_active_after_customer_add(self) -> bool:
            # A src_route with customers is always active if it is assigned to a vehicle.
            return self.is_assigned
        #endregion

        #region How does src_route activation change after operations?

        def activation_change_after_start_depot_swap(self, depot: Depot) -> int:
            # returns -1 if deactivates, 0 if no change, 1 if activates
            if self.start_depot == depot: # Depot unchanged!
                return 0

            active = self.is_active
            will_be_active = self.is_active_after_start_depot_swap(depot)

            activates = not active and will_be_active
            deactivates = active and not will_be_active

            return activates - deactivates

        def activation_change_after_end_depot_swap(self, _: Depot) -> int:
            # End depot swaps no longer have any effect on current src_route activation.
            # The only effects come from changing the next src_route's start depot.
            # TODO: Remove all uses of this after src_route activity definition is finalized
            return 0

        def deactivates_after_customer_remove(self) -> bool:
            # ASSUME here: customer removal is valid - src_route is nonempty
            return self.is_active and self.is_inactive_after_customer_remove()

        def deactivates_after_customer_pop(self) -> bool:
            return self.deactivates_after_customer_remove()

        def activates_after_customer_insert(self) -> bool:
            return self.is_inactive and self.is_active_after_customer_add()

        def activates_after_customer_append(self) -> bool:
            return self.activates_after_customer_insert()
        #endregion

        #endregion

        # endregion

        #region General computations for overload deltas if load and/or vehicle changes.
        def overload_delta_if_load_changes(self, load_delta) -> Num:
            if self.vehicle is None: return 0

            final_load = self.current_load + load_delta
            final_amount_overloaded = max(0, final_load - self.vehicle.capacity)
            return final_amount_overloaded - self.amount_overloaded

        def is_overloaded_delta_if_load_changes(self, load_delta) -> int:
            if self.vehicle is None: return 0

            # Returns: 1 if is newly overloaded, 0 if no change, -1 if newly not overloaded
            is_overloaded = self.is_overloaded
            will_be_overloaded = self.current_load + load_delta > self.vehicle.capacity

            return will_be_overloaded - is_overloaded

        def is_vehicle_overloaded_delta_if_load_changes(self, load_delta: Num) -> int:
            vehicle = self.vehicle

            if vehicle is None:
                return 0

            is_overloaded_delta = self.is_overloaded_delta_if_load_changes(load_delta)

            curr_num_overloaded = vehicle.num_routes_overloaded
            was_overloaded = curr_num_overloaded > 0
            will_be_overloaded = curr_num_overloaded + is_overloaded_delta > 0

            return will_be_overloaded - was_overloaded

        def is_vehicle_overloaded_delta_if_load_changes_from_other_route(self, load_delta: Num, other: Route) -> int:
            if self == other:
                # Same src_route - no change.
                return 0

            if not self.shares_vehicle_with(other):
                self_delta = self.is_vehicle_overloaded_delta_if_load_changes(load_delta)
                other_delta = other.is_vehicle_overloaded_delta_if_load_changes(-load_delta)
                return self_delta + other_delta

            # If same vehicle: must handle differently
            vehicle = self.vehicle

            if vehicle is None:
                return 0

            is_overloaded_delta = self.is_overloaded_delta_if_load_changes(load_delta)
            is_other_overloaded_delta = other.is_overloaded_delta_if_load_changes(-load_delta)

            curr_num_overloaded = vehicle.num_routes_overloaded
            was_overloaded = curr_num_overloaded > 0
            will_be_overloaded = curr_num_overloaded + is_overloaded_delta + is_other_overloaded_delta > 0

            return will_be_overloaded - was_overloaded
        #endregion

        #region Full depot usage deltas from start/end depot changes
        ### Changes for: pure start/end depot assignment change, or if src_route is moved
        ### Important logic to be used on "next src_route" and "this src_route" to determine effects of changing start and end depots.
        ### Affects: Insert self, remove self, change end depot of self.
        def depot_num_usage_deltas_if_start_depot_changes(self, new_start_depot: Depot) -> defaultdict[Depot, int]:
            return self.first_visit.num_depot_usage_deltas_if_depot_swapped(new_start_depot)

        def depot_num_usage_deltas_if_end_depot_changes(self, new_end_depot: Depot) -> defaultdict[Depot, int]:
            return self.last_visit.num_depot_usage_deltas_if_depot_swapped(new_end_depot)

        def depot_num_usage_deltas_if_removed(self) -> defaultdict[Depot, int]:
            # Supports any combination of active/inactive routes for self and next src_route.

            if not self.is_assigned_to_active_vehicle:
                return defaultdict(int) # Cannot remove! No current vehicle.

            # If the vehicle is assigned, the depot changes are:
            # 1) Assign current start depot to next src_route (if it exists).
            # 2) Unassign current start depot from this src_route (which may or may not currently be trivial/active). ("Unassign" = "Assign VirtualDepot")

            unassign_depot = VirtualDepot()
            start_depot = self.start_depot

            # 1) Current depot gets unassigned from current src_route.
            depot_num_usage_deltas = self.first_visit.num_depot_usage_deltas_if_depot_swapped(unassign_depot) # unassign_current_deltas

            # 2) Current start depot gets assigned to next src_route if it exists
            next_route = self.next_route
            if isinstance(next_route, Route):
                # Subtly different usage results than replacing the last depot of this src_route:
                # Example: Route is empty last src_route in active vehicle.
                # Replacing last depot of this src_route could make this src_route inactive - as would un-assigning first depot.
                # Both would decrement one activation from the first depot - double-counting the deactivation of this src_route!
                reassign_next_deltas = next_route.first_visit.num_depot_usage_deltas_if_depot_swapped(start_depot)

                # Combine all depots' deltas by summing them per vehicle
                append_new_defaultdict_by_value_sum(depot_num_usage_deltas, reassign_next_deltas)

            # Put the two together and return it
            return depot_num_usage_deltas

        def depot_num_usage_deltas_if_inserted_before(self, other: Route|LastRoute) -> defaultdict[Depot, int]:
            # SHORTCUT: If pointing at self, no change!
            if other is self:
                return defaultdict(int)

            # Changes:
            # 1) Current start depot changes to new start depot
            # 2) Current next src_route's start depot changes to current start depot
            # 3) New next src_route's start depot changes to current end depot

            # Since end depot changes have no effect on start depot activation, we don't have to worry about that.
            vehicle = other.vehicle
            assert vehicle is not None

            start_depot = self.start_depot
            next_route = self.next_route

            new_start_depot = other.start_depot


            # 1) Current start depot changes to new start depot
            depot_num_usage_deltas = self.depot_num_usage_deltas_if_start_depot_changes(new_start_depot)

            # 2) Next src_route start depot changes to current start depot
            if isinstance(next_route, Route): # Note: if None then index >= vehicle.num_routes - it's an append!
                reassign_new_next_deltas = next_route.depot_num_usage_deltas_if_start_depot_changes(start_depot)

                # Add in new deltas, combining same-key deltas via a sum
                append_new_defaultdict_by_value_sum(depot_num_usage_deltas, reassign_new_next_deltas)

            # 3) New next src_route start depot changes to current end depot
            if not isinstance(other, LastRoute):
                reassign_new_next_deltas = other.depot_num_usage_deltas_if_start_depot_changes(self.end_depot)

                # Add in new deltas, combining same-key deltas via a sum
                append_new_defaultdict_by_value_sum(depot_num_usage_deltas, reassign_new_next_deltas)

            return depot_num_usage_deltas

        def depot_num_usage_deltas_if_appended_to(self, vehicle: Vehicle) -> defaultdict[Depot, int]:
            # Insert to end of vehicle: new_next_route will be None
            return self.depot_num_usage_deltas_if_inserted_before(vehicle.last_route)

        @staticmethod
        def depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas: defaultdict[Depot, int],
                                                               depot_num_uses: defaultdict[Depot, int]) -> int:
            if not depot_usage_deltas:
                # No-changes case
                return 0

            result = 0
            """ Result will report:
            +1 for each depot that transitions from 0 to some uses,
            -1 for each that transitions from some uses to no uses.
            """
            for (depot, usage_deltas) in depot_usage_deltas.items():
                uses = depot_num_uses[depot]
                if usage_deltas > 0:  # Depot gained uses - possible activation
                    result += uses == 0
                elif usage_deltas < 0:  # Depot lost uses - possible deactivation: if Num uses lost == current routes starting here.
                    if uses < -usage_deltas:
                        raise ValueError("Usage deltas are incorrect! They remove more than current number of routes. "
                                         "Something went wrong with the bookkeeping for depot uses.")
                    result -= uses == -usage_deltas

            return result
        #endregion

        #endregion

        #region Basic operations

        #region Changing end depot
        def travel_delta_if_end_depot_changes(self, new_end_depot: Depot) -> Num:
            # Includes relinking the depot for the last move of this route and the first move of any next route
            return self.last_visit.get_replacement_travel_delta(new_end_depot)

        # Since we don't allow operations (except removal and customer insertion) for empty routes:
        #   if we're changing the end depot, this src_route is nonempty, and so our vehicle is active and will remain so.

        def depot_activation_delta_if_end_depot_changes(self, new_end_depot: Depot) -> int:
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            depot_num_usage_deltas = self.depot_num_usage_deltas_if_end_depot_changes(new_end_depot)
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_num_usage_deltas, depot_num_uses=self.depot_num_uses)

        def cost_deltas_if_end_depot_changes(self, new_end_depot: Depot) -> ObjectiveTermDelta:
            travel_delta = self.travel_delta_if_end_depot_changes(new_end_depot)

            depot_activation_delta = self.depot_activation_delta_if_end_depot_changes(new_end_depot)

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta)
        #endregion

        #region Route operations: removing, inserting, and appending self to/from a vehicle.
        # Possibilities: Travel distance could change. Vehicle could be activated/deactivated.
        #   Depot could be activated/deactivated. Amount of src_route overload could change.

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

        #region Depot-related computations
        def depot_activation_delta_if_removed(self) -> int:
            if self.is_trivial:
                return 0

            depot_usage_deltas = self.depot_num_usage_deltas_if_removed()
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_num_uses=self.depot_num_uses)

        def depot_activation_delta_if_inserted_before(self, route: Route|LastRoute) -> int:
            depot_usage_deltas = self.depot_num_usage_deltas_if_inserted_before(route)
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_num_uses=self.depot_num_uses)

        def depot_activation_delta_if_appended_to(self, vehicle) -> int:
            depot_usage_deltas = self.depot_num_usage_deltas_if_appended_to(vehicle)
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_num_uses=self.depot_num_uses)
        #endregion

        #region Vehicle activation-related computations
        def is_vehicle_deactivated_if_removed(self):
            # Removal deactivates a vehicle if the src_route has customers and is the sole such src_route for its vehicle
            vehicle = self.vehicle
            return vehicle is not None and vehicle.num_routes_with_customers == 1 and self.has_customers

        def is_last_overloaded_route_in_vehicle(self) -> bool:
            # True if self is currently its vehicle's sole overloaded route, i.e. removing self
            # (or otherwise un-overloading it) would un-overload the whole vehicle.
            vehicle = self.vehicle
            return vehicle is not None and vehicle.num_routes_overloaded == 1 and self.is_overloaded

        def vehicle_activation_delta_if_added(self, vehicle: Vehicle):
            # Adding to another vehicle involves removing from current vehicle!

            # If current vehicle = vehicle, no change.
            if vehicle == self.vehicle:
                return 0

            current_deactivates = self.is_vehicle_deactivated_if_removed()
            # New activates if it has no customers
            new_activates = vehicle.num_customers == 0 and self.has_customers

            return new_activates - current_deactivates
        #endregion

        #region Full delta computations
        def cost_deltas_if_removed(self):
            # Also doubles as "travel delta if disposed"
            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            if self.vehicle is None:
                return 0 # Cannot remove a src_route if it's unassigned!

            if self.is_trivial:
                return ObjectiveTermDelta() # Delta = 0

            travel_delta = self.travel_delta_if_removed()

            # Compute vehicle activation delta
            # Vehicle is deactivated if all of vehicle's dest_route routes are unused
            vehicle_activation_delta = -int(self.is_vehicle_deactivated_if_removed())

            # Compute depot activation delta
            # Depot is deactivated if self's start depot has only one src_route
            depot_activation_delta = self.depot_activation_delta_if_removed()

            # Compute overload delta
            overload_delta = -self.amount_overloaded

            # Compute delta for num vehicles overloaded (-1 if this was the last overloaded src_route in vehicle, 0 o/w)
            num_vehicles_overloaded_delta = -int(self.is_last_overloaded_route_in_vehicle())

            return ObjectiveTermDelta(travel_delta, vehicle_activation_delta, depot_activation_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_inserted_before(self, other: Route|LastRoute) -> ObjectiveTermDelta:
            vehicle = other.vehicle
            assert vehicle is not None, "Cannot insert before unassigned route"

            # If currently assigned to a vehicle: this DOES NOT include deltas for removal stage
            if self.is_adjacent_with(other):
                # route1 is earlier of self or dest_route, route2 = route1.next_route is the later.
                # Since the two are adjacent... both exist.
                route1 = self if other is self.next_route else other
                route2 = route1.next_route # type: ignore - Linter is unconvincible that route1 is not None without an ignore somewhere
                return route1.cost_deltas_if_swapped_with_next_route() # type: ignore

            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            if self.is_empty:
                return ObjectiveTermDelta() # Delta = 0. (We don't allow inserting empty stuff - so return 0.)

            is_same_vehicle = self.vehicle == vehicle

            travel_delta = self.travel_delta_if_inserted_before(other)

            # Compute vehicle activation delta
            # Vehicle is activated if all of vehicle's dest_route routes are unused
            vehicle_activation_delta = int(self.vehicle_activation_delta_if_added(vehicle))

            # Compute depot activation delta
            # Depot is deactivated if self's start depot has no routes
            depot_activation_delta = self.depot_activation_delta_if_inserted_before(other)

            # Compute overload deltas
            if is_same_vehicle:
                overload_delta = 0
                num_vehicles_overloaded_delta = 0
            else:
                # Total overload
                old_overload = self.amount_overloaded
                new_overload = max(0, self.current_load - vehicle.capacity)
                overload_delta = new_overload - old_overload

                # Num vehicles overloaded: mirrors cost_deltas_if_removed's own formula -- removing
                # self un-overloads its OLD vehicle exactly when self was that vehicle's only
                # overloaded route (NOT when the vehicle deactivates, which is a different condition).
                vehicle_overloads_removed = self.is_last_overloaded_route_in_vehicle()
                vehicle_overloads_added = vehicle.num_routes_overloaded == 0 and (self.current_load > vehicle.capacity)
                num_vehicles_overloaded_delta = vehicle_overloads_added - vehicle_overloads_removed

            return ObjectiveTermDelta(travel_delta, vehicle_activation_delta, depot_activation_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_appended_to(self, vehicle: Vehicle) -> ObjectiveTermDelta:
            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            return self.cost_deltas_if_inserted_before(vehicle.last_route)
        #endregion
        #endregion

        #region Basic customer operations (within a src_route): Remove, pop, insert, append

        #region Travel-related deltas
        @staticmethod
        def travel_delta_if_customer_removed(customer: CustomerVisit):
            return customer.travel_delta_if_removed

        def travel_delta_if_customer_popped(self, index: int):
            if index >= self.path_len:
                raise IndexError("Customer index out of range.")
            return self.travel_delta_if_customer_removed(self.path[index])

        def travel_delta_if_customer_inserted(self, customer: CustomerVisit, index: int):
            # Returns the travel time cost incurred by inserting a customer at the given index
            # Robust to out-of-bounds: returns start or end visit as appropriate in this case
            next_visit = self.get_visit_at(index)

            # Pattern is "visit gets delta if inserting a new customer before itself"
            return next_visit.travel_delta_if_inserting_customer_before_this(customer)

        def travel_delta_if_customer_appended(self, customer: CustomerVisit):
            return self.last_visit.travel_delta_if_inserting_customer_before_this(customer)
        #endregion

        #region Vehicle activation deltas

        # NOTE: Active routes does not imply an active vehicle.
        # Active vehicle = "vehicle has customers"
        # Active src_route = "src_route moves something and it's assigned to an active vehicle"
        @property
        def vehicle_deactivates_if_customer_removed(self):
            # For a customer removal to deactivate our vehicle:
            #   It must make us trivial, and this must be the only nontrivial src_route.
            vehicle = self.vehicle
            return vehicle is not None and vehicle.num_customers == 1

        def vehicle_activates_if_customer_added(self):
            vehicle = self.vehicle

            # Adding a customer to any inactive vehicle activates it
            return vehicle is not None and vehicle.is_inactive
        #endregion

        #region Depot activation deltas
        def depot_deactivates_if_customer_removed(self):
            return self.deactivates_after_customer_remove() and self.first_visit.num_routes_starting_here == 1

        def depot_activates_if_customer_added(self):
            return self.activates_after_customer_insert() and self.first_visit.num_routes_starting_here == 0
        #endregion

        #region Overload-related deltas
        def overload_deltas_if_customer_removed(self, customer: CustomerVisit) -> tuple[Num, int]:
            load_delta = -customer.demand

            overload_delta = self.overload_delta_if_load_changes(load_delta)
            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes(load_delta)

            return overload_delta, vehicles_overloaded_delta

        def overload_deltas_if_customer_popped(self, index: int) -> tuple[Num, int]:
            return self.overload_deltas_if_customer_removed(self.path[index])

        def overload_deltas_if_customer_inserted(self, customer: CustomerVisit) -> tuple[Num, int]:
            load_delta = customer.demand

            overload_delta = self.overload_delta_if_load_changes(load_delta)
            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes(load_delta)

            return overload_delta, vehicles_overloaded_delta

        def overload_deltas_if_customer_appended(self, customer: CustomerVisit) -> tuple[Num, int]:
            return self.overload_deltas_if_customer_inserted(customer)
        #endregion

        #region Full deltas
        def cost_deltas_if_customer_removed(self, customer):
            travel_delta = self.travel_delta_if_customer_removed(customer)
            vehicle_delta = -self.vehicle_deactivates_if_customer_removed
            depot_delta = -self.depot_deactivates_if_customer_removed()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_removed(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_customer_popped(self, index):
            travel_delta = self.travel_delta_if_customer_popped(index)
            vehicle_delta = -self.vehicle_deactivates_if_customer_removed
            depot_delta = -self.depot_deactivates_if_customer_removed()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_popped(index)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_customer_inserted(self, customer, index):
            travel_delta = self.travel_delta_if_customer_inserted(customer, index)
            vehicle_delta = self.vehicle_activates_if_customer_added()
            depot_delta = self.depot_activates_if_customer_added()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_inserted(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_customer_appended(self, customer):
            travel_delta = self.travel_delta_if_customer_appended(customer)
            vehicle_delta = self.vehicle_activates_if_customer_added()
            depot_delta = self.depot_activates_if_customer_added()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_appended(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)
        #endregion

        #endregion

        #endregion

        #region Composite operations: Swapping customers, permuting/subpermuting, combining, and splitting

        #region Customer swaps
        # can only change travel distance or overload routes)
        @staticmethod
        def cost_deltas_for_adjacent_customer_swap_starting_with(customer1: CustomerVisit):
            customer2 = customer1.next_visit
            if not isinstance(customer2, CustomerVisit):
                raise ValueError("Specified customer is at the end of a src_route.")

            # Swapping adjacent customers affects only travel distance:
            # No depots/vehicles are activated and no src_route loads change.

            travel_delta = customer1.travel_delta_if_swapped_with(customer2)
            return ObjectiveTermDelta(travel_distance=travel_delta)

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
        def total_overload_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit) -> tuple[Num, int]:
            # returns (route1_overload_delta, route2_overload_delta, vehicle1_is_overloaded_delta, vehicle2_is_overloaded_delta)
            route1 = customer1.route
            route2 = customer2.route

            if route1 is None or route2 is None:
                raise ValueError("Cannot swap customers that aren't assigned to routes!")

            if route1 == route2:
                # Load is unchanged! Intra-src_route swap.
                return 0, 0
            else:
                # Compute net src_route overload change
                route1_load_delta = customer1.current_route_load_delta_if_swapped_with(customer2)
                route2_load_delta = -route1_load_delta

                route1_overload_delta = route1.overload_delta_if_load_changes(route1_load_delta) # type: ignore # For some reason linter can't tell that route1 is not None here
                route2_overload_delta = route2.overload_delta_if_load_changes(route2_load_delta)

                num_vehicles_overloaded_delta = route1.is_vehicle_overloaded_delta_if_load_changes_from_other_route(route1_load_delta, route2)# type: ignore # For some reason linter can't tell that route1 is not None here

                return route1_overload_delta + route2_overload_delta, num_vehicles_overloaded_delta

        # Any two customers
        @staticmethod
        def cost_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit):
            # Implement all deltas in one place to prevent rework such as recomputing load deltas.

            # Travel delta
            travel_delta = customer1.travel_delta_if_swapped_with(customer2)

            # Total overload and num vehicles overloaded delta
            (route_overload_delta, num_vehicles_overloaded_delta) = Route.total_overload_deltas_for_customer_swap(customer1, customer2)

            # Swapping customers does not change vehicle or depot activation. So we're ready to return.
            return ObjectiveTermDelta(travel_distance=travel_delta, total_route_overload=route_overload_delta, vehicles_overloaded=num_vehicles_overloaded_delta)

        def cost_deltas_for_intra_route_customer_swap_at(self, i: int, j: int):
            customer1 = self.path[i]
            customer2 = self.path[j]

            return self.cost_deltas_for_customer_swap(customer1, customer2)

        def cost_deltas_for_inter_route_customer_swap_at(self, i: int, other: Route, j: int):
            customer1 = self.path[i]
            customer2 = other.path[j]

            return self.cost_deltas_for_customer_swap(customer1, customer2)
        #endregion

        #region Permutation and subpermutation (travel distance only)
        def cost_deltas_for_permutation(self, permutation: Sequence[int]) -> ObjectiveTermDelta:
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

            return ObjectiveTermDelta(travel_distance=travel_delta)

        def cost_deltas_for_subpermutation(self, subpermutation: Sequence[int]) -> ObjectiveTermDelta:
            # WARNING: Must sub-permute anyway to get the cost delta. Could be cheaper to apply the operator, compute, then unapply.
            # We would like to compute via summing along a cycle of customer swaps instead. Issue: Need to actually swap customers before computing this.
            old_distance = self.total_distance()

            first_visit = self.first_visit
            last_visit = self.last_visit

            path = self.path
            path_len = len(path)
            subpermutation_len = len(subpermutation)


            new_path = list(path)
            sub_permute_list(subpermutation, new_path)

            use_partial_update = subpermutation_len <= path_len / 5
            if use_partial_update:
                # Affected visits defines consecutive subpaths that are touched by the subpermutation.
                # Sort is expensive, so we only want to do this if subpermutation is significantly shorter than o/g permutation
                affected_visits = list(sorted({i for j in subpermutation for i in (j+1,j,j-1)}))

                travel_delta = 0

                for idx in range(len(affected_visits)-1):
                    i = affected_visits[idx]
                    next_i = affected_visits[idx+1]
                    if next_i != i + 1:
                        continue # Connection not touched by subpermutation

                    src = first_visit if i<0 else path[i]
                    new_src = first_visit if i<0 else new_path[i]

                    new_dest = last_visit if next_i >= path_len else new_path[next_i]

                    travel_delta += new_src.distance(new_dest) - src.distance_out
            else:
                new_path = [self.start_depot] + new_path + [self.end_depot]
                new_distance = sum(new_path[i].distance(new_path[i + 1]) for i in range(len(new_path) - 1))

                travel_delta = new_distance - old_distance

            return ObjectiveTermDelta(travel_distance=travel_delta)
        #endregion

        #region Splitting this src_route
        def cost_deltas_for_split_at(self, split_index: int, refill_depot: Depot) -> ObjectiveTermDelta:
            path = self.path

            # split_index is the index of the new (second-half) route's first customer -- same
            # convention as split_at and split2_load below -- so the customer this function prices
            # the depot-stop insertion after (the first half's last customer) is at split_index - 1.
            split_customer = self.get_visit_at(split_index - 1)
            # use isinstance instead of is_customer_visit for linter's sanity
            if not isinstance(split_customer, CustomerVisit):
                # First split src_route must end with customer
                return ObjectiveTermDelta()

            if not split_customer.next_visit.is_customer_visit:
                # Second split src_route must begin with customer
                # Note: next_visit is guaranteed to exist since split_customer is a customer visit
                return ObjectiveTermDelta()

            vehicle = self.vehicle
            if vehicle is None:
                return ObjectiveTermDelta() #  Cannot split unassigned routes


            ## Compute each relevant delta

            # Travel
            travel_delta = split_customer.travel_delta_if_depot_stop_added_after_this(refill_depot)

            # Depot activation
            # Guaranteed to activate refill depot if self is assigned (which is guaranteed): new src_route will have customers and thus be active
            depot_activation_delta = int(self.depot_num_uses[refill_depot] == 0)

            # No new vehicles will be activated, so we skip vehicle activation delta

            # Capacity overloading
            old_overload = self.amount_overloaded

            split2_load = sum(customer.demand for customer in path[split_index:])
            split1_load = self.current_load - split2_load

            split1_new_overload = max(0, split1_load - vehicle.capacity)
            split2_new_overload = max(0, split2_load - vehicle.capacity)

            overload_delta = split1_new_overload + split2_new_overload - old_overload

            # Vehicle overloading
            vehicle_num_overloads = vehicle.num_routes_overloaded
            vehicle_was_overloaded = vehicle_num_overloads > 0

            route_was_overloaded = old_overload > 0
            split1_overloaded = split1_new_overload > 0
            split2_overloaded = split2_new_overload > 0

            vehicle_new_num_overloads = vehicle_num_overloads - route_was_overloaded + split1_overloaded + split2_overloaded
            vehicle_will_be_overloaded = vehicle_new_num_overloads > 0

            vehicle_num_overloaded_delta = vehicle_will_be_overloaded - vehicle_was_overloaded

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta, total_route_overload=overload_delta, vehicles_overloaded=vehicle_num_overloaded_delta)
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

        # Combining cannot activate self.vehicle: we only allow combining with active routes, so self must be nonempty!
        def depot_activation_delta_for_combine_with(self, other: Route) -> int:
            if self is other:
                return 0 # Can't combine with self

            if other == self.next_route:
                # Combination with next src_route looks very different: The stop in between the routes is just removed, and next-src_route start activation is removed if it's nonempty.
                return self.depot_activation_delta_for_combine_with_next_route()

            # Combine with prev src_route is the same as combine with nonadjacent:
            # Effects of current-src_route start depot change are handled by depot removal.
            # Current-src_route end depot change does not affect current-src_route start depot activation, so the caveat that start and depots may change simultaneously affects nothing.
            return self.depot_activation_delta_for_combine_with_nonadjacent(other)

        def depot_activation_delta_for_combine_with_nonadjacent(self, other: Route) -> int:
            assert self is not other, "Cannot combine with self"

            # Depot changes are:
            # 1) Remove the dest_route src_route from its vehicle
            # 2) Change the end depot for this src_route to the dest_route's end depot

            # 1) Other removal
            depot_activation_deltas = other.depot_num_usage_deltas_if_removed()

            # 2) Self end depot replacement
            next_route = self.next_route
            if isinstance(next_route, Route) and self.end_depot != other.end_depot:
                this_depot_activation_deltas = self.depot_num_usage_deltas_if_end_depot_changes(other.end_depot)
                append_new_defaultdict_by_value_sum(depot_activation_deltas, this_depot_activation_deltas)

            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_activation_deltas, depot_num_uses=self.depot_num_uses)

        def depot_activation_delta_for_combine_with_next_route(self) -> int:
            # Math is different if combining with next src_route.
            other = self.next_route

            # Explicitly assume that valid swap vetting is done before this stage. We don't want to double-check these conditions again in production
            assert other is not None, "No next src_route to combine with"# If dest_route is None the operation is illegal.
            assert self is not other, "Cannot combine with self"
            assert isinstance(other, Route), "Can only combine with Routes"

            # Why is it different? When dest_route is removed, the next src_route's start depot changes, and on combination, it changes again.
            # That is: the "sum of changes" approach calculates outcomes with the wrong predicted data, and
            # e.g. could count activation of 2 different start depots for the next src_route instead of 1.

            # Depot changes are just: Remove any use count of dest_route's start depot.
            # Thus, quick computation: If the dest_route src_route is active (has customers, since it's definitely assigned), the depot loses a use, and so deactivates if that lost use was the last one.
            return -(other.has_customers and self.depot_num_uses[other.start_depot] == 1)

        def overload_related_deltas_for_combine_with(self, other: Route) -> tuple[Num, int]:
            if self.is_inactive or other.is_inactive or self is other:
                return 0, 0  # We don't operate with inactive routes except for removal! So return 0 change

            other_load = other.current_load
            this_overload_delta = self.overload_delta_if_load_changes(other_load)
            other_overload_delta = other.overload_delta_if_load_changes(-other_load)
            overload_delta = this_overload_delta + other_overload_delta


            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes_from_other_route(other_load, other)

            return overload_delta, vehicles_overloaded_delta

        def vehicle_activation_delta_for_combine_with(self, other: Route) -> int:
            if self.vehicle == other.vehicle:
                # Shuffling routes within a vehicle won't deactivate it
                return 0

            return -other.is_vehicle_deactivated_if_removed()

        def cost_deltas_for_combine_with(self, other: Route) -> ObjectiveTermDelta:
            if self is other:
                raise ValueError("Cannot combine a src_route with itself")

            travel_delta = self.travel_delta_for_combine_with(other)
            depot_activation_delta = self.depot_activation_delta_for_combine_with(other)
            (overload_delta, vehicles_overloaded_delta) = self.overload_related_deltas_for_combine_with(other)

            # If this and dest_route don't share a vehicle, dest_route's vehicle may deactivate
            vehicle_activation_delta = self.vehicle_activation_delta_for_combine_with(other)

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta, vehicles_activated=vehicle_activation_delta,
                                      total_route_overload=overload_delta, vehicles_overloaded=vehicles_overloaded_delta)
        #endregion

        def cost_deltas_if_swapped_with_next_route(self):
            # These deltas come exclusively from changes in the start_depot of each src_route.
            # So? We simply ask the routes for the travel deltas when swapping their start depots.
            # This includes the src_route after next if it exists.
            # The routes affected are: this src_route, the next src_route, and the src_route after next.

            route1 = self
            route2 = self.next_route

            if route2 is None:
                raise ValueError("No next src_route to swap with.")

            if route1.is_empty or route2.is_empty:
                # Cannot swap with empty routes (soft rule on calculate, hard on operate)
                return ObjectiveTermDelta()

            # Before swap: routes are route0->route1->route2->route3
            # After swap: routes are route0->route2->route1->route3
            # So:
            # 1) src_route 1 starts at end of route2
            # 2) src_route 2 starts at original start for route1
            # 3) src_route 3 starts at end of route1

            start_depot_1 = route1.start_depot
            end_depot_1 = route1.end_depot
            end_depot_2 = route2.end_depot
            route3 = route2.next_route

            # Load these once for efficiency
            route3_exists = isinstance(route3, Route)
            route1_first_visit = route1.first_visit
            route2_first_visit = route2.first_visit
            route3_first_visit = route3.first_visit if route3_exists else None # type: ignore

            # TRAVEL DELTAS
            travel_delta_1 = route1_first_visit.start_travel_delta_if_depot_swapped(end_depot_2)
            travel_delta_2 = route2_first_visit.start_travel_delta_if_depot_swapped(start_depot_1)
            travel_delta_3 = route3_first_visit.start_travel_delta_if_depot_swapped(end_depot_1) if route3_exists else 0 # type: ignore

            travel_delta = travel_delta_1 + travel_delta_2 + travel_delta_3

            # DEPOT ACTIVATION DELTAS
            # Compute num use deltas per start-swap operation
            depot_num_use_deltas_1 = route1_first_visit.num_depot_usage_deltas_if_depot_swapped(end_depot_2)
            depot_num_use_deltas_2 = route2_first_visit.num_depot_usage_deltas_if_depot_swapped(start_depot_1)
            depot_num_use_deltas_3 = route3_first_visit.num_depot_usage_deltas_if_depot_swapped(end_depot_1) if route3_exists else 0 # type: ignore

            # Aggregate num use deltas from the three operations
            all_depot_num_use_deltas = depot_num_use_deltas_1
            append_new_defaultdict_by_value_sum(all_depot_num_use_deltas, depot_num_use_deltas_2)
            if route3_exists: append_new_defaultdict_by_value_sum(all_depot_num_use_deltas, depot_num_use_deltas_3) # type: ignore

            # Compute delta for number of depots activated from full use delta info
            depot_activation_delta = self.depot_activation_delta_from_depot_num_usage_deltas(all_depot_num_use_deltas, depot_num_uses=self.depot_num_uses)

            # Vehicle activation delta = 0: Vehicles are considered active if they have customers,
            # which is unaffected by src_route order.

            # Vehicle overloading and total amount of overloading are 0: src_route swapping within a vehicle does not affect src_route/vehicle overloading

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta)

        #endregion

        #endregion

        #region Basic object operations

        def count_load_change(self, load_delta):
            # Add load_delta to self.current_load, and handle vehicle overload accounting for the load change
            # Delta must be updated after predicted overload changes are accounted for.

            # Update number of overloads for vehicle
            vehicle = self.vehicle
            if vehicle is not None:
                vehicle.num_routes_overloaded += self.is_overloaded_delta_if_load_changes(load_delta)

            # Update current load delta
            self.current_load += load_delta

        #region customer registration

        # NOTE: MUST call these before self.num_customers changes if it's not a src_route operation.
        # Otherwise: Cannot evaluate whether the src_route is about to be empty
        def register_num_customers_change_in_vehicle(self, num_customer_delta: int, is_route_operation: bool = False):
            if num_customer_delta == 0: return # No change

            vehicle = self.vehicle
            if vehicle is not None:
                # Update num customers
                vehicle.num_customers += num_customer_delta

                # Update accounting, depending on whether it's a customer or src_route operation
                delta_sign = 1 if num_customer_delta > 0 else -1
                if is_route_operation:
                    # Add or remove. Either count or uncount the src_route based on sign.
                    vehicle.num_routes_with_customers += delta_sign
                else:
                    # Add if positive and currently empty
                    if delta_sign > 0 and self.is_empty:
                        vehicle.num_routes_with_customers += 1
                    if delta_sign < 0 and num_customer_delta == -self.num_customers:
                        # About to be empty! Decrement customers
                        vehicle.num_routes_with_customers -= 1

        def count_customers_in_vehicle(self):
            self.register_num_customers_change_in_vehicle(self.num_customers, is_route_operation=True)

        def uncount_customers_from_vehicle(self):
            self.register_num_customers_change_in_vehicle(-self.num_customers, is_route_operation=True)

        def register_customer_add_in_vehicle(self):
            self.register_num_customers_change_in_vehicle(1, is_route_operation=False)

        def register_customer_remove_in_vehicle(self):
            self.register_num_customers_change_in_vehicle(-1, is_route_operation=False)
        #endregion

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

            # Vehicle accounting: Overloading and num customers
            self.vehicle.num_routes_overloaded -= self.is_overloaded

            self.uncount_customers_from_vehicle()

            # Unlink this src_route from the vehicle
            self.vehicle.routes.remove(self)

            self.set_start_depot(VirtualDepot())
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

                # Handle accounting
                self.count_customers_in_vehicle()

                # Mark src_route as an overload for this vehicle
                # Pitfall for counting routes overloaded per vehicle: opt may shift all overloaded routes to one vehicle instead of splitting them.
                # To help counteract this, we can add a "Split_random_overloaded_route" operator - active if there are some overloaded routes
                new_vehicle.num_routes_overloaded += self.is_overloaded

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

        def populate_derived_data(self):
            # Link path visits together, and compute delivery load for src_route
            self.uncount_customers_from_vehicle()
            path = self.path
            self.count_customers_in_vehicle()

            if len(path) == 0:
                self.count_load_change(-self.current_load) # Remove all load from self - and update any requisite vehicle overload accounting.
                self.first_visit.next_visit = self.last_visit
                return

            # Update current load and vehicle overload accounting
            current_load = sum(c.demand for c in path)
            self.count_load_change(current_load-self.current_load)

            # Link visits
            self.link_visits()

        def link_visits(self):
            # For use during copy or similar:
            # Relink visits without updating any accounting
            path = self.path

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

        # To be called exactly once from FullSolution directly after initial solution is populated
        def link_depot_uses(self, depot_num_uses: defaultdict[Depot, int]):
            self.depot_num_uses = depot_num_uses

            self.first_visit.depot_num_uses = depot_num_uses
            self.last_visit.depot_num_uses = depot_num_uses

            for visit in self.path:
                visit.depot_num_uses = depot_num_uses

        # To be called only when a new src_route is created during mid-solve.
        # Currently, only a few operations can do this, like Split()
        def link_depot_uses_except_customers(self, depot_num_uses: defaultdict[Depot, int]):
            self.depot_num_uses = depot_num_uses

            self.first_visit.depot_num_uses = depot_num_uses
            self.last_visit.depot_num_uses = depot_num_uses

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
            # Just inserts the customer. Updates start depot's "num_used" if the src_route goes
            # inactive -> active. Mirrors CustomerVisit.unlink_from_route's decrement: the rule is
            # "uses its depot" = "has customers AND is assigned" (is_active), NOT is_trivial --
            # an empty route with start != end is non-trivial but still inactive/uncounted.
            if self.is_inactive and self.is_active_after_customer_add():
                self.first_visit.count_route_depot_use()

            self.register_customer_add_in_vehicle()
            self.count_load_change(customer.demand)

            self.path.insert(index, customer)
            self.link_customer(index)

        def append_customer(self, customer):
            # Just appends the customer. Same inactive -> active depot-usage rule as insert_customer.
            if self.is_inactive and self.is_active_after_customer_add():
                self.first_visit.count_route_depot_use()

            self.register_customer_add_in_vehicle()
            self.count_load_change(customer.demand)

            self.path.append(customer)
            self.link_customer(self.path_len-1)

        def remove_customer(self, customer):
            # Caution: This is more expensive than pop_customer_at:
            #   It requires an unordered search for customer in path, on top of
            #   the normal list removal cost.
            #   Updates start depot's "num_used" if the src_route becomes trivial post-remove.

            self.register_customer_remove_in_vehicle()
            self.count_load_change(-customer.demand)

            customer.unlink_from_route()
            self.path.remove(customer)

            # Customer unlinking takes care of depot usage accounting.

        def pop_customer_at(self, index: int) -> CustomerVisit:
            # Pops the src_route customer at index and returns it.
            #   Updates start depot's "num_used" if the src_route becomes trivial post-pop.
            self.register_customer_remove_in_vehicle()
            self.count_load_change(-self.path[index].demand)

            self.unlink_customer_at(index)
            customer = self.path.pop(index)

            # Customer unlinking takes care of depot usage accounting.

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

            # SKIP depot_num_uses: MUST be linked by FullSolution

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

        def permute(self, permutation: Sequence[int]):
            path = self.path
            path_len = len(path)
            if path_len <=1:
                return # nothing to permute!

            if len(permutation) != path_len:
                raise ValueError("Permutation has wrong length")

            if set(permutation) != set(range(path_len)):
                raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

            # Use set_values to re-link customers
            # CS convention: ith value of permutation defines source for new path: [2,3,4,1] means new is [path[2], path[3], path[4], path[1]], not (path[1] goes to 2) etc.
            new_path = [path[i].source_customer for i in permutation]

            for i in range(path_len):
                path[i].replace_customer(new_path[i])

        def sub_permute(self, subpermutation: Sequence[int]):
            # Like permute, but e.g. if subpermutation is 1,3,5, then we move item 1->3->5->1

            if len(subpermutation) > self.path_len:
                raise ValueError("Subpermutation is longer than the path")
            if len(subpermutation) <= 1:
                return

            # Permute path in place cheaply (no accounting necessary!) via direct node replacement within visits.
            sub_permute_path(subpermutation, self.path)

        def split_at(self, split_index: int, refill_depot: Depot) -> Route:
            # Removes the customers at or after the index. Then returns a new src_route with those customers and
            # the given end depot. Idea is that vehicle will handle the insertion of the new src_route.
            # TODO(revert-identity): take an optional `into: Route | None = None` and, when given,
            # refill THAT route object with the tail customers instead of constructing a new one.
            # Needed so CombineRoutes._revert_impl can restore the route combine_with disposed of,
            # rather than substituting a fresh object. Right now any caller holding a reference to
            # the original route (an already-evaluated Move's operands, a future undo stack, a
            # debug re-evaluate) is left pointing at a dead route after an apply->revert cycle.
            path = self.path
            path_len = self.path_len

            if split_index < 0 or split_index >= path_len:
                raise IndexError("split_index out of range")

            if split_index == 0 or 1 >= path_len or path_len == split_index:
                raise ValueError("Invalid split: After split, both routes must have a customer.")

            # Make the new src_route. First customer of new src_route will link with new FirstVisit on creation.
            # Broken linkages will update on new src_route add.
            new_route = Route(path[split_index:], self.end_depot)

            # Remove the tail of the path from the original src_route, and update customer linkages without affecting vehicle customer accounting.

            # We've removed some customers! So un-count them from the vehicle.
            # They'll be re-counted on insertion of the new src_route.
            self.register_num_customers_change_in_vehicle(-new_route.num_customers, is_route_operation=False)

            self.path = path[:split_index]
            self.relink_customer(split_index-1)
            new_route.relink_customer(0)

            new_route.link_depot_uses_except_customers(self.depot_num_uses)

            # Replace end depot of this src_route with refill_depot
            # We use set_end_depot to ensure that all depot accounting is correct (and self.end_depot=next_route.start_depot
            # as expected) before we insert the new src_route after this one.
            self.set_end_depot(refill_depot)
            self.count_load_change(-new_route.current_load)

            # Add new route after self
            new_route.link_to_vehicle_after(self)

            return new_route  # Return it for addition to all_routes

        def combine_with(self, other: Route):
            # other must have customers to relink at the boundary index below; is_empty (not just
            # is_trivial) is the real requirement -- an empty-but-not-trivial other (zero customers,
            # start_depot != end_depot) would relink out of range just the same.
            if other.is_empty or self.is_trivial:
                raise ValueError("Cannot combine using trivial/empty routes")

            if self is other:
                raise ValueError("Cannot combine a src_route with itself")

            # Operate before removing dest_route so that the remove operation sees the correct end depot - and thus correctly updates
            #   the end_depot for the next pop.
            #   ("pop" triggers "self.unlink_from_vehicle" - which will set the current start depot as the next src_route's
            #       start_depot, among dest_route key changes. So we need to ensure data is correct when we pop!)
            # Also, increment current vehicle's overload count if this src_route is newly overloaded. (Un-overloading is not possible since demands>0!)
            start_len = self.path_len

            # Even if vehicle is the same, this is needed to balance out the accounting from other.unlink_from_vehicle.
            # Still needed: #customers doesn't change, but vehicle's num_routes_with_customers might!
            self.register_num_customers_change_in_vehicle(other.num_customers, is_route_operation=False)

            self.path += other.path
            self.set_end_depot(other.end_depot)
            self.count_load_change(other.current_load)

            # Relink dest_route's first customer in self (links src_route ends together), and reassign others' routes as self
            self.relink_customer(start_len)
            # Relink the new final customer to SELF's last_visit too. The appended customers still
            # carry other's internal links, so without this the tail stays wired to
            # other.last_visit and self.last_visit.prev_visit keeps pointing at self's OLD last
            # customer -- which silently corrupts every delta computed off last_visit
            # (get_replacement_travel_delta, distance_in, ...). Only a no-op when other had
            # exactly 1 customer, in which case relink_customer(start_len) already did it.
            self.relink_customer(self.path_len - 1)
            other.last_visit.route = self
            for i in range(start_len+1, self.path_len):
                self.path[i].route = self

            other.unlink_from_vehicle() # Also uncounts its customers from the dest_route src_route's vehicle

            # Clear dest_route src_route
            other.set_values(path=[])

        def __str__(self):
            return (str(self.start_depot.dID) + '->' +
                    '->'.join(str(customer.cID) for customer in self.path) + '->' +
                    str(self.end_depot.dID))

        def __repr__(self):
            return str(self)

        #endregion


class RouteSet:
    """Class for a set supporting random choice. Expanded and optimized greatly from Gemini-generated version."""
    """A set-like container supporting O(1) add, remove, lookups, and random choice."""

    def __init__(self, iterable: Iterable[Route] = ()):
        self._items: list[Route] = []
        self._idx_map: dict[Route, int] = {}
        for item in iterable:
            self.add(item)


    @staticmethod
    def _add_given_fields(item: Route, items: list[Route], idx_map: dict[Route, int], size) -> bool:
        if item in idx_map:
            return False

        idx_map[item] = size
        items.append(item)
        return True

    def add(self, item: Route) -> bool:
        return RouteSet._add_given_fields(item, self._items, self._idx_map, self.__len__())

    @staticmethod
    def _remove_existing_item_given_fields(item: Route, idx: int, items: List[Route], idx_map: dict[Route, int]) -> None:
        # Not worth doing this only if needed: cpu instruction flushing is worse than just 3 ops unnecessarily
        last_item = items[-1]

        # Swap target item with the last item in the list
        items[idx] = last_item
        idx_map[last_item] = idx

        # Remove the target item
        items.pop()
        del idx_map[item]

    def remove(self, item: Route) -> None:
        idx_map = self._idx_map
        if item not in idx_map:
            raise KeyError(item)

        idx = idx_map[item]
        RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def discard(self, item: Route) -> None:
        idx_map = self._idx_map
        if item not in idx_map:
            return

        idx = idx_map[item]
        RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def clear(self):
        self._items.clear()
        self._idx_map.clear()

    def choose_random(self) -> Route:
        """Return a random element in O(1) time."""
        if not self._items:
            raise IndexError("Cannot select from an empty RandomSet")
        return random.choice(self._items)

    def pop_random(self) -> Route:
        """Remove and return a random element in O(1) time."""
        item = self.choose_random()
        self.remove(item)

        return item

    def choose_n(self, n: int) -> list[Route]:
        """Return n distinct random elements without removing them."""
        indices = random.sample(range(len(self._items)), n)
        return [self._items[i] for i in indices]

    def pop_n(self, n: int) -> list[Route]:
        """Remove and return n distinct random elements."""
        chosen = self.choose_n(n)
        self.difference_update(chosen)
        return chosen

    def pop_all(self, items: Iterable[Route]) -> list[Route]:
        """Remove and return all given items at once (each must already be present)."""
        items = list(items)
        self.difference_update(items)
        return items

    def update(self, iterable: Iterable[Route]):
        add = self._add_given_fields
        items = self._items
        idx_map = self._idx_map
        size = len(items)

        for item in iterable:
            size+=add(item, items, idx_map, size)

    def difference_update(self, iterable: Iterable[Route]):
        items = self._items
        idx_map = self._idx_map
        remove = RouteSet._remove_existing_item_given_fields
        for item in iterable:
            if item in idx_map:
                idx = idx_map[item]
                remove(item, idx, items, idx_map)

    def difference(self, other: Iterable[Route]) -> RouteSet:
        diff = RouteSet(self)
        diff.difference_update(other)
        return diff

    def union(self, other: Iterable[Route]) -> RouteSet:
        union = RouteSet(self)
        union.update(other)
        return union

    def intersection(self, other: Iterable[Route]) -> RouteSet:
        if isinstance(other, RouteSet|set):
            return self.intersection_with_set(other)

        return RouteSet(item for item in other if item in self)

    def intersection_with_set(self, other: set[Route] | RouteSet):
        if self.__len__() < len(other):
            return RouteSet(item for item in self if item in other)
        else:
            return RouteSet(item for item in other if item in self)

    def intersection_update(self, other: Iterable[Route]):
        other_set = other if isinstance(other, RouteSet|set) else set(other)

        remove = self._remove_existing_item_given_fields
        items = self._items
        idx_map = self._idx_map
        num_items = len(items)

        i = 0
        while i<num_items:
            item = items[i]
            if item not in other_set:
                remove(item, i, items, idx_map)
                num_items -= 1
            else:
                i+=1

    def symmetric_difference(self, other: Iterable[Route]) -> RouteSet:
        if isinstance(other, set | RouteSet) and len(self) < len(other):
            # Special case: dest_route is large and already a set. We can operate without copying dest_route.
            symmetric_difference = RouteSet(self)
            symmetric_difference.symmetric_difference_update_with_set(other)
            return symmetric_difference

        symmetric_difference = RouteSet(other)
        symmetric_difference.symmetric_difference_update_with_set(self)
        return symmetric_difference

    def symmetric_difference_update(self, other: Iterable[Route]):
        other_set = other if isinstance(other, RouteSet|set) else set(other)
        self.symmetric_difference_update_with_set(other_set)

    def symmetric_difference_update_with_set(self, other_set: set | RouteSet):
        remove = RouteSet._remove_existing_item_given_fields
        add = RouteSet._add_given_fields

        items = self._items
        idx_map = self._idx_map

        size = len(self)

        for item in other_set:
            if item in idx_map:
                idx = idx_map[item]
                remove(item, idx, items, idx_map)
                size -= 1
            else:
                size += add(item, items, idx_map, size)

    def issuperset(self, other: Iterable[Route]):
        if isinstance(other, set|RouteSet) and len(self) < len(other):
            return False

        idx_map = self._idx_map
        return all(item in idx_map for item in other)

    def issuperset_of_set(self, other: set[Route]|RouteSet):
        # Can shortcut as soon as we know #unchecked other items > #unmatched self items
        if len(self) < len(other):
            return False

        idx_map = self._idx_map
        return all(item in idx_map for item in other)

    def issubset(self, other: Iterable[Route]):
        if isinstance(other, set):
            return other.issuperset(self)
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)

        # Like intersect but with possible early exit
        idx_map = self._idx_map
        intersect = RouteSet()
        num_matches = 0
        num_items = self.__len__()
        if num_matches == num_items:
            return True

        for item in other:
            if item in idx_map:
                is_new = intersect.add(item)
                num_matches += is_new
                if is_new and num_matches==num_items:
                    return True

        return False

    def issubset_of_set(self, other: set[Route] | RouteSet):
        if len(self) > len(other):
            return False
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)
        return other.issuperset(self)

    def issubset_of_collection(self, other: Collection[Route]):
        if isinstance(other, set):
            return other.issuperset(self)
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)

        # You have more information than if other is Iterable: the length
        # But, less information than if other is set-like: can't check if items of self are in other or call other.superset

        # Can shortcut as soon as we know #unchecked other items > #unmatched self items
        idx_map = self._idx_map

        self_remaining = self.__len__()
        other_remaining = other.__len__()
        intersect = RouteSet()

        if self_remaining == 0:
            # Empty set is subset of all
            return True
        elif self_remaining > other_remaining:
            # Too many items in self
            return False

        for item in other:
            in_self = item in idx_map
            self_remaining -= in_self and intersect.add(item)
            other_remaining -= 1
            if self_remaining == 0:
                # All items in self have been seen in other!
                return True
            elif self_remaining > other_remaining:
                # Too many remaining unmatched items in self
                return False

        return False

    @staticmethod
    def _are_disjoint(set1: set[Route]|RouteSet, set2: Iterable[Route]) -> bool:
        for item in set2:
            if item in set1:
                return False

        return True

    def is_disjoint_with_set(self, other: set[Route]|RouteSet):
        if self.__len__() >= len(other):
            return RouteSet._are_disjoint(self, other)

        return RouteSet._are_disjoint(other, self)

    def is_disjoint(self, other: Iterable[Route]):
        return RouteSet._are_disjoint(self, other)

    def copy(self) -> RouteSet:
        return RouteSet(self)


    # Supports single indexing, but not slicing
    def __getitem__(self, idx: int) -> Route:
        return self._items[idx]

    def __contains__(self, item: object) -> bool:
        return item in self._idx_map

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Route]:
        return iter(self._items)

    def __add__(self, other: Iterable[Route]) -> RouteSet:
        return self.union(other)

    def __sub__(self, other: Iterable[Route]) -> RouteSet:
        return self.difference(other)


class Vehicle:
    # Unique vehicle id
    vID: int

    # Start depot for src_route
    initial_depot: Depot

    # Demand serviceable by vehicle on one src_route
    capacity: Num

    # Vehicle's part of core solution: RouteSet of routes
    # RouteSet choice: We never really care about "add/remove third src_route", only "add/remove src_route from vehicle, before/after target src_route, or at start/end"
    # RouteSet still lets us pick random routes from the vehicle, so that's all we really need. Routes maintain linkages.
    routes: RouteSet

    # Number of overloaded routes, carrying too much supply.
    num_routes_overloaded: int

    # Number of nonempty (active) routes. (NOTE: active routes can still be nontrivial! Another op will be required to deactivate them.)
    num_routes_with_customers: int

    # Total number of customers. A vehicle is active iff it serves customers.
    num_customers: int

    # First and last routes (head and tail)
    first_route: FirstRoute
    last_route: LastRoute

    # Currently does not access num_depot_uses, so we skip.

    def __init__(self, i=0, initial_depot: Depot=Depot(), capacity = -1): # type:ignore
        self.vID = i # data
        self.initial_depot = initial_depot # type:ignore # data
        self.capacity = capacity # data
        self.routes = RouteSet() # Core decision for the vehicle

        # Running counters, maintained incrementally by register_*_change_in_vehicle
        self.num_routes_overloaded = 0
        self.num_routes_with_customers = 0
        self.num_customers = 0

        first_route = FirstRoute(initial_depot)
        last_route = LastRoute(first_route)

        self.first_route = first_route
        self.last_route = last_route

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
    def split_route(self, route: Route, split_index: int, refill_depot: Depot) -> Route:
        if route.vehicle is not self:
            raise ValueError("route not assigned to current vehicle.")

        return route.split_at(split_index, refill_depot)

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


class FullSolution:
    # NOTE: annotations only -- no values. Every field is initialized per-instance in __init__.
    # These must never carry defaults: a class-level `vehicles: list = []` (or RouteSet()/defaultdict())
    # is created ONCE and shared by every FullSolution ever built, so in-place mutation
    # (all_routes.add, vehicles.append, depot_num_uses[d] += 1) leaks across instances.
    all_routes: RouteSet
    vehicles: list[Vehicle]

    empty_routes: RouteSet

    # Objective terms
    unit_travel_cost: Num
    cost_per_vehicle: Num
    cost_per_depot: Num

    # unit feasibility penalty for overloading a src_route. $1000 per unit to replace a broken truck should suffice XD
    # Strongly encourages splitting or reassigning customers from overloaded routes
    unit_overload_penalty: Num
    # Strongly discourages temporary src_route overloading. Per-vehicle computation prevents penalization of splitting
    # two severely overloaded routes into one far less overloaded src_route.
    vehicle_overload_penalty: Num  # activated feasibility penalty for overloading any vehicle in a src_route. Don't wanna replace the truck.

    # Problem data
    depots: list[Depot]
    customers: list[Customer]
    capacity_per_vehicle: list[Num]

    total_customer_capacity: Num
    mean_customer_capacity: Num

    min_vehicle_capacity: Num
    max_vehicle_capacity: Num
    mean_vehicle_capacity: Num
    total_vehicle_capacity: Num

    num_routes_lb: int

    depot_num_uses: defaultdict[Depot, int]

    # Bumped by OperatorBL.apply/revert. A cheap guard against applying a Move that was
    # evaluate()'d against a since-mutated solution.
    # TODO: currently only bumped in OperatorBL.apply/revert. If a hazard ever shows up where
    # something mutates the solution between an evaluate() and its matching apply() outside of
    # that pair (e.g. a future multi-operator lookahead), bump this in the core mutators too
    # (insert_customer, pop_customer_at, swap_customers, permute, set_end_depot,
    # link_to_vehicle_*, unlink_from_vehicle, split_at, combine_with).
    version: int

    def __init__(self):
        self.all_routes = RouteSet()
        self.vehicles = []

        self.empty_routes = RouteSet()

        # Objective terms
        self.unit_travel_cost = 0
        self.cost_per_vehicle = 0
        self.cost_per_depot = 0
        self.unit_overload_penalty = 1000
        self.vehicle_overload_penalty = 100000

        # Problem data
        self.depots = []
        self.customers = []
        self.capacity_per_vehicle = []

        self.total_customer_capacity = 0
        self.mean_customer_capacity = 0

        self.min_vehicle_capacity = 1e100
        self.max_vehicle_capacity = -1e100
        self.mean_vehicle_capacity = 0
        self.total_vehicle_capacity = 0

        self.num_routes_lb = -1

        self.depot_num_uses = defaultdict[Depot, int](int)

        self.version = 0

    #region Data setters
    def set_customers(self, customers):
        self.customers = customers
        self.total_customer_capacity = sum(c.demand for c in self.customers)
        self.mean_customer_capacity = self.total_customer_capacity / len(self.customers)

    def set_depots(self, depots):
        self.depots = depots

    def set_objectives(self, unit_travel_cost: Num, cost_per_vehicle: Num, cost_per_depot: Num,
                       unit_overload_penalty: Num = 1000, vehicle_overload_penalty: Num = 100000):
        self.unit_travel_cost = unit_travel_cost
        self.cost_per_vehicle = cost_per_vehicle
        self.cost_per_depot = cost_per_depot
        self.unit_overload_penalty = unit_overload_penalty
        self.vehicle_overload_penalty = vehicle_overload_penalty

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
    def cost_deltas_for_removing_empty_routes(routes: RouteSet) -> ObjectiveTermDelta:
        # Walks prev_route/next_route chains within the set of routes being removed, so adjacent
        # removals aren't double-counted, then accounts for each maximal chain's successor (if a
        # real Route) now starting where the chain started instead of where it ended.
        routes_remaining = routes.copy()
        num_routes = len(routes_remaining)
        if num_routes == 0:
            return ObjectiveTermDelta()

        depot_num_uses = next(iter(routes_remaining)).depot_num_uses
        travel_delta = 0
        depot_usage_deltas = defaultdict(int)
        routes_to_remove = []

        while num_routes > 0:
            first_in_sequence = routes_remaining[0]
            last_in_sequence = first_in_sequence

            predecessor = first_in_sequence.prev_route
            while predecessor in routes_remaining:
                assert isinstance(predecessor, Route)

                # Mark back-step to start of predecessor as distance no longer traveled, then slide backwards and mark predecessor for removal
                travel_delta -= predecessor.first_move_distance()
                routes_to_remove.append(predecessor)

                first_in_sequence = predecessor
                predecessor = first_in_sequence.prev_route

            successor = last_in_sequence.next_route
            while successor in routes_remaining:
                assert isinstance(successor, Route)

                # Mark forward-step to start of successor as distance no longer traveled, then slide forwards and mark last_in_sequence for removal
                travel_delta -= last_in_sequence.first_move_distance()
                routes_to_remove.append(last_in_sequence)

                last_in_sequence = successor
                successor = last_in_sequence.next_route # type: ignore - successor in routes_remaining implies... it's a Route

            # Here: last_in_sequence is the last route in the chain contained in remaining_routes. But: its move hasn't yet been counted!
            travel_delta -= last_in_sequence.first_move_distance()
            routes_to_remove.append(last_in_sequence)

            # The chain's successor (if a real Route, not a LastRoute sentinel) now starts where
            # the chain started, instead of where the chain ended.
            if isinstance(successor, Route):
                chain_start_depot = first_in_sequence.start_depot
                travel_delta += successor.first_visit.start_travel_delta_if_depot_swapped(chain_start_depot)
                append_new_defaultdict_by_value_sum(
                    depot_usage_deltas, successor.depot_num_usage_deltas_if_start_depot_changes(chain_start_depot))

            # Remove the routes
            routes_remaining.difference_update(routes_to_remove)
            num_routes = len(routes_remaining)
            routes_to_remove.clear()

        depots_activated = Route.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_num_uses)
        return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depots_activated)

    #endregion

    #region Route operations
    def choose_random_nonempty_route(self) -> Route|None:
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
            idx = random.randrange(0, num_options)
            if idx >= num_routes:
                route = vehicles[idx-num_routes].last_route
                break
            else:
                route = all_routes[idx]
                if route.is_assigned:
                    break
                else:
                    unassigned_routes: RouteSet = RouteSet() if unassigned_routes is None else unassigned_routes
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

        route.link_depot_uses(self.depot_num_uses)
        vehicle.append_route(route)
        self.all_routes.add(route)

    def add_route_to_vehicle_with_id(self, route: Route, vehicle_id: int):
        if vehicle_id >= len(self.vehicles) or vehicle_id < 0:
            raise ValueError("vehicle_id out of range")

        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        vehicle = self.vehicles[vehicle_id]
        route.link_depot_uses(self.depot_num_uses)
        vehicle.append_route(route)
        self.all_routes.add(route)

    def link_num_depot_uses_to_all(self):
        for route in self.all_routes:
            route.link_depot_uses(self.depot_num_uses)

    #endregion

    #region Objective computations
    def vehicles_used(self) -> int:
        return sum(vehicle.is_active for vehicle in self.vehicles)

    def depots_used(self) -> int:
        return sum(self.depot_num_uses[depot] >= 1 for depot in self.depots)

    def recompute_depots_used(self) -> int:
        return len(set(route.start_depot for route in self.all_routes if route.is_active))

    def depot_usage_breakdown(self) -> defaultdict[Depot, int]:
        usage = defaultdict(int)
        for route in self.all_routes:
            if route.is_active:
                usage[route.start_depot] += 1
        return usage

    def total_path_len(self) -> Num:
        return sum(route.total_distance() for route in self.all_routes)

    def num_overloaded_routes(self) -> int:
        return sum(route.is_overloaded for route in self.all_routes)

    def num_overloaded_vehicles(self) -> int:
        return sum(vehicle.has_overloaded_route for vehicle in self.vehicles)

    def total_overload(self):
        return sum(route.amount_overloaded for route in self.all_routes)

    def solution_cost(self):
        return (self.cost_per_vehicle * self.vehicles_used() +
                self.cost_per_depot * self.depots_used() +
                self.unit_travel_cost * self.total_path_len() +
                self.unit_overload_penalty * self.total_overload() +
                self.vehicle_overload_penalty * self.num_overloaded_vehicles())

    def objective_terms(self) -> ObjectiveTermDelta:
        # Absolute totals in the same 5-field shape as ObjectiveTermDelta, so deltas can be
        # checked against ground truth by diffing two calls to this. Also the measurement used
        # by OperatorBL._evaluate_by_applying for operators that can't price a move without
        # performing it.
        return ObjectiveTermDelta(
            travel_distance=self.total_path_len(), vehicles_activated=self.vehicles_used(),
            depots_activated=self.depots_used(), total_route_overload=self.total_overload(),
            vehicles_overloaded=self.num_overloaded_vehicles())
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

        # Copy problem data
        new_sln.depots = self.depots
        new_sln.customers = self.customers
        new_sln.capacity_per_vehicle = self.capacity_per_vehicle

        # Copy calculations derived from core solution and problem data
        new_sln.total_customer_capacity = self.total_customer_capacity
        new_sln.mean_customer_capacity = self.mean_customer_capacity

        new_sln.min_vehicle_capacity = self.min_vehicle_capacity
        new_sln.max_vehicle_capacity = self.max_vehicle_capacity
        new_sln.mean_vehicle_capacity = self.mean_vehicle_capacity
        new_sln.total_vehicle_capacity = self.total_vehicle_capacity

        new_sln.num_routes_lb = self.num_routes_lb

        new_sln.depot_num_uses = copy.copy(self.depot_num_uses)

        # __new__ bypasses __init__, so EVERY field must be set explicitly here -- there are no
        # class-level defaults to fall back on any more. These two are easy to forget:
        new_sln.empty_routes = RouteSet(route for route in new_sln.all_routes if route.is_empty)
        new_sln.version = self.version

        # Re-link depot_num_uses.
        # IMPORTANT to do it here so all objects see the copy of depot_num_uses instead of the original.
        new_sln.link_num_depot_uses_to_all()

        return new_sln


    def take_snapshot(self):
        # copy.copy invokes FullSolution.__copy__, which is much cheaper than deepcopy for a
        # solution of any real size. Only safe now that the Vehicle.__copy__ linkage bug is fixed
        # (see Phase 0) -- before that fix, copies had corrupted prev_route backlinks.
        snapshot = copy.copy(self)
        obj = snapshot.solution_cost()
        return obj, snapshot

    def __str__(self) -> str:
        return '\n'.join(str(vehicle) for vehicle in self.vehicles)

    def __repr__(self):
        return str(self)