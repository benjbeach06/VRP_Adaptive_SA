"""
Pricing for sweeps that touch many routes at once.

One function today. It prices removing every empty route in a set, and that is NOT the sum of the
individual removals: two empty routes adjacent in the same vehicle chain would each charge the
successor for inheriting a start depot, and the successor only inherits once.

So it walks prev_route and next_route WITHIN the set, groups the removals into maximal chains, and
charges each chain's successor exactly once -- for starting where the chain STARTED rather than
where it ended.
"""
from typing import Mapping

from ..basics import Num
from ..nodes import Depot
from ..records import NO_CHANGES, RawDeltaRecord
from ..route_set import RouteSet
from ..routes import Route
from ..vehicle import Vehicle
from .visit_arcs import start_travel_delta_if_depot_swapped


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
            successor_travel = start_travel_delta_if_depot_swapped(successor.first_visit, 
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
