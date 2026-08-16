import copy
import random
from bisect import bisect_left
from ftplib import all_errors

from itertools import chain

import numpy as np
from numpy import cumsum, ndarray

#from Temp_TimeIt import num_trials

from_iterable = chain.from_iterable

from typing import cast, Any, List, DefaultDict, Iterable, Iterator, Sequence, Collection
from collections import defaultdict
from math import hypot, ceil

from functools import lru_cache
from enum import Enum, auto
from typing import NamedTuple

from abc import ABC, abstractmethod

Num = float | int

# A run of consecutive customers within one route, addressed by position. One index is the
# single-customer case, so every chain operation subsumes the single-customer one and there is no
# second code path to keep in agreement.
Chain = int | range


def as_chain_range(customer_chain: Chain) -> range:
    """Normalise a Chain to a half-open range. Call this ONCE at the top of any chain method, so
    the rest of the body never has to ask which form it was handed."""
    return range(customer_chain, customer_chain + 1) if isinstance(customer_chain, int) else customer_chain


#region Randomness
# Single source of randomness for the whole solver: operand selection, RouteSet sampling, and the
# Metropolis coin all draw from here. Owning one explicit generator (rather than the process-wide
# `random` module) means a run is reproducible from one seed and cannot be perturbed by unrelated
# code -- test harnesses, notebooks, library internals -- drawing from the global stream.
#
# Reproducibility matters here beyond tidiness: the solver is a long random walk, so a single
# extra draw anywhere permanently diverges the trajectory. That is what makes an intermittent
# bug non-bisectable, and it is why instrumenting a failing run can make the failure disappear.
#
# WHY random.Random AND NOT np.random.Generator: the guarantee we need is one OWNED, seeded
# stream -- isolated from anything else in the process -- and a Random instance gives exactly
# that. numpy's Generator gives the same isolation but is built for bulk array generation, so
# every scalar draw pays array machinery: measured at ~6-8x the stdlib cost per call
# (rand_index 0.91us vs 0.13us, rand_choice 0.91us vs 0.12us, distinct-pair 4.50us vs 1.02us).
# The solver only ever draws scalars, millions of times, so that overhead is pure loss.
solver_rng: random.Random = random.Random()


def seed_solver_rng(seed) -> random.Random:
    """Reseed the shared generator. Call once before a solve to make it reproducible."""
    global solver_rng
    solver_rng = random.Random(seed)
    return solver_rng


def rand_unit() -> float:
    """Uniform float in [0, 1)."""
    return solver_rng.random()


def rand_index(num_options: int) -> int:
    """Uniform index in [0, num_options)."""
    return solver_rng.randrange(num_options)


def rand_int_inclusive(low: int, high: int) -> int:
    """Uniform int in [low, high] -- INCLUSIVE upper bound, as randint defines it."""
    return solver_rng.randint(low, high)


def rand_choice(sequence):
    """Uniform element of a sequence supporting len() and indexing (including RouteSet)."""
    return solver_rng.choice(sequence)


def rand_distinct_indices(num_options: int, count: int) -> list[int]:
    """`count` distinct indices from [0, num_options)."""
    return solver_rng.sample(range(num_options), count)


def rand_shuffle(items: list) -> None:
    """In-place shuffle."""
    solver_rng.shuffle(items)
#endregion

#region Global helper functions

def combine_defaultdicts_by_value_sum[T1: Any](dict1: defaultdict[T1, Any], dict2: defaultdict[T1, Any]) -> defaultdict[T1, Any]:
    # Copy-combines and returns new
    result: defaultdict[T1, Any] = defaultdict(dict1.default_factory)

    all_keys = dict1.keys() | dict2.keys()

    for key in all_keys:
        result[key] = dict1[key] + dict2[key]

    return result

def append_new_defaultdict_by_value_sum[T1: Any](dict1: defaultdict[T1, Any], dict2: defaultdict[T1, Any]) -> None:
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
    depot_route_starts: DefaultDict[Depot, RouteSet]


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

    def change_depot_uses(self, depot: Depot, route: Route, num_uses_delta: int):
        """
        Record or un-record `route` as STARTING at `depot`.

        The route is passed rather than read from self.route: a set stores identity, so a stale
        back-pointer (which __copy__ can produce) would silently insert the wrong object where a
        counter could not have noticed. Every caller already holds the route.
        """
        if depot.is_virtual_depot:
            raise ValueError("Virtual depots cannot be used.")

        if num_uses_delta > 0:
            self.depot_route_starts[depot].add(route)
        elif num_uses_delta < 0:
            self.depot_route_starts[depot].discard(route)

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
        return route.is_inactive_after_customers_removed()

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
        # Only unlinks src_route and uncounts src_route from vehicle and updates depot accounting.
        # Does not process loading changes or vehicle accounting, since some of those operations
        # must be performed before the src_route's path is mutated.
        route = self.route
        if route is None:
            raise ValueError(f"Cannot unlink CustomerVisit {self.cID}: it is already unlinked!")

        # If it's the last in the src_route, the src_route goes inactive and stops using its start depot.
        # NOTE: this is the USAGE-COUNT question ("does depot_route_starts drop by 1"), NOT the
        # activation question ("does the depot go from used to unused"). Gating this on
        # will_deactivate_depot_if_removed() instead would skip the decrement whenever 2+ routes
        # start at that depot, leaving depot_route_starts permanently too high.
        if self.will_decrement_depot_usage_if_removed():
            self.prev_visit.uncount_route_depot_use(route) # type: ignore - If it decrements: src_route exists and this is its only customer, so prev visit is a FirstRouteVisit

        # Link neighbors
        prev_visit = self.prev_visit
        next_visit = self.next_visit

        prev_visit.next_visit = next_visit
        next_visit.prev_visit = prev_visit

        # Unlink self from src_route
        self.route = None
        self.prev_visit = None # type: ignore # None only for a short bit
        self.next_visit = None # type: ignore # none only for a short bit

    def unlink_from_route_no_depot_accounting(self):
        # Only unlinks src_route and uncounts src_route from vehicle.
        # Does not process loading changes or vehicle accounting, since some of those operations
        # must be performed before the src_route's path is mutated.
        if self.route is None:
            raise ValueError(f"Cannot unlink CustomerVisit {self.cID}: it is already unlinked!")

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
        return len(self.depot_route_starts[self.source_depot])

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

    def count_route_depot_use(self, route: Route):
        self.change_depot_uses(self.source_depot, route, 1)

    def uncount_route_depot_use(self, route: Route):
        self.change_depot_uses(self.source_depot, route, -1)

    def change_my_depot_uses(self, route: Route, num_uses_delta: int):
        self.change_depot_uses(self.source_depot, route, num_uses_delta)

    def replace_depot(self, new_depot: Depot):
        # If the depot is unchanged, return or both current and new depots are virtual
        if self.depot_is(new_depot):
            return

        # 1. If the current src_route is assigned to a vehicle, swap which depot counts this src_route (only for "counted" routes)
        # - Decrements old usage if old src_route was nontrivial and depot changed
        # - Increments new usage if depot changed and new src_route is nontrivial after the change
        # Virtual depots are never counted, so skip the corresponding side entirely rather than
        # asking change_depot_uses to accept a virtual depot.
        # The one site that must read self.route: a FirstRouteVisit swapping its own depot. It is
        # a linked, post-construction visit here, so the back-pointer is set.
        own_route = self.route
        assert own_route is not None, "FirstRouteVisit.replace_depot on an unlinked visit"
        if not self.source_depot.is_virtual_depot:
            self.change_my_depot_uses(own_route, -self.will_depot_swap_decrement_current_depot_usage(new_depot))
        if not new_depot.is_virtual_depot:
            self.change_depot_uses(new_depot, own_route, self.will_depot_swap_increment_new_depot_usage(new_depot))

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


class NextRouteKind(Enum):
    """
    What follows a route in its vehicle chain. Names the three-state distinction that a bare
    `next_route is not None` check silently collapses into two -- the single most common bug
    shape in this model, since a LastRoute sentinel passes an `is not None` guard and then fails
    on any Route-only attribute.
    """
    NONE       = auto()   # route is unassigned: no successor at all
    ROUTE      = auto()   # a real successor Route, which owns a FirstRouteVisit to chain into
    LAST_ROUTE = auto()   # the vehicle's tail sentinel: stores a start_depot, has no visits


class LastRouteVisit(Depot, RouteVisit):
    prev_visit: CustomerVisit | FirstRouteVisit # prev visit is never None
    #next_visit: FirstRouteVisit | None # next visit is either None or the start of the next src_route

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
        # NOTE: a None here means "no next VISIT", which is NOT the same as "no next route" --
        # the tail sentinel has a start_depot but no visits. Use next_route_type when the
        # difference matters, and replace_next_start_depot/get_next_start_depot to act on it.
        next_route = self.route.next_route
        if isinstance(next_route, Route):
            return next_route.first_visit

        return None

    @property
    def next_route_type(self) -> NextRouteKind:
        """Which of the three successor states this route is in. See NextRouteKind."""
        route = self.route
        next_route = route.next_route if route is not None else None

        if isinstance(next_route, Route):
            return NextRouteKind.ROUTE
        if isinstance(next_route, LastRoute):
            return NextRouteKind.LAST_ROUTE
        return NextRouteKind.NONE

    def get_next_start_depot(self) -> Depot | None:
        """
        The depot the successor starts from, whichever kind of successor it is.
        None only when this route is unassigned (no successor at all).
        """
        kind = self.next_route_type
        if kind is NextRouteKind.NONE:
            return None

        route = self.route
        assert route is not None   # guaranteed by kind != NONE
        next_route = route.next_route

        if kind is NextRouteKind.ROUTE:
            assert isinstance(next_route, Route)
            return next_route.start_depot

        assert isinstance(next_route, LastRoute)
        return next_route.start_depot

    def replace_next_start_depot(self, new_depot: Depot) -> None:
        """
        Push this route's new end depot onto whatever follows it, so the successor's recorded
        start depot never drifts from this route's end depot.

        Both successor kinds must be handled: a real Route carries the change through its
        FirstRouteVisit (which also does the depot-usage accounting), while the tail sentinel
        just stores the depot. Updating only the Route case leaves LastRoute.start_depot stale
        as soon as a vehicle's FINAL route changes end depot -- which silently corrupts
        Vehicle.final_depot and any "insert before LastRoute" pricing that reads
        next_route.start_depot to determine the moved route's new start.
        """
        kind = self.next_route_type
        if kind is NextRouteKind.NONE:
            return   # unassigned route: nothing downstream to update

        route = self.route
        assert route is not None   # guaranteed by kind != NONE
        next_route = route.next_route

        if kind is NextRouteKind.ROUTE:
            assert isinstance(next_route, Route)
            next_route.first_visit.replace_depot(new_depot)
            return

        assert isinstance(next_route, LastRoute)
        next_route.set_start_depot(new_depot)

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

    # DEAD, deliberately kept commented rather than deleted. These wrote END-depot usage into
    # depot_route_starts, which counts route STARTS only -- calling them corrupts it. Nothing calls
    # them today; a decrement path used to, and only escaped notice because a buggy guard was
    # almost always false (see test_core_model_regressions, combine-revert end-depot test).
    # They may come back if end-depot usage is ever tracked properly -- see
    # TODO(end-depot-index) on SwapRouteTailsAtSharedDepot for why that is not cheap.
    #
    # def count_route_in_depot(self):
    #     self.change_depot_uses(self.source_depot, 1)
    #
    # def uncount_route_in_depot(self):
    #     self.change_depot_uses(self.source_depot, -1)

    #def change_my_depot_uses(self, num_uses_delta: int):
    #    self.change_depot_uses(self.source_depot, num_uses_delta)

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

        # 1. Update whatever follows this src_route, so its start depot tracks our new end depot.
        # Handles both successor kinds (real Route and tail sentinel); see the method.
        self.replace_next_start_depot(new_depot)

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

# region Route-like objects, including start-route and end-route
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

        depot_route_starts: defaultdict[Depot, RouteSet]

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

        def is_inactive_after_customers_removed(self, num_customers: int = 1) -> bool:
            # ASSUME here: the removal is valid - src_route holds at least num_customers
            # Will be inactive if it is unassigned or if the removal takes every customer it has.
            return self.vehicle is None or self.path_len == num_customers

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

        def deactivates_after_customers_removed(self, num_customers: int = 1) -> bool:
            # ASSUME here: the removal is valid - src_route holds at least num_customers
            return self.is_active and self.is_inactive_after_customers_removed(num_customers)

        def deactivates_after_customer_popped(self, num_customers: int = 1) -> bool:
            return self.deactivates_after_customers_removed(num_customers)

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
                                                               depot_route_starts: defaultdict[Depot, RouteSet]) -> int:
            if not depot_usage_deltas:
                # No-changes case
                return 0

            result = 0
            """ Result will report:
            +1 for each depot that transitions from 0 to some uses,
            -1 for each that transitions from some uses to no uses.
            """
            for (depot, usage_deltas) in depot_usage_deltas.items():
                uses = len(depot_route_starts[depot])
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
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_num_usage_deltas, depot_route_starts=self.depot_route_starts)

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
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_route_starts=self.depot_route_starts)

        def depot_activation_delta_if_inserted_before(self, route: Route|LastRoute) -> int:
            depot_usage_deltas = self.depot_num_usage_deltas_if_inserted_before(route)
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_route_starts=self.depot_route_starts)

        def depot_activation_delta_if_appended_to(self, vehicle) -> int:
            depot_usage_deltas = self.depot_num_usage_deltas_if_appended_to(vehicle)
            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_route_starts=self.depot_route_starts)
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

        #region Vehicle activation deltas

        # NOTE: Active routes does not imply an active vehicle.
        # Active vehicle = "vehicle has customers"
        # Active src_route = "src_route moves something and it's assigned to an active vehicle"
        def vehicle_deactivates_if_customers_removed(self, num_customers: int = 1) -> bool:
            # For a customer removal to deactivate our vehicle:
            #   It must take every customer the vehicle has, across all of its routes.
            vehicle = self.vehicle
            return vehicle is not None and vehicle.num_customers == num_customers

        def vehicle_activation_delta_if_customers_added(self, customer_route: Route, customer_vehicle: Vehicle|None,
                                                        num_customers: int = 1) -> int:
            vehicle = self.vehicle

            same_vehicle = vehicle is not None and customer_vehicle == vehicle

            if same_vehicle:
                # Move in same vehicle has no effect on activation
                return 0
            else:
                vehicle_activates = vehicle is not None and vehicle.is_inactive
                customer_vehicle_deactivates = customer_route is not None and customer_route.vehicle_deactivates_if_customers_removed(num_customers)

                return vehicle_activates - customer_vehicle_deactivates

        #endregion

        #region Depot activation deltas
        def depot_deactivates_if_customers_removed(self, num_customers: int = 1) -> bool:
            return self.deactivates_after_customers_removed(num_customers) and self.first_visit.num_routes_starting_here == 1

        def depot_activation_delta_if_customers_added(self, customer_route: Route, num_customers: int = 1) -> int:
            same_route = customer_route == self
            if same_route:
                return 0
            else:
                start_depot = self.start_depot
                customer_route_start_depot = customer_route.start_depot
                if start_depot != customer_route_start_depot:
                    start_depot_activates = self.activates_after_customer_insert() and self.first_visit.num_routes_starting_here == 0
                    customer_start_depot_deactivates = customer_route.depot_deactivates_if_customers_removed(num_customers)

                    return start_depot_activates - customer_start_depot_deactivates
                else:
                    return 0


        #endregion

        #region Overload-related deltas
        def overload_deltas_if_customer_removed(self, customer: CustomerVisit) -> tuple[Num, int]:
            load_delta = -customer.demand

            overload_delta = self.overload_delta_if_load_changes(load_delta)
            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes(load_delta)

            return overload_delta, vehicles_overloaded_delta

        def overload_deltas_if_customer_popped(self, index: int) -> tuple[Num, int]:
            return self.overload_deltas_if_customer_removed(self.path[index])

        def overload_deltas_if_load_added(self, load_delta: Num, customer_route: Route) -> tuple[Num, int]:
            # Takes the load rather than the customers: summing demand over a chain is the
            # expensive part, and callers already need that total for their own accounting, so
            # they compute it once and pass it in.
            same_route = customer_route == self

            if same_route:
                # Intra-route move! No change.
                return 0, 0

            route_overload_delta = self.overload_delta_if_load_changes(load_delta)
            customer_route_overload_delta = customer_route.overload_delta_if_load_changes(-load_delta)
            overload_delta = route_overload_delta + customer_route_overload_delta

            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes_from_other_route(load_delta, customer_route)

            return overload_delta, vehicles_overloaded_delta
        #endregion

        #region Full deltas
        def cost_deltas_if_customer_removed(self, customer):
            travel_delta = self.travel_delta_if_customer_removed(customer)
            vehicle_delta = -self.vehicle_deactivates_if_customers_removed()
            depot_delta = -self.depot_deactivates_if_customers_removed()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_removed(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_customer_popped(self, index):
            travel_delta = self.travel_delta_if_customer_popped(index)
            vehicle_delta = -self.vehicle_deactivates_if_customers_removed()
            depot_delta = -self.depot_deactivates_if_customers_removed()

            overload_delta, num_vehicles_overloaded_delta = self.overload_deltas_if_customer_popped(index)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta, num_vehicles_overloaded_delta)

        def cost_deltas_if_customer_inserted_before(self, customer: CustomerVisit, insert_visit: CustomerVisit | LastRouteVisit) -> ObjectiveTermDelta:
            if insert_visit is customer or insert_visit is customer.next_visit:
                return ObjectiveTermDelta() # No-op!

            customer_route: Route | None = customer.route
            customer_vehicle = None if customer_route is None else customer_route.vehicle

            assert isinstance(insert_visit, CustomerVisit|LastRouteVisit)
            assert isinstance(customer_route, Route)

            # DECISION: We don't compute full cost deltas explicitly for unassigned customers.
            # IN THE EVENT we choose to add support for this (e.g. for multi-day delivery plans where some customers don't get deliveries):
            # We will split into "Unassigned" and "Assigned" versions for add/insert operations, and this method
            # will triage between the two.

            travel_delta = Route.travel_delta_if_customer_inserted_before(customer, insert_visit, customer_route)
            depot_delta = self.depot_activation_delta_if_customers_added(customer_route)
            vehicle_activation_delta = self.vehicle_activation_delta_if_customers_added(customer_route, customer_vehicle)
            (overload_delta, num_vehicles_overloaded_delta) = self.overload_deltas_if_load_added(customer.demand, customer_route)

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_delta,
                                      vehicles_activated=vehicle_activation_delta, total_route_overload=overload_delta,
                                      vehicles_overloaded=num_vehicles_overloaded_delta)


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

        def cost_deltas_if_customer_chain_removed(self, chain: Chain) -> ObjectiveTermDelta:
            """
            Price taking `chain` out of this route, charged BEFORE the removal happens.

            A chain of one is the single-customer removal, so this widens
            cost_deltas_if_customer_removed rather than sitting beside it.
            """
            rng = as_chain_range(chain)
            k = len(rng)
            if k == 0:
                return ObjectiveTermDelta()

            path = self.path
            chain_load = sum(path[i].demand for i in rng)

            return ObjectiveTermDelta(
                travel_distance=self.travel_delta_if_customer_chain_removed(rng),
                vehicles_activated=-self.vehicle_deactivates_if_customers_removed(k),
                depots_activated=-self.depot_deactivates_if_customers_removed(k),
                total_route_overload=self.overload_delta_if_load_changes(-chain_load),
                vehicles_overloaded=self.is_vehicle_overloaded_delta_if_load_changes(-chain_load))

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
        ) -> tuple[ObjectiveTermDelta, ObjectiveTermDelta]:
            """
            Price splicing detached `visits` into THIS route before insert_visit.

            Returns (not_reversed, reversed); only travel_distance differs between them. Makes no
            decision -- the caller picks, exactly as cost_deltas_if_customer_chain_moved does.

            Destination-only by design: `visits` are detached, so there is no source route to
            offset against. Whoever detached them already charged that side.
            """
            k = len(visits)
            if k == 0:
                return ObjectiveTermDelta(), ObjectiveTermDelta()

            chain_load = sum(visit.demand for visit in visits)
            vehicle = self.vehicle

            # The destination halves of depot_activation_delta_if_customers_added and
            # vehicle_activation_delta_if_customers_added, with the source subtraction dropped.
            vehicle_delta = int(vehicle is not None and vehicle.is_inactive)
            depot_delta = int(self.activates_after_customer_insert()
                              and self.first_visit.num_routes_starting_here == 0)
            overload_delta = self.overload_delta_if_load_changes(chain_load)
            vehicles_overloaded_delta = self.is_vehicle_overloaded_delta_if_load_changes(chain_load)

            fwd_travel, rev_travel = Route.travel_deltas_if_customer_chain_inserted_before(
                visits, insert_visit)

            def terms(travel: Num) -> ObjectiveTermDelta:
                return ObjectiveTermDelta(travel_distance=travel, vehicles_activated=vehicle_delta,
                                          depots_activated=depot_delta,
                                          total_route_overload=overload_delta,
                                          vehicles_overloaded=vehicles_overloaded_delta)

            return terms(fwd_travel), terms(rev_travel)
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
                                                dest_idx: int) -> tuple[ObjectiveTermDelta, ObjectiveTermDelta]:
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
                # No customer crosses a route boundary, so load, depot and vehicle are untouched.
                return (ObjectiveTermDelta(travel_distance=fwd_travel),
                        ObjectiveTermDelta(travel_distance=rev_travel))

            chain_load = sum(self.path[i].demand for i in rng)
            depot_delta = dest_route.depot_activation_delta_if_customers_added(self, k)
            vehicle_delta = dest_route.vehicle_activation_delta_if_customers_added(self, self.vehicle, k)
            (overload_delta,
             vehicles_overloaded_delta) = dest_route.overload_deltas_if_load_added(chain_load, self)

            def terms(travel: Num) -> ObjectiveTermDelta:
                return ObjectiveTermDelta(travel_distance=travel, vehicles_activated=vehicle_delta,
                                          depots_activated=depot_delta,
                                          total_route_overload=overload_delta,
                                          vehicles_overloaded=vehicles_overloaded_delta)

            return terms(fwd_travel), terms(rev_travel)
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
        def total_overload_deltas_for_load_swap(route1: Route, route2: Route, route1_load_delta: Num) -> tuple[Num, int]:
            # Takes the load moving INTO route1 rather than the customers moving, so a chain swap
            # can sum its demands once and reuse this unchanged. Returns
            # (total_route_overload_delta, num_vehicles_overloaded_delta).
            if route1 is route2:
                # Load is unchanged! Intra-route swap: demand never leaves the route.
                return 0, 0

            route1_overload_delta = route1.overload_delta_if_load_changes(route1_load_delta)
            route2_overload_delta = route2.overload_delta_if_load_changes(-route1_load_delta)

            num_vehicles_overloaded_delta = route1.is_vehicle_overloaded_delta_if_load_changes_from_other_route(route1_load_delta, route2)

            return route1_overload_delta + route2_overload_delta, num_vehicles_overloaded_delta

        @staticmethod
        def total_overload_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit) -> tuple[Num, int]:
            route1 = customer1.route
            route2 = customer2.route

            if route1 is None or route2 is None:
                raise ValueError("Cannot swap customers that aren't assigned to routes!")

            # current_route_load_delta_if_swapped_with, not a bare demand difference: it reduces
            # numerical error when both customers share a route.
            route1_load_delta = customer1.current_route_load_delta_if_swapped_with(customer2)
            return Route.total_overload_deltas_for_load_swap(route1, route2, route1_load_delta)

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

        def customer_chains_are_adjacent(self, chain: Chain, other: Route, other_chain: Chain) -> bool:
            # Only possible within one route. Adjacent chains share a boundary arc, which makes
            # the two reversals interact -- see cost_deltas_for_customer_chain_swap.
            if self is not other:
                return False
            rng1, rng2 = as_chain_range(chain), as_chain_range(other_chain)
            return rng1.stop == rng2.start or rng2.stop == rng1.start

        def cost_deltas_for_customer_chain_swap(self, chain: Chain, other: Route, other_chain: Chain
                                                ) -> tuple[ObjectiveTermDelta, ObjectiveTermDelta,
                                                           ObjectiveTermDelta, ObjectiveTermDelta]:
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
                moved = self.cost_deltas_if_customer_chain_moved(early, self, early.start + len(late))
                moved_travel = (moved[0].travel_distance, moved[1].travel_distance)

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

                travels = (travel(False, False), travel(True, False),
                           travel(False, True), travel(True, True))
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

                travels = (there_fwd + here_fwd, there_rev + here_fwd,
                           there_fwd + here_rev, there_rev + here_rev)

            # No vehicles_activated or depots_activated terms. Both chains are non-empty (the BL
            # guards it), so each route keeps at least one customer and neither can empty. If that
            # guard ever goes, these terms come back.
            chain1_load = sum(path1[i].demand for i in rng1)
            chain2_load = sum(path2[j].demand for j in rng2)
            overload_delta, vehicles_overloaded_delta = Route.total_overload_deltas_for_load_swap(
                self, other, chain2_load - chain1_load)

            return tuple(  # type: ignore - fixed length 4, built from a 4-tuple
                ObjectiveTermDelta(travel_distance=t, total_route_overload=overload_delta,
                                   vehicles_overloaded=vehicles_overloaded_delta)
                for t in travels)
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
            depot_activation_delta = int(len(self.depot_route_starts[refill_depot]) == 0)

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

            return self.depot_activation_delta_from_depot_num_usage_deltas(depot_activation_deltas, depot_route_starts=self.depot_route_starts)

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
            return -(other.has_customers and len(self.depot_route_starts[other.start_depot]) == 1)

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

        #region Reversing/reassigning subpaths

        #region Reversing a subpath
        def cost_deltas_if_customer_chain_reversed(self, chain: Chain) -> ObjectiveTermDelta:
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

            return ObjectiveTermDelta(travel_distance=new_distance-old_distance)


        #endregion

        #endregion

        def cost_deltas_if_swapped_with_next_route(self):
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
                return ObjectiveTermDelta()

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
            depot_activation_delta = self.depot_activation_delta_from_depot_num_usage_deltas(all_depot_num_use_deltas, depot_route_starts=self.depot_route_starts)

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
                self.last_visit.prev_visit = self.first_visit
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
        def link_depot_uses(self, depot_route_starts: defaultdict[Depot, RouteSet]):
            self.depot_route_starts = depot_route_starts

            self.first_visit.depot_route_starts = depot_route_starts
            self.last_visit.depot_route_starts = depot_route_starts

            for visit in self.path:
                visit.depot_route_starts = depot_route_starts

        # To be called only when a new src_route is created during mid-solve.
        # Currently, only a few operations can do this, like Split()
        def link_depot_uses_except_customers(self, depot_route_starts: defaultdict[Depot, RouteSet]):
            self.depot_route_starts = depot_route_starts

            self.first_visit.depot_route_starts = depot_route_starts
            self.last_visit.depot_route_starts = depot_route_starts

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
            # Just inserts the customer. Updates start depot's "num_used" if the this route goes
            # inactive -> active. Mirrors CustomerVisit.unlink_from_route's decrement: the rule is
            # "uses its depot" = "has customers AND is assigned" (is_active), NOT is_trivial --
            # an empty route with start != end is non-trivial but still inactive/uncounted.
            if self.is_inactive and self.is_active_after_customer_add():
                self.first_visit.count_route_depot_use(self)

            self.register_customer_add_in_vehicle()
            self.count_load_change(customer.demand)

            self.path.insert(index, customer)
            self.link_customer(index)

        def append_customer(self, customer):
            # Just appends the customer. Same inactive -> active depot-usage rule as insert_customer.
            if self.is_inactive and self.is_active_after_customer_add():
                self.first_visit.count_route_depot_use(self)

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

            # Remove the tail of the path from the original src_route, and update customer linkages without affecting vehicle customer accounting.

            # We've removed some customers! So un-count them from the vehicle.
            # They'll be re-counted on insertion of the new src_route.
            self.register_num_customers_change_in_vehicle(-new_route.num_customers, is_route_operation=False)

            self.path = path[:split_index]
            self.relink_customer(split_index-1)
            new_route.relink_customer(0)

            new_route.link_depot_uses_except_customers(self.depot_route_starts)

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
                    path[span_start + offset].replace_customer_with_customer_from_same_route(customer)

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

            # Both of these read path_len, so they must run before the path shrinks.
            self.register_num_customers_change_in_vehicle(-k, is_route_operation=False)
            self.count_load_change(-sum(visit.demand for visit in removed))

            was_active = self.is_active
            path[rng.start:rng.stop] = []
            prev_visit.next_visit = next_visit
            next_visit.prev_visit = prev_visit

            # Mirror of insert_customer's inactive -> active increment. unlink_from_route asks this
            # per customer via will_decrement_depot_usage_if_removed(), which only fires on the
            # last one; removing a whole chain reaches the same state in one step.
            if was_active and self.is_inactive:
                self.first_visit.uncount_route_depot_use(self)

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

            if self.is_inactive and self.is_active_after_customer_add():
                self.first_visit.count_route_depot_use(self)

            self.register_num_customers_change_in_vehicle(k, is_route_operation=False)
            self.count_load_change(sum(visit.demand for visit in visits))

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


class RouteSet:
    """Class for a set supporting random choice. Expanded and optimized greatly from Gemini-generated version."""
    """A set-like container supporting O(1) add, remove, lookups, and random choice."""

    def __init__(self, iterable: Iterable[Route] = ()):
        self._items: list[Route] = []
        self._idx_map: dict[Route, int] = {}
        for item in iterable:
            self.add(item)


    # NOTE on ORDER: removal is swap-with-last, so a remove -> add round trip restores membership
    # but NOT position. That matters because the solver picks operands positionally
    # (rand_choice indexes _items), so a permutation of this list silently changes which route a
    # random draw returns -- i.e. an operator's revert can be perfectly value-correct and still
    # divert the whole search. remove() therefore reports where it moved the displaced element,
    # and add() can put a re-added element straight back there; see undo_remove().

    @staticmethod
    def _add_given_fields(item: Route, items: list[Route], idx_map: dict[Route, int], size,
                          post_add_swap_index: int | None = None) -> bool:
        if item in idx_map:
            return False

        idx_map[item] = size
        items.append(item)

        # Only meaningful for a TRUE add (we returned above otherwise): put the newly appended
        # item back at post_add_swap_index and push whatever sits there to the end -- the exact
        # inverse of the swap-with-last that removal performs.
        if post_add_swap_index is not None and post_add_swap_index != size:
            assert post_add_swap_index is not None # Linter is dumb hurr durr
            displaced = items[post_add_swap_index]
            items[post_add_swap_index] = item
            items[size] = displaced
            idx_map[item] = post_add_swap_index
            idx_map[displaced] = size

        return True

    def add(self, item: Route, post_add_swap_index: int | None = None) -> bool:
        return RouteSet._add_given_fields(item, self._items, self._idx_map, self.__len__(),
                                          post_add_swap_index)

    def undo_remove(self, item: Route, swap_index: int | None) -> bool:
        """
        Re-add `item` at the position it occupied before a remove(), restoring this set's ORDER
        and not just its membership. `swap_index` is remove()'s return value.
        """
        return self.add(item, post_add_swap_index=swap_index)

    @staticmethod
    def _remove_existing_item_given_fields(item: Route, idx: int, items: List[Route], idx_map: dict[Route, int]) -> int:
        # Not worth doing this only if needed: cpu instruction flushing is worse than just 3 ops unnecessarily
        last_item = items[-1]

        # Swap target item with the last item in the list
        items[idx] = last_item
        idx_map[last_item] = idx

        # Remove the target item
        items.pop()
        del idx_map[item]

        # Where the removed item sat, so undo_remove() can restore ordering exactly.
        return idx

    def remove(self, item: Route) -> int:
        idx_map = self._idx_map
        if item not in idx_map:
            raise KeyError(item)

        idx = idx_map[item]
        return RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def discard(self, item: Route) -> int | None:
        idx_map = self._idx_map
        if item not in idx_map:
            return None

        idx = idx_map[item]
        return RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def clear(self):
        self._items.clear()
        self._idx_map.clear()

    def choose_random(self) -> Route:
        """Return a random element in O(1) time."""
        if not self._items:
            raise IndexError("Cannot select from an empty RandomSet")
        return rand_choice(self._items)

    def pop_random(self) -> Route:
        """Remove and return a random element in O(1) time."""
        item = self.choose_random()
        self.remove(item)

        return item

    def choose_n(self, n: int) -> list[Route]:
        """Return n distinct random elements without removing them."""
        indices = rand_distinct_indices(len(self._items), n)
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

    def difference_update(self, iterable: Iterable[Route]) -> list[tuple[Route, int]]:
        """
        Remove every item of `iterable` that is present.

        Returns (item, swap_index) records in REMOVAL ORDER -- exactly the order and format
        undo_difference_update() expects, so an undoable removal is just:
            removed = routes.difference_update(victims)
            ...
            routes.undo_difference_update(removed)
        """
        items = self._items
        idx_map = self._idx_map
        remove = RouteSet._remove_existing_item_given_fields
        removed: list[tuple[Route, int]] = []
        for item in iterable:
            if item in idx_map:
                idx = idx_map[item]
                remove(item, idx, items, idx_map)
                removed.append((item, idx))
        return removed

    def undo_difference_update(self, removed: list[tuple[Route, int]]) -> None:
        """
        Exact inverse of difference_update: restores membership AND position.

        Replayed in reverse, because each recorded swap_index is only meaningful against the
        state that immediately preceded that particular removal.
        """
        for item, swap_index in reversed(removed):
            self.undo_remove(item, swap_index)

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


#region Nearest-neighbor tables
# How many nearest customers each customer remembers. Consumed by the neighbor-guided operators,
# which scan a candidate route testing membership -- so this is "how wide is near", not a budget.
CUSTOMER_NEIGHBORS_K = 20

# How many nearest depots each customer remembers. Instances have very few depots, so this is
# usually all of them.
CUSTOMER_DEPOTS_K = 10


def nearest_indices(sources: ndarray, targets: ndarray, k: int, exclude_self: bool,
                    chunk: int = 512) -> list[tuple[int, ...]]:
    """
    For each row of `sources`, the indices of its `k` nearest rows in `targets`, nearest first.

    Chunked so peak memory is bounded by `chunk * len(targets)` rather than the full pairwise
    matrix -- 20MB per chunk at 5000 targets, against 200MB for the whole thing.

    O(len(sources) * len(targets)) work, but entirely inside numpy. An incremental "keep a sorted
    top-k, insert when closer than the last" loop has the same asymptotic cost with the Python
    interpreter's constant factor on top, which is around 100x worse here. Genuinely sub-quadratic
    needs a k-d tree or grid bucketing; neither is worth it below roughly 50k customers.

    Squared distances are compared, never rooted. sqrt is monotonic, so the ordering is identical
    and the per-pair cost drops.

    TIES BREAK BY INDEX, deterministically. Coordinates here are integers on a small lattice, so
    equal distances are common rather than exotic, and `argmin` -- which callers are replacing with
    these tables -- resolves a tie by taking the lowest index. lexsort reproduces that rule exactly;
    plain argsort would not, since its default quicksort is unstable.
    """
    limit = len(targets) - (1 if exclude_self else 0)
    k = min(k, limit)
    if k <= 0:
        return [() for _ in range(len(sources))]

    out: list[tuple[int, ...]] = []
    for start in range(0, len(sources), chunk):
        block = sources[start:start + chunk]
        squared = ((block[:, None, :] - targets[None, :, :]) ** 2).sum(axis=-1)
        if exclude_self:
            # sources IS targets here, so row i of this block is target start + i.
            for i in range(len(block)):
                squared[i, start + i] = np.inf

        # argpartition puts the k smallest in front, unordered; order just those k.
        candidates = np.argpartition(squared, k - 1, axis=1)[:, :k]
        distances = np.take_along_axis(squared, candidates, axis=1)
        # lexsort's LAST key is primary, so this is "by distance, then by index".
        order = np.lexsort((candidates, distances), axis=1)
        winners = np.take_along_axis(candidates, order, axis=1)
        out.extend(tuple(int(index) for index in row) for row in winners)
    return out


def _locations_array(nodes) -> ndarray:
    return np.asarray([node.location for node in nodes], dtype=float)


def _require_dense_ids(items, id_attr: str, label: str) -> None:
    """
    The tables index by ID directly, with no indirection, because every construction site in this
    repo numbers its nodes 0..n-1. Fail loudly rather than silently mis-associating neighbors.
    """
    for position, item in enumerate(items):
        if getattr(item, id_attr) != position:
            raise ValueError(
                f"{label} IDs must be dense and 0-based for the neighbor tables to index by ID: "
                f"position {position} has {id_attr}={getattr(item, id_attr)}.")
#endregion


class FullSolution:
    # NOTE: annotations only -- no values. Every field is initialized per-instance in __init__.
    # These must never carry defaults: a class-level `vehicles: list = []` (or RouteSet()/defaultdict())
    # is created ONCE and shared by every FullSolution ever built, so in-place mutation
    # (all_routes.add, vehicles.append, depot_route_starts[d] += 1) leaks across instances.
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

    depot_route_starts: defaultdict[Depot, RouteSet]

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

        self.depot_route_starts = defaultdict[Depot, RouteSet](RouteSet)

        # Static geometry, built once by build_neighbor_tables(). Never maintained: customers and
        # depots do not move, so these survive every mutation and are shared by copies.
        self.neighbors: list[tuple[int, ...]] = []
        self.neighbor_rank: list[dict[int, int]] = []
        self.depot_neighbors: list[tuple[int, ...]] = []
        self.customer_depots: list[tuple[int, ...]] = []

        self.version = 0

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

        depot_route_starts = next(iter(routes_remaining)).depot_route_starts
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

        depots_activated = Route.depot_activation_delta_from_depot_num_usage_deltas(depot_usage_deltas, depot_route_starts)
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

        route.link_depot_uses(self.depot_route_starts)
        vehicle.append_route(route)
        self.all_routes.add(route)

    def add_route_to_vehicle_with_id(self, route: Route, vehicle_id: int):
        if vehicle_id >= len(self.vehicles) or vehicle_id < 0:
            raise ValueError("vehicle_id out of range")

        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        vehicle = self.vehicles[vehicle_id]
        route.link_depot_uses(self.depot_route_starts)
        vehicle.append_route(route)
        self.all_routes.add(route)

    def link_num_depot_uses_to_all(self):
        for route in self.all_routes:
            route.link_depot_uses(self.depot_route_starts)

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

    def solution_cost(self):
        return (self.cost_per_vehicle * self.vehicles_used() +
                self.cost_per_depot * self.depots_used() +
                self.unit_travel_cost * self.total_path_len() +
                self.unit_overload_penalty * self.total_overload() +
                self.vehicle_overload_penalty * self.num_overloaded_vehicles())

    def objective_terms(self) -> ObjectiveTermDelta:
        # Absolute totals in the same 5-field shape as ObjectiveTermDelta, so deltas can be
        # checked against ground truth by diffing two calls to this. Also the measurement
        # available to operators that set _evaluates_by_applying because they can't price a move
        # without performing it.
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

        # IMPORTANT to do it here so all objects see the copy's map instead of the original's.
        new_sln.link_num_depot_uses_to_all()

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