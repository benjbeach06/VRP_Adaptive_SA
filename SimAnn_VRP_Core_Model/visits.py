"""
Route visits: the linked-list nodes a Route is built out of.

A visit MIRRORS the fields of its underlying node rather than pointing at it, so pricing reads a
location without a second dereference. RouteVisit is the abstract base; the three concrete kinds
are the two depot ends of a route and the CustomerVisits between them.

The union aliases near the bottom -- NodeLike, CustomerLike, DepotLike, DepotVisit -- are the
vocabulary the rest of the model annotates against.

IMPORT CYCLE, AND WHY THE LAST LINE OF THIS FILE IS AN IMPORT: LastRouteVisit isinstance-tests
Route and LastRoute at runtime, to tell the three successor states apart; Route in turn builds and
isinstance-tests the classes below. The two modules genuinely need each other. The package
__init__ imports THIS module first, which pins the order and makes that bottom import resolve.
Read the note in __init__.py before reordering anything there.
"""
from abc import ABC
from enum import Enum, auto
from typing import TYPE_CHECKING, List, Sequence

from .basics import Num, dist
from .nodes import VIRTUAL_DEPOT, Customer, Depot, Node

if TYPE_CHECKING:
    from .routes import FirstRoute, LastRoute, Route

#region Route visit definitions
class RouteVisit(ABC):
    __slots__ = ("location", "route", "prev_visit", "next_visit")
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
    location: tuple[Num, Num]

    def __init__(self, node: Node):
        # Subclasses overwrite route (and link the visits) after calling super().__init__().
        self.location = node.location
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

    def distance(self, other: NodeLike | None) -> Num:
        if other is None: return 0 # Trick to help with type safety: distance with None is 0 (e.g. distance with prev visit but prev visit is None)
        return dist(self.location, other.location)

    @property
    def travel_delta_if_removed(self) -> Num:
        assert self.prev_visit is not None, "Cannot remove nodes at start or end of vehicle or unassigned src_route path."
        # Change to current-src_route travel distance if removing this from src_route
        old_length = self.distance_surrounding
        new_length = self.distance_if_removed
        return new_length - old_length

    @property
    def is_first_route_visit(self) -> bool:
        return isinstance(self, FirstRouteVisit)

    @property
    def is_last_route_visit(self) -> bool:
        return isinstance(self, LastRouteVisit)

    @property
    def is_customer_visit(self) -> bool:
        return isinstance(self, CustomerVisit)

    def is_adjacent_with(self, other: RouteVisit) -> bool:
        return other == self.prev_visit or other == self.next_visit

    def travel_delta_if_inserting_customer_before_this(self, new_customer: CustomerLike) -> Num:
        # Change to src_route travel distance if inserting new_customer before this
        old_length = self.distance_in
        new_length = new_customer.distance(self.prev_visit) + self.distance(new_customer)
        return new_length - old_length

    #endregion

    #region Object operations

    def __copy__(self):
        cls = self.__class__

        # We bypass constructor since inherited classes may have different constructor arguments
        new_node = cls.__new__(cls)

        # We overwrite _copy_data when we need more data, leaving __copy__ alone
        new_node._copy_data(self)

        return new_node

    def _copy_data(self, source: RouteVisit):
        # We do not copy routes and visits here: part of larger copy, where routes and prev/next visits are new objects.
        self.location = source.location

    #endregion


class CustomerVisit(RouteVisit):
    __slots__ = ("cID", "source_customer", "demand")
    prev_visit: RouteVisit # Prev and next visits are guaranteed to exist for customers linked to a src_route.
    next_visit: RouteVisit # CustomersVisits are never unlinked more than temporarily to move between routes.

    demand: Num
    cID: int
    source_customer: Customer

    def __init__(self, customer: Customer):
        super().__init__(node=customer)
        self.source_customer = customer
        self.cID = customer.cID
        self.demand = customer.demand

    #region Current state
    def is_last_customer_in_route(self) -> bool:
        return self.prev_visit.is_first_route_visit and self.next_visit.is_last_route_visit
    #endregion

    #region Delta computations

    def travel_delta_if_customer_replaced(self, new_customer: CustomerLike) -> Num:
        old_length = self.distance_surrounding
        new_length = self.prev_visit.distance(new_customer) + new_customer.distance(self.next_visit)
        return new_length - old_length

    def travel_deltas_if_swapped_with(self, other: CustomerVisit) -> tuple[Num, Num]:
        """(this visit's route share, the other visit's route share) of swapping the two.

        Adjacency is only possible WITHIN one route, so the adjacent branch puts the whole delta
        on this side and zero on the other. The non-adjacent branch is already two independent
        replacements, one per route -- travel_delta_if_swapped_with just adds them.
        """
        if not self.is_adjacent_with(other):
            return (self.travel_delta_if_customer_replaced(other),
                    other.travel_delta_if_customer_replaced(self))
        return self.travel_delta_if_swapped_with(other), 0

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
    def travel_delta_if_depot_stop_added_after_this(self, depot_stop: DepotLike) -> Num:
        next_visit = self.next_visit
        # ASSUME: this is part of a general split delta conversation. Verification that next_visit is a customer
        # has already been done. (We don't want to re-verify this several times.)

        # Add path self->depot->next_visit instead of self->next_visit
        old_distance = self.distance_out
        new_distance = self.distance(depot_stop) + depot_stop.distance(next_visit)
        return new_distance - old_distance

    # For src_route splits: new depot will activate, no need to calculate depot usage changes here. Vehicles won't activate/deactivate.
    # New overloads need to be computed at the src_route level, as full demand lists before and after must be summed


    def current_route_load_delta_if_swapped_with(self, other: CustomerVisit) -> Num:
        # Can reduce numerical error compared to "always subtract" if in same src_route:
        # (a-b) + (b-a) may evaluate to a small nonzero value due to numerical errors
        return 0 if self.route == other.route else other.demand - self.demand

    #endregion

    #region Object operations

    def replace_customer(self, new_customer: Customer):
        # Reason to copy values instead of just mirroring a reference: cost comps will happen much more frequently than node replacements.
        # Thus, copying values ("is a" node) removes a layer of indirection

        # 1. Update fields for this visit to match the new customer
        self.location = new_customer.location
        self.cID = new_customer.cID
        self.demand = new_customer.demand

        # 2. Update the source customer for this visit
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
            self.replace_customer(other_customer)
            other.replace_customer(curr_customer)

    def unlink_from_route(self):
        # Only unlinks src_route and uncounts src_route from vehicle and updates depot accounting.
        # Does not process loading changes or vehicle accounting, since some of those operations
        # must be performed before the src_route's path is mutated.
        route = self.route
        if route is None:
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

    def _copy_data(self, source: RouteVisit):
        assert isinstance(source, CustomerVisit)

        # Copy only customer data fields and source_depot
        self.source_customer = source.source_customer

        self.cID = source.cID
        self.demand = source.demand

        # Note: This calls both Customer and RouteVisit versions of _copy_data
        super()._copy_data(source)

    def __str__(self):
        return str(self.source_customer)

    def __repr__(self):
        return str(self)

    #endregion


class FirstRouteVisit(RouteVisit):
    __slots__ = "dID", "supply_limit", "vehicle_count", "source_depot"
    # NOTE: Core operations can only focus on changing where a src_route ends, not starts.
    # BUT changing where one src_route ends for a vehicle necessarily changes where the next starts
    prev_visit: LastRouteVisit | None # Prev visit either None or part of previous src_route
    next_visit: CustomerVisit | LastRouteVisit # Next visit never None

    source_depot: Depot
    dID: int
    supply_limit: Num
    vehicle_count: int

    def __init__(self, depot: Depot, route: Route):
        # Restrict to just fields in base Depot class to prevent possible inheritance collisions
        super().__init__(node=depot)
        self.source_depot = depot
        self.dID = depot.dID
        self.supply_limit = depot.supply_limit
        self.vehicle_count = depot.vehicle_count

        self.route: Route = route

        # When this is initializing: the src_route will not yet be assigned to a vehicle, so the depot is not counted.
        # This is a part of ensuring that unused routes do not contribute to the solution

    #region Current state
    def distance(self, other: NodeLike | None):
        if self.source_depot is VIRTUAL_DEPOT:
            return 0
        return super().distance(other)

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
        return not self.source_depot is VIRTUAL_DEPOT

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
    def start_travel_delta_if_depot_swapped(self, new_node: DepotLike) -> Num:
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

    def travel_delta_if_inserting_customer_before_this(self, new_customer: CustomerLike):
        # Change to src_route travel distance if inserting new_customer before this
        raise ValueError("Cannot insert a node before a first src_route visit.")

    #endregion

    #region Object operations

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

        # 2. Update fields for this visit to match the new depot
        self.dID = new_depot.dID
        self.supply_limit = new_depot.supply_limit
        self.vehicle_count = new_depot.vehicle_count
        self.location = new_depot.location

        # 3. Update the source depot for this visit
        self.source_depot = new_depot

    def _copy_data(self, source: RouteVisit):
        assert isinstance(source, FirstRouteVisit)

        # Copy only depot data fields (via super()) and source_depot
        self.source_depot = source.source_depot

        self.dID = source.dID
        self.supply_limit = source.supply_limit
        self.vehicle_count = source.vehicle_count

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


class LastRouteVisit(RouteVisit):
    __slots__ = "source_depot", "dID", "supply_limit", "vehicle_count"
    prev_visit: CustomerVisit | FirstRouteVisit # prev visit is never None

    route: Route

    # NOTE: Core operations can only focus on changing where a src_route ends, not starts.
    # BUT changing where one src_route ends for a vehicle necessarily changes where the next starts
    def __init__(self, depot: Depot, route: Route):
        # Restrict to just fields in base Depot class to prevent possible inheritance collisions
        self.source_depot = depot

        self.dID = depot.dID
        self.supply_limit = depot.supply_limit
        self.vehicle_count = depot.vehicle_count

        super().__init__(depot)

        self.route = route


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

    def get_replacement_travel_deltas(self, new_depot: DepotLike) -> tuple[Num, Num]:
        """(this route's share, the next route's share) of replacing this end depot.

        Two routes move, and each half is already route-local: this route's last arc changes, and
        the next route's first arc changes because a route's end depot IS the next route's start
        depot. The sum is what get_replacement_travel_delta returns.
        """
        own_delta = self.prev_visit.distance(new_depot) - self.distance_in

        next_first_visit = self.next_visit
        next_delta = (next_first_visit.start_travel_delta_if_depot_swapped(new_depot)
                      if next_first_visit is not None else 0)

        return own_delta, next_delta

    def get_replacement_travel_delta(self, new_depot: DepotLike):
        # Travel delta if replacing own end depot in place:
        # 1) Relink depot for this route's last move
        # 2) Relink depot for next route's first move
        own_delta, next_delta = self.get_replacement_travel_deltas(new_depot)
        return own_delta + next_delta

    def travel_delta_if_inserting_customer_before_this(self, new_customer: CustomerLike):
        # Change to src_route travel distance if inserting new_customer before this
        old_length = self.distance_in
        new_length = self.prev_visit.distance(new_customer) + new_customer.distance(self)
        return new_length - old_length

    def end_travel_delta_if_route_removed(self) -> Num:
        # If src_route is removed: the next src_route's start depot will change
        # FirstRouteVisit handles the disconnect from start->next_visit

        # If src_route is a cycle or there is no next src_route, start depot doesn't change
        next_visit = self.next_visit
        if next_visit is None or self.depot_is(self.route.start_depot):
            return 0

        # Otherwise: report travel distance if the next src_route swaps start depots
        return next_visit.start_travel_delta_if_depot_swapped(self.route.start_depot)

    #endregion

    #region Object operations

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
        self.dID = new_depot.dID
        self.supply_limit = new_depot.supply_limit
        self.vehicle_count = new_depot.vehicle_count
        self.location = new_depot.location

        # 3. Update the source depot for this visit
        self.source_depot = new_depot

    def _copy_data(self, source: RouteVisit):
        assert isinstance(source, LastRouteVisit)

        # Copy only depot data fields and source_depot
        self.source_depot = source.source_depot

        self.dID = source.dID
        self.supply_limit = source.supply_limit
        self.vehicle_count = source.vehicle_count

        # Note: This calls both Customer and RouteVisit versions of _copy_data
        super()._copy_data(source)


    def __str__(self):
        return str(self.source_depot)

    def __repr__(self):
        return str(self)

NodeLike = Node | RouteVisit
CustomerLike = Customer | CustomerVisit
DepotLike = Depot | FirstRouteVisit | LastRouteVisit
DepotVisit = FirstRouteVisit | LastRouteVisit

    #endregion
#endregion

# UNUSED - DEPRECATE
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


# UNUSED - DEPRECATE
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
        curr_visit.replace_customer(next_visit.source_customer)
        curr_visit = next_visit

    curr_visit.replace_customer(start_customer)



# Deferred to the very bottom, deliberately. See the module docstring: Route and LastRoute are
# needed at RUNTIME by the isinstance tests above, and both are defined one module up the chain.
# Binding them here as ordinary module globals keeps those tests a plain global lookup on the
# pricing path -- no per-call import, and no module-attribute indirection.
from .routes import LastRoute, Route  # noqa: E402
