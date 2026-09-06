"""
Pricing for moves that change HOW MANY routes a vehicle's customers are divided into.

A split adds a depot stop part-way along a route and hands the tail to a new route. A combine
removes a depot stop and folds one route's customers into another. Neither changes the customer
set or its order. Only the segment boundaries move.

The two are not mirror images to price. A split always adds one depot stop at a known index, and
the new route inherits the old end depot. A combine depends on where the other route sits --
next, previous, or neither -- and the previous case is NOT the reverse of the next case: when the
route being combined into is empty, its own start and end arcs collapse rather than cancel.
"""
from ..basics import Num
from ..nodes import VIRTUAL_DEPOT, Depot
from ..records import NO_CHANGES, RawDeltaRecord
from ..routes import Route
from ..vehicle import Vehicle
from ..visits import CustomerVisit
from .route_moves import travel_delta_if_route_removed
from .visit_arcs import (end_travel_delta_if_route_removed, start_travel_delta_if_depot_swapped,
                         travel_delta_if_depot_stop_added_after_this)


#region Splitting one route into two
def cost_deltas_for_split_at(route: Route, split_index: int, refill_depot: Depot,
                             new_route: Route) -> RawDeltaRecord:

    # `new_route` is the empty, unassigned route the split will fill -- the SAME object
    # split_at receives. Splitting creates a route, and the raw record keys transitions
    # on route objects, so the created one has to exist before pricing can describe it.
    path = route.path

    # split_index is the index of the new (second-half) route's first customer -- same
    # convention as split_at and split2_load below -- so the customer this function prices
    # the depot-stop insertion after (the first half's last customer) is at split_index - 1.
    split_customer = route.get_visit_at(split_index - 1)
    # use isinstance instead of is_customer_visit for linter's sanity
    if not isinstance(split_customer, CustomerVisit):
        # First split src_route must end with customer
        return RawDeltaRecord()

    if not split_customer.next_visit.is_customer_visit:
        # Second split src_route must begin with customer
        # Note: next_visit is guaranteed to exist since split_customer is a customer visit
        return RawDeltaRecord()

    vehicle = route.vehicle
    if vehicle is None:
        return RawDeltaRecord() #  Cannot split unassigned routes


    ## Compute each relevant delta

    # Travel
    travel_delta = travel_delta_if_depot_stop_added_after_this(split_customer, refill_depot)

    # No new vehicles will be activated, so we skip vehicle activation delta

    # ONE WALK over the tail, for load and distance together. The load sum was always
    # here; the distance sum rides along, so the split gains a second O(tail) quantity
    # without a second pass. split2_travel is everything the new route will own except its
    # own entry arc: the arcs between the tail customers, plus the arc to the end depot
    # that route is handing over.
    split2_load: Num = 0
    split2_travel: Num = 0
    previous = None
    for customer in path[split_index:]:
        split2_load += customer.demand
        if previous is not None:
            split2_travel += previous.distance(customer)
        previous = customer
    assert previous is not None, "split2 is empty; the guards above should have caught it"
    split2_travel += route.end_depot.distance(previous)

    split1_load = route.current_load - split2_load

    # new_route starts at refill_depot once split_at links it after route, so it owns that
    # entry arc too. What route loses is exactly what new_route gains, minus the priced
    # join, so route's share is the remainder of the total.
    new_route_travel = refill_depot.distance(path[split_index]) + split2_travel
    self_travel = travel_delta - new_route_travel

    # Two entries, and only two. The route AFTER route keeps its start depot: new_route was
    # constructed carrying route's ORIGINAL end depot, and it lands between them, so the
    # successor still starts where it started. refill_depot re-points the FIRST half only.
    split2_count = route.num_customers - split_index
    # route keeps its start depot and its vehicle, so it appears only in the two numeric
    # maps. new_route is CREATED: it gains a depot and a vehicle, so it appears in all four.


    assert split_index > 0 # We NEVER price wasteful splits. Caller must catch this degenerate case.
    assert split2_count > 0

    raw = RawDeltaRecord(
        travel_changes={route: self_travel, new_route: new_route_travel},
        load_changes={route: (route.current_load, split1_load),
                            new_route: (new_route.current_load, split2_load)},
        customer_deltas={route: (route.num_customers, split_index),
                               new_route: (new_route.num_customers, split2_count)},
        start_depot_changes={new_route: (new_route.start_depot, refill_depot)},
        vehicle_changes={new_route: (new_route.vehicle, vehicle)})

    return raw
#endregion


#region Combining another route with this one
#region Travel-related computations
def travel_delta_for_combine_with(route: Route, other: Route) -> Num:
    # Note: new end depot comes from dest_route src_route. And we don't combine routes with themselves.
    if route is other:
        return 0

    if other == route.next_route:
        return travel_delta_for_combine_with_next(route)

    if other == route.prev_route:
        return travel_delta_for_combine_with_prev(route)

    # CAVEAT: if dest_route == route.prev_route and route is empty, then
    # prev_start->...->prev_last->start->last becomes prev_start->...->last. So must treat combines with previous src_route differently for travel computations.
    return travel_delta_for_combine_with_nonadjacent(route, other)

def travel_delta_for_combine_with_nonadjacent(route: Route, other: Route) -> Num:
    # Note: new end depot comes from dest_route src_route.
    assert route is not other, "Cannot combine with self"

    # Travel for dest_route's tail_distance was already accounted for.
    # This delta comes from a few changes:
    # 1) Other src_route: disconnected from its vehicle
    # 2) This src_route: end-1->end_depot becomes end-1->other_start+1
    # 3) Next src_route: start depot is swapped to dest_route.end_depot
    curr_visit_before_end = route.last_visit.prev_visit
    other_visit_after_start = other.first_visit.next_visit

    travel_delta = travel_delta_if_route_removed(other)

    old_distance = route.last_move_distance()
    new_distance = curr_visit_before_end.distance(other_visit_after_start)

    travel_delta += new_distance - old_distance

    next_route = route.next_route
    if isinstance(next_route, Route):
        travel_delta += start_travel_delta_if_depot_swapped(next_route.first_visit, other.end_depot)

    return travel_delta

def travel_delta_for_combine_with_next(route: Route) -> Num:
    other = route.next_route
    # Note: new end depot comes from dest_route src_route. And we don't combine inactive routes.
    assert other is not None, "Next src_route does not exist."
    assert route is not other, "Cannot combine with self"
    assert isinstance(other, Route), "Can only combine with Routes"

    # Combining with the immediate successor collapses the shared depot stop, which is TWO
    # visit objects at the same location: route's last_visit (end depot) and other's
    # first_visit (start depot). Both disappear, replaced by one direct edge from route's
    # last customer to other's first customer.
    # NOTE: travel_delta_if_visit_removed(route.last_visit) is NOT usable here -- it removes a
    # single node, and that node's next_visit is other.first_visit, sitting at the very
    # same location, so it always evaluates to exactly 0.
    # Both routes are guaranteed non-empty by the callers (CombineRoutes rejects empty
    # operands), so prev/next visits below are real customers.
    curr_visit_before_end = route.last_visit.prev_visit
    other_visit_after_start = other.first_visit.next_visit

    old_distance = route.last_move_distance() + other.first_move_distance()
    new_distance = curr_visit_before_end.distance(other_visit_after_start)

    return new_distance - old_distance

def travel_delta_for_combine_with_prev(route: Route) -> Num:
    other = route.prev_route
    # Note: new end depot comes from dest_route src_route.
    assert other is not None, "Previous src_route does not exist."
    assert route is not other, "Cannot combine with self"
    assert isinstance(other, Route), "Can only combine with Routes"

    # This one is by far the most complicated because of empty src_route interactions. Appending prev to end of route is a bit messy.

    # Neither empty:
    # Before: other_start->other_start+1->...->other_end->start+1->...->end-1->end->next_start+1
    # After: other_start->start+1->...->end-1->other_start+1->...->other_end->next_start+1

    # Other empty only:
    # Before: other_start->other_end->start+1->...->end-1->end->next_start+1
    # After:  other_start->start+1->...->end-1->other_start+1=other_end->next_start+1
    # COMPARE TO Neither empty: Just lose ->...->other_end - the tail of dest_route. But that was already counted, so no logical change!

    # Self empty (regardless of dest_route empty)
    # Before: other_start->other_start+1->...->other_end->end->next_start+1
    # After:  other_start->other_start+1->...->other_end->next_start+1 -> Equal to replacing route end depot with other_end!

    if route.is_empty:
        # Then combine_with_prev just removes this route, in effect: other_end->end pops out.
        return travel_delta_if_route_removed(route)

    # If route is not empty, Break it down:
    # 1) Route starts: Lose other_start->other_start+1 and other_end->start+1, gain other_start->start+1
    # 2) Path combine: Lose end-1->end, gain end-1->other_start+1
    # 3) Next src_route changed start: Lost end->next_start+1, gain other_end->next_start+1 (next changes start depot)
    curr_visit_before_end = route.last_visit.prev_visit
    curr_visit_after_start = route.first_visit.next_visit
    other_visit_after_start = other.first_visit.next_visit

    # 1) Route starts
    old_distance = other.first_move_distance() + route.first_move_distance()
    new_distance = other.first_visit.distance(curr_visit_after_start)  # Can't query start depot replace: if this src_route is empty you'll count new_start->end, which isn't used.
    travel_delta = new_distance - old_distance

    # 2) Path combine
    old_distance = route.last_move_distance()
    new_distance = curr_visit_before_end.distance(other_visit_after_start)

    travel_delta += new_distance - old_distance

    # 3) Next src_route changed start
    next_route = route.next_route
    if isinstance(next_route, Route):
        travel_delta += start_travel_delta_if_depot_swapped(next_route.first_visit, other.end_depot)

    return travel_delta
#endregion

#region Full delta computations
def cost_deltas_for_combine_with(route: Route, other: Route) -> RawDeltaRecord:
    if route is other:
        raise ValueError("Cannot combine a src_route with itself")

    # Call assumption: route and other are different and nonempty
    has_customers = route.has_customers
    other_has_customers = other.has_customers
    assert route is not other and has_customers and other_has_customers, "Cannot combine a src_route with itself"

    travel_delta = travel_delta_for_combine_with(route, other)

    # OTHER ENDS AT ZERO DISTANCE: combine_with empties its path and unlinks it, and an
    # unassigned empty route measures zero. Its cached total is the exact amount to remove,
    # so this side needs no walk.
    other_travel = -other.current_travel

    # UP TO THREE ROUTES MOVE, and only the first is obvious.
    #
    #   route        absorbs other's customers, so load and count rise. Its START DEPOT also
    #               moves when other is its PREDECESSOR: the chain is other -> route, so
    #               once other is gone route takes other's slot and therefore other's start
    #               depot. Claiming it unchanged is wrong, and the raw-record oracle caught
    #               exactly that on the adjacency="prev" cases.
    #   other       is emptied AND unlinked in the one call: load and count to zero, start
    #               depot to a VirtualDepot, vehicle to None.
    #   next route  inherits other's end depot, because combine_with gives route that end
    #               depot and a route's end depot IS the next route's start depot. Skipped
    #               when the next route IS other, which is about to disappear anyway.
    #   other's own successor inherits other's START depot, because unlinking other closes
    #               the gap in ITS chain. Only in the NON-ADJACENT case: when other is
    #               route's successor the two effects coincide (route ends up carrying other's
    #               end depot, which is what that successor already started at), and when
    #               other is route's predecessor the successor IS route, handled above.

    start_depot = route.start_depot
    other_start_depot = other.start_depot
    used_start_depot = route.used_start_depot
    other_used_start_depot = other.used_start_depot
    self_start = other_used_start_depot if route.prev_route is other else used_start_depot

    current_load = route.current_load
    loads: dict[Route, tuple[Num, Num]] = {
        route: (current_load, current_load + other.current_load),
        other: (other.current_load, 0)}
    counts: dict[Route, tuple[int, int]] = {
        route: (route.num_customers, route.num_customers + other.num_customers),
        other: (other.num_customers, 0)}
    start_depots: dict[Route, tuple[Depot, Depot]] = {}

    other_active = other.is_active
    split_legal = route.is_active or other_active
    assert split_legal, "Cannot price combine solely between inactive routes"

    if other_active:
        # Uncount other's start depot - it becomes empty and unassigned
        start_depots[other] = (other_used_start_depot, VIRTUAL_DEPOT)

    if self_start is not start_depot and route.vehicle is not None:
        start_depots[route] = (used_start_depot, self_start)

    vehicles: dict[Route, tuple[Vehicle | None, Vehicle | None]] = {
        other: (other.vehicle, None)}

    next_route = route.next_route
    if (isinstance(next_route, Route) and next_route is not other
            and next_route.start_depot != # type: ignore - Linter is an idiot. Gated by isinstance -_-
            other.end_depot):
        assert isinstance(next_route, Route)
        next_final_use_depot = other.end_depot if next_route.is_active else VIRTUAL_DEPOT
        start_depots[next_route] = (next_route.used_start_depot, next_final_use_depot)

    other_successor = other.next_route
    if (isinstance(other_successor, Route) and other_successor is not route
            and other is not next_route
            and other_successor.start_depot != # type: ignore - Linter is an idiot. Gated by isinstance -_-
            other_start_depot):
        assert isinstance(other_successor, Route)
        other_successor_final_use_depot = other_start_depot if other_successor.is_active else VIRTUAL_DEPOT
        start_depots[other_successor] = (other_successor.used_start_depot, other_successor_final_use_depot)

    # The entry-arc changes that belong to neighbours rather than to route or other. Both
    # are start-depot swaps, and both are already inside the priced total. Whatever the
    # total does not account for on other routes is route's, which is right by construction:
    # route absorbs other's whole path plus the join arc.
    travels: dict[Route, Num] = {}
    if other_travel:
        travels[other] = other_travel

    if other is not next_route and other is not route.prev_route:
        # Non-adjacent: other's own successor closes the gap other leaves behind.
        successor_travel = end_travel_delta_if_route_removed(other.last_visit)
        if successor_travel and isinstance(other_successor, Route):
            travels[other_successor] = travels.get(other_successor, 0) + successor_travel

    if isinstance(next_route, Route) and other is not next_route:
        swap_travel = start_travel_delta_if_depot_swapped(next_route.first_visit, 
            other.end_depot)
        if swap_travel:
            travels[next_route] = travels.get(next_route, 0) + swap_travel

    self_travel = travel_delta - sum(travels.values())
    if self_travel:
        travels[route] = travels.get(route, 0) + self_travel
    travels = {route: delta for route, delta in travels.items() if delta}

    raw = RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                         load_changes=loads,
                         customer_deltas=counts,
                         start_depot_changes=start_depots,
                         vehicle_changes=vehicles)

    return raw
#endregion
#endregion
