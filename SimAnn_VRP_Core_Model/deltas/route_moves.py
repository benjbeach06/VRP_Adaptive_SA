"""
Pricing for moves where the ROUTE is the object that moves. Its customers do not change, and
neither does their order. The route is unlinked, relinked, or handed a different depot.

Four facts about the vehicle chain drive every function here:

    - A route's start depot IS its predecessor's end depot. So removing a route, or inserting one,
      changes where the SUCCESSOR starts, and that arc has to be paid for too.
    - An unassigned route starts at a VirtualDepot, and an arc from one costs nothing.
    - A trivial route has no customers, so it has no interior travel to charge.
    - The tail of the chain is the LastRoute sentinel. It owns no first visit, so there is no
      successor arc to charge against it.

cost_deltas_if_swapped_with_next_route is the ADJACENT case of cost_deltas_if_inserted_before,
which asserts non-adjacency and refuses to price it. The two are a pair; keep them together.
"""
from typing import Mapping

from ..basics import Num
from ..nodes import VIRTUAL_DEPOT, Depot
from ..records import NO_CHANGES, RawDeltaRecord
from ..routes import LastRoute, Route
from ..vehicle import Vehicle
from .visit_arcs import (end_travel_delta_if_route_removed, get_replacement_travel_delta,
                         get_replacement_travel_deltas, start_travel_delta_if_depot_swapped,
                         start_travel_delta_if_route_removed)


#region Changing end depot
def travel_delta_if_end_depot_changes(route: Route, new_end_depot: Depot) -> Num:
    # Includes relinking the depot for the last move of this route and the first move of any next route
    return get_replacement_travel_delta(route.last_visit, new_end_depot)

def cost_deltas_if_end_depot_changes(route: Route, new_end_depot: Depot) -> RawDeltaRecord:
    # Two routes move and each half is route-local: this route's last arc, and the next
    # route's first arc (a route's end depot IS the next route's start depot).
    own_travel, next_travel = get_replacement_travel_deltas(route.last_visit, new_end_depot)

    # THIS ROUTE DOES NOT CHANGE. A route's end depot IS the next route's start depot, so
    # set_end_depot -> last_visit.replace_depot moves the NEXT route's start_depot and
    # leaves this one alone. Measured, not inferred. End-depot use is not tracked until
    # step 4, so this route's own entry would be unchanged and would drop anyway.
    start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = NO_CHANGES
    next_route = route.next_route

    # isinstance, not `is not None`: the tail route's next_route is the LastRoute sentinel.
    if isinstance(next_route, Route) and next_route.start_depot != new_end_depot and len(next_route.path) > 0:
        # Next route start depot change is counted if it has customers and the depot changes (Assignment guaranteed)
        start_depots = {next_route : (next_route.start_depot, new_end_depot)}

    travels: dict[Route, Num] | Mapping = {route: own_travel} if own_travel else {}
    if next_travel and isinstance(next_route, Route):
        assert isinstance(travels, dict)
        travels[next_route] = next_travel

    return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                          start_depot_changes=start_depots)
#endregion


#region Route operations: removing, inserting, and appending a route to or from a vehicle
#region Travel-related computations
def travel_delta_if_route_removed(route: Route) -> Num:
    if route.is_trivial or not route.is_assigned:
        return 0

    # Travel deltas are: from removing the first move, and from changing the start depot of the next src_route
    return start_travel_delta_if_route_removed(route.first_visit) + end_travel_delta_if_route_removed(route.last_visit)

def travel_delta_if_inserted_before(route: Route, next_route: Route | LastRoute) -> Num:
    # REQUIRE adjacent case to be gatekept by parent, calling full delta-comp fcn for swapping adjacent routes.
    assert not route.is_adjacent_with(next_route), "Wrong function for adjacent routes."
    if route.is_empty or next_route is route:
        # We don't insert or shift around empty routes. Just remove, dispose, or combine.
        # If moving to current location no change!
        return 0

    # Nonadjacent case only! Cleanly remove from current location and insert at new.

    # Travel deltas are from:
    # 1) Changing the start depot of route's OLD successor, now that route has vacated its old spot
    # 2) Replacing route's own entry edge: old_start->first_customer becomes new_start->first_customer
    # 3) Changing the start depot of the next src_route (route's new successor), or 0 if appending (LastRoute)
    # NOTE: Internal travel deltas for the src_route are always counted in the global objective, and
    # are not explicitly tracked per-src_route.
    # IMPORTANT: item 1 uses only end_travel_delta_if_route_removed(last_visit), NOT the
    # full travel_delta_if_route_removed(route) -- that also includes
    # start_travel_delta_if_route_removed(first_visit)
    # (route's own entry edge disappearing), which would double-count against item 2 below, which
    # already nets out the change to route's own entry edge (old_start -> new_start).
    new_start_depot = next_route.start_depot
    end_depot = route.end_depot

    remove_delta = end_travel_delta_if_route_removed(route.last_visit)
    start_delta = start_travel_delta_if_depot_swapped(route.first_visit, new_start_depot)
    end_delta = 0 if isinstance(next_route, LastRoute) else start_travel_delta_if_depot_swapped(next_route.first_visit, end_depot)

    return remove_delta + start_delta + end_delta

def travel_delta_if_appended_to(route: Route, vehicle: Vehicle):
    return travel_delta_if_inserted_before(route, vehicle.last_route)
#endregion

#region Full delta computations
def cost_deltas_if_removed(route: Route):
    # Also doubles as "travel delta if disposed"
    # Returns: travel_delta, depot_used_delta, vehicle_used_delta, load_delta
    if route.vehicle is None:
        return RawDeltaRecord() # Cannot remove a src_route if it's unassigned!

    start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}

    if route.is_active:
        # If route is active, start_depot becomes unused
        start_depots[route] = (route.start_depot, VIRTUAL_DEPOT)

    vehicles: dict[Route, tuple[Vehicle, Vehicle|None]] = {route: (route.vehicle, None)}

    next_route = route.next_route
    # isinstance, not `is not None`: the tail route's next_route is the LastRoute sentinel,
    # which has no start depot to inherit anything.
    if isinstance(next_route, Route) and next_route.start_depot != route.start_depot and len(next_route.path) > 0:
        assert isinstance(start_depots, dict) # Make linter glad
        # Next used start depot changes if next route has customers and its start depot changes (Assignment guaranteed)
        start_depots[next_route] = (next_route.start_depot, route.start_depot)

    if not start_depots:
        start_depots = NO_CHANGES

    if route.is_trivial:
        return RawDeltaRecord(start_depot_changes=start_depots, vehicle_changes=vehicles) # Delta = 0, but the structure still moves.

    # Two halves, already route-local. The first is this route losing its own entry arc --
    # an unassigned route starts at a VirtualDepot, and FirstRouteVisit.distance returns 0
    # from one, so the route's own total drops by exactly that arc. The second is the next
    # route inheriting this one's start depot.
    own_travel = start_travel_delta_if_route_removed(route.first_visit)
    next_travel = end_travel_delta_if_route_removed(route.last_visit)

    travels: dict[Route, Num] | Mapping = {route: own_travel} if own_travel else {}
    if next_travel and isinstance(next_route, Route):
        assert isinstance(travels, dict)
        travels[next_route] = next_travel

    return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                          start_depot_changes=start_depots, vehicle_changes=vehicles)

def cost_deltas_if_inserted_before(route: Route, other: Route|LastRoute) -> RawDeltaRecord:
    vehicle = other.vehicle
    assert vehicle is not None, "Cannot insert before unassigned route"

    # If currently assigned to a vehicle: this DOES NOT include deltas for removal stage
    if route.is_adjacent_with(other):
        # route1 is earlier of route or dest_route, route2 = route1.next_route is the later.
        # Since the two are adjacent... both exist.
        route1 = route if other is route.next_route else other
        assert isinstance(route1, Route)
        return cost_deltas_if_swapped_with_next_route(route1)

    # Returns: travel_delta, depot_used_delta, vehicle_used_delta, load_delta
    if route.is_empty:
        return RawDeltaRecord() # Delta = 0. (We don't allow inserting empty stuff - so return 0.)

    # Three routes move their entry arc, and travel_delta_if_inserted_before already
    # computes the three pieces separately before adding them. Keep them apart.
    insert_start_depot = other.start_depot
    insert_end_depot = route.end_depot
    old_successor_travel = end_travel_delta_if_route_removed(route.last_visit)
    own_travel = start_travel_delta_if_depot_swapped(route.first_visit, insert_start_depot)
    other_travel = (0 if isinstance(other, LastRoute)
                    else start_travel_delta_if_depot_swapped(other.first_visit, insert_end_depot))

    # Up to three routes move their start depot, and NONE of them changes load or customer
    # count -- relinking carries a route's customers with it. The adjacent case never gets
    # here (it returned above), so route's old successor is never `other`.
    #   route          -- starts where `other` used to start; joins `vehicle`
    #   old successor -- inherits route's old start depot, now that route has vacated
    #   other         -- starts at route's end depot, now that route sits in front of it
    # LastRoute successors get no entry: they are sentinels, not routes.
    has_customers = len(route.path) > 0

    start_depots: dict[Route, tuple[Depot, Depot]] | Mapping = {}

    self_start = route.used_start_depot
    self_end = route.end_depot
    other_start = other.start_depot
    if has_customers and self_start != other_start:
        # Start depot changes if has customers and changes start depots. (Assignment guaranteed)
        start_depots[route] = (self_start, other_start)

    old_successor = route.next_route
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

    self_vehicle = route.vehicle
    vehicle_changes = {route: (self_vehicle, vehicle)} if self_vehicle != vehicle else NO_CHANGES

    travels: dict[Route, Num] = {}
    if own_travel:
        travels[route] = own_travel
    if old_successor_travel and isinstance(old_successor, Route):
        travels[old_successor] = travels.get(old_successor, 0) + old_successor_travel
    if other_travel and isinstance(other, Route):
        travels[other] = travels.get(other, 0) + other_travel

    return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                          start_depot_changes=start_depots,
                          vehicle_changes=vehicle_changes)

def cost_deltas_if_appended_to(route: Route, vehicle: Vehicle) -> RawDeltaRecord:
    # Returns: travel_delta, depot_used_delta, vehicle_used_delta
    return cost_deltas_if_inserted_before(route, vehicle.last_route)
#endregion
#endregion


#region Swapping a route with its successor -- the adjacent case of inserted_before
def cost_deltas_if_swapped_with_next_route(route: Route) -> RawDeltaRecord:
    # These deltas come exclusively from changes in the start_depot of each src_route.
    # So? We simply ask the routes for the travel deltas when swapping their start depots.
    # This includes the src_route after next if it exists.
    # The routes affected are: this src_route, the next src_route, and the src_route after next.

    route1 = route
    route2 = route.next_route

    # isinstance, not `is not None`: next_route is None only when unassigned -- once
    # assigned it is a real Route OR the vehicle's LastRoute sentinel, and LastRoute has
    # no is_empty/end_depot/first_visit. A `is not None` check lets the sentinel through
    # and raises AttributeError two lines down. (route3 below already gets this right.)
    if not isinstance(route2, Route):
        if route2 is None:
            raise ValueError("No next src_route to swap with.")
        # route2 is the LastRoute sentinel: route is the vehicle's final route, so there
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
    travel_delta_1 = start_travel_delta_if_depot_swapped(route1_first_visit, end_depot_2)
    travel_delta_2 = start_travel_delta_if_depot_swapped(route2_first_visit, start_depot_1)
    travel_delta_3 = start_travel_delta_if_depot_swapped(route3_first_visit, end_depot_1) if route3_exists else 0 # type: ignore

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
