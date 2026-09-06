"""
Arc arithmetic on route visits: what a visit's arcs cost now, and what they would cost after a
change. These are the primitives every other module in this package sums.

A visit reads only its own two arcs -- the one into it and the one out of it -- so each function
here does a fixed amount of work whatever the route length. That is where O(1) move pricing starts.

ONE VISIT DELTA IS NOT HERE. RouteVisit.travel_delta_if_inserting_customer_before_this stays a
method, because FirstRouteVisit and LastRouteVisit override it. Virtual dispatch costs less than
the three-branch isinstance chain a free function would need, and it sits on the insertion path.
"""
from ..basics import Num
from ..visits import (CustomerLike, CustomerVisit, DepotLike, FirstRouteVisit, LastRouteVisit,
                      RouteVisit)


#region RouteVisit
def travel_delta_if_visit_removed(visit: RouteVisit) -> Num:
    assert visit.prev_visit is not None, "Cannot remove nodes at start or end of vehicle or unassigned src_route path."
    # Change to current-src_route travel distance if removing this from src_route
    old_length = visit.distance_surrounding
    new_length = visit.distance_if_removed
    return new_length - old_length
#endregion


#region CustomerVisit
def travel_delta_if_customer_replaced(visit: CustomerVisit, new_customer: CustomerLike) -> Num:
    old_length = visit.distance_surrounding
    new_length = visit.prev_visit.distance(new_customer) + new_customer.distance(visit.next_visit)
    return new_length - old_length

def travel_deltas_if_swapped_with(visit: CustomerVisit, other: CustomerVisit) -> tuple[Num, Num]:
    """(this visit's route share, the other visit's route share) of swapping the two.

    Adjacency is only possible WITHIN one route, so the adjacent branch puts the whole delta
    on this side and zero on the other. The non-adjacent branch is already two independent
    replacements, one per route -- travel_delta_if_swapped_with just adds them.
    """
    if not visit.is_adjacent_with(other):
        return (travel_delta_if_customer_replaced(visit, other),
                travel_delta_if_customer_replaced(other, visit))
    return travel_delta_if_swapped_with(visit, other), 0

def travel_delta_if_swapped_with(visit: CustomerVisit, other: CustomerVisit) -> Num:
    # Change to current-src_route travel distance if swapping customers with another CustomerVisit
    if not visit.is_adjacent_with(other):
        return travel_delta_if_customer_replaced(visit, other) + travel_delta_if_customer_replaced(other, visit)

    if other == visit.next_visit:
        prev = visit.prev_visit
        nxt = other.next_visit

        old_distance = visit.distance_in + other.distance_out
        new_distance = prev.distance(other) + visit.distance(nxt)

    else: # dest_route == visit.prev_visit
        prev = other.prev_visit
        nxt = visit.next_visit

        old_distance = other.distance_in + visit.distance_out
        new_distance = prev.distance(visit) + other.distance(nxt)

    return new_distance - old_distance

# Route splits
def travel_delta_if_depot_stop_added_after_this(visit: CustomerVisit, depot_stop: DepotLike) -> Num:
    next_visit = visit.next_visit
    # ASSUME: this is part of a general split delta conversation. Verification that next_visit is a customer
    # has already been done. (We don't want to re-verify this several times.)

    # Add path visit->depot->next_visit instead of visit->next_visit
    old_distance = visit.distance_out
    new_distance = visit.distance(depot_stop) + depot_stop.distance(next_visit)
    return new_distance - old_distance

def current_route_load_delta_if_swapped_with(visit: CustomerVisit, other: CustomerVisit) -> Num:
    # Can reduce numerical error compared to "always subtract" if in same src_route:
    # (a-b) + (b-a) may evaluate to a small nonzero value due to numerical errors
    return 0 if visit.route == other.route else other.demand - visit.demand
#endregion


#region FirstRouteVisit
def start_travel_delta_if_depot_swapped(visit: FirstRouteVisit, new_node: DepotLike) -> Num:
    # Change to src_route travel distance if replacing the node here with a new one
    old_length = visit.distance_out
    new_length = new_node.distance(visit.next_visit)
    return new_length - old_length

def start_travel_delta_if_route_removed(visit: FirstRouteVisit):
    if visit.route_is_trivial or visit.source_depot.is_virtual_depot:
        return 0

    # If src_route is removed: connection first->next no longer occurs.
    # LastRouteVisit can handle the delta from any change in start depot for the next src_route
    return -visit.distance(visit.next_visit)
#endregion


#region LastRouteVisit
def get_replacement_travel_deltas(visit: LastRouteVisit, new_depot: DepotLike) -> tuple[Num, Num]:
    """(this route's share, the next route's share) of replacing this end depot.

    Two routes move, and each half is already route-local: this route's last arc changes, and
    the next route's first arc changes because a route's end depot IS the next route's start
    depot. The sum is what get_replacement_travel_delta returns.
    """
    own_delta = visit.prev_visit.distance(new_depot) - visit.distance_in

    next_first_visit = visit.next_visit
    next_delta = (start_travel_delta_if_depot_swapped(next_first_visit, new_depot)
                  if next_first_visit is not None else 0)

    return own_delta, next_delta

def get_replacement_travel_delta(visit: LastRouteVisit, new_depot: DepotLike):
    # Travel delta if replacing own end depot in place:
    # 1) Relink depot for this route's last move
    # 2) Relink depot for next route's first move
    own_delta, next_delta = get_replacement_travel_deltas(visit, new_depot)
    return own_delta + next_delta

def end_travel_delta_if_route_removed(visit: LastRouteVisit) -> Num:
    # If src_route is removed: the next src_route's start depot will change
    # FirstRouteVisit handles the disconnect from start->next_visit

    # If src_route is a cycle or there is no next src_route, start depot doesn't change
    next_visit = visit.next_visit
    if next_visit is None or visit.depot_is(visit.route.start_depot):
        return 0

    # Otherwise: report travel distance if the next src_route swaps start depots
    return start_travel_delta_if_depot_swapped(next_visit, visit.route.start_depot)
#endregion
