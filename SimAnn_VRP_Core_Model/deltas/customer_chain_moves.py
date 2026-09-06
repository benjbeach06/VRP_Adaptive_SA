"""
Pricing for moves where CUSTOMERS are the objects that move: one customer, or a contiguous chain,
removed, popped, inserted, appended, relocated, or swapped -- within one route or across two.

Every function prices from the arcs at the move's BOUNDARY. Nothing here walks a path. Removing a
customer destroys two arcs and creates one; inserting does the reverse; and a chain move is those
two halves in sequence, which is why the sequential-halves region exists instead of a separate
closed form for it.

A swap is two customers exchanging positions, so neither route changes length. Chain swaps at
length 1 delegate to the single-customer swap rather than re-deriving adjacency and load, and the
four chain-swap travels collapse to one, because reversing a single customer changes nothing.
"""
from typing import Sequence

from ..basics import Chain, Num, as_chain_range
from ..records import NO_CHANGES, RawDeltaRecord
from ..routes import Route
from ..visits import CustomerVisit, LastRouteVisit
from .visit_arcs import (current_route_load_delta_if_swapped_with, travel_delta_if_swapped_with,
                         travel_delta_if_visit_removed, travel_deltas_if_swapped_with)


#region Basic customer operations: remove, pop, insert, append
#region Travel-related deltas
def travel_delta_if_customer_removed(customer: CustomerVisit) -> Num:
    return travel_delta_if_visit_removed(customer)

def travel_delta_if_customer_popped(route: Route, index: int) -> Num:
    if index >= route.path_len:
        raise IndexError("Customer index out of range.")
    return travel_delta_if_customer_removed(route.path[index])

def travel_delta_if_customer_inserted_before(customer: CustomerVisit, insert_visit: CustomerVisit | LastRouteVisit,
                                             customer_route: Route) -> Num:
    # For efficiency: callers need to gate for no-ops
    assert insert_visit is not customer and insert_visit.prev_visit is not customer, "Travel delta mini-method called on no-op."
    adjacent = customer.is_adjacent_with(insert_visit)

    return (travel_delta_if_swapped_with(customer, insert_visit)) if adjacent and isinstance(insert_visit, CustomerVisit) \
        else travel_delta_if_customer_removed(customer) + insert_visit.travel_delta_if_inserting_customer_before_this(customer)

def travel_delta_if_unassigned_customer_appended(route: Route, customer: CustomerVisit, customer_route: Route) -> Num:
    return travel_delta_if_customer_inserted_before(customer, route.last_visit, customer_route)
#endregion

#region Full deltas
def cost_deltas_if_customer_removed(route: Route, customer: CustomerVisit) -> RawDeltaRecord:
    travel_delta = travel_delta_if_customer_removed(customer)

    # A chain of one has no interior, so the link delta IS this route's whole change.
    raw = RawDeltaRecord.for_customers_changing((route, travel_delta, -customer.demand, -1))
    return raw

def cost_deltas_if_customer_popped(route: Route, index: int) -> RawDeltaRecord:
    travel_delta = travel_delta_if_customer_popped(route, index)

    raw = RawDeltaRecord.for_customers_changing(
        (route, travel_delta, -route.path[index].demand, -1))
    return raw

def cost_deltas_if_customer_inserted_before(route: Route, customer: CustomerVisit, insert_visit: CustomerVisit | LastRouteVisit) -> RawDeltaRecord:
    if insert_visit is customer or insert_visit is customer.next_visit:
        return RawDeltaRecord() # No-op!

    customer_route: Route | None = customer.route

    assert isinstance(insert_visit, CustomerVisit|LastRouteVisit)
    assert isinstance(customer_route, Route)

    # DECISION: We don't compute full cost deltas explicitly for unassigned customers.
    # IN THE EVENT we choose to add support for this (e.g. for multi-day delivery plans where some customers don't get deliveries):
    # We will split into "Unassigned" and "Assigned" versions for add/insert operations, and this method
    # will triage between the two.


    if customer_route is route:
        # Same route: nothing crosses a boundary, so the whole link delta is this route's.
        assert isinstance(customer_route, Route)
        travel_delta = travel_delta_if_customer_inserted_before(
            customer, insert_visit, customer_route)
        return RawDeltaRecord(travel_changes={route: travel_delta})

    # CROSS-ROUTE, and the two halves are already route-local: the source closes the gap
    # the customer leaves, the destination opens one for it. A single customer carries no
    # interior arcs, so no sub-chain sum is needed here.
    assert isinstance(customer_route, Route)
    source_travel = travel_delta_if_customer_removed(customer)
    dest_travel = insert_visit.travel_delta_if_inserting_customer_before_this(customer)

    raw = RawDeltaRecord.for_customers_changing(
        (route, dest_travel, customer.demand, 1),
        (customer_route, source_travel, -customer.demand, -1))

    return raw

def cost_deltas_if_customer_appended(route: Route, customer):
    return cost_deltas_if_customer_inserted_before(route, customer, route.last_visit)
#endregion
#endregion


#region Customer chains: sequential halves -- remove, then insert
#region Travel-related deltas
def travel_delta_if_customer_chain_removed(route: Route, chain: Chain) -> Num:
    """Closing the gap a chain leaves behind. Orientation-independent."""
    rng = as_chain_range(chain)
    path = route.path
    first = path[rng.start]
    last = path[rng.stop - 1]
    before_chain = first.prev_visit
    after_chain = last.next_visit

    return (before_chain.distance(after_chain)
            - before_chain.distance(first) - last.distance(after_chain))

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

def travel_deltas_if_customer_chain_moved(route: Route, chain: Chain,
                                          insert_visit: CustomerVisit | LastRouteVisit) -> tuple[Num, Num]:
    # Returns (not_reversed, reversed), in that order.
    rng = as_chain_range(chain)
    path = route.path
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
#endregion

#region Full deltas
def cost_deltas_if_customer_chain_removed(route: Route, chain: Chain) -> RawDeltaRecord:
    """
    Price taking `chain` out of this route, charged BEFORE the removal happens.

    A chain of one is the single-customer removal, so this widens
    cost_deltas_if_customer_removed rather than sitting beside it.
    """
    rng = as_chain_range(chain)
    k = len(rng)
    if k == 0:
        return RawDeltaRecord()

    path = route.path
    chain_load = sum(path[i].demand for i in rng)

    # The link delta closes the gap the chain leaves. The route ALSO loses the chain's
    # interior arcs, which travel with the detached visits, so this route's own change is
    # the link delta minus that interior. The matching insert half adds it back.
    travel_delta = (travel_delta_if_customer_chain_removed(route, rng)
                    - route.path_distance(rng.start, rng.stop))

    # Only this route moves. The visits come out DETACHED -- they belong to no route until
    # someone inserts them -- so there is no second entry to make here. Start depot and
    # vehicle are untouched even when the route empties completely: an empty route is still
    # an assigned route, and whether it still COUNTS as using its depot is a step function
    # of the customer count, which the processor resolves. Reported, not decided.
    raw = RawDeltaRecord.for_customers_changing((route, travel_delta, -chain_load, -k))

    return raw

def cost_deltas_if_customer_chain_inserted_before(
        route: Route, visits: Sequence[CustomerVisit],
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

    fwd_travel, rev_travel = travel_deltas_if_customer_chain_inserted_before(
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
    raw_fwd = RawDeltaRecord.for_customers_changing((route, fwd_travel, chain_load, k))
    raw_rev = RawDeltaRecord.for_customers_changing((route, rev_travel, chain_load, k))

    return raw_fwd, raw_rev

def cost_deltas_if_customer_chain_moved(route: Route, chain: Chain, dest_route: Route,
                                        dest_idx: int) -> tuple[RawDeltaRecord, RawDeltaRecord]:
    # Returns (not_reversed, reversed). The two differ ONLY in travel_distance: the other
    # four terms depend on which customers moved and where to, never on their order.
    # This makes no decision -- it hands back both prices and the caller picks.
    rng = as_chain_range(chain)
    k = len(rng)
    same_route = dest_route is route

    # Mirrors ReassignCustomerAt's pre-removal precedent fetch, widened from one customer
    # to k: moving right within a route, everything from dest_idx on shifts left by k once
    # the chain is gone, so before the removal the visit to insert before sits k further on.
    insert_visit = dest_route.get_visit_at(
        dest_idx + k if same_route and rng.start <= dest_idx else dest_idx)
    assert isinstance(insert_visit, CustomerVisit | LastRouteVisit)

    fwd_travel, rev_travel = travel_deltas_if_customer_chain_moved(route, rng, insert_visit)

    if same_route:
        # No customer crosses a route boundary, so load, depot and vehicle are untouched --
        # and the whole travel delta belongs to this one route.
        return (RawDeltaRecord(travel_changes={route: fwd_travel}),
                RawDeltaRecord(travel_changes={route: rev_travel}))

    chain_load = sum(route.path[i].demand for i in rng)

    # CROSS-ROUTE. The link deltas are only jointly correct: the source genuinely loses the
    # chain's interior arcs and the destination genuinely gains them, and neither half
    # names them. Split by moving that interior across, which is the one sub-chain sum this
    # aggregator needs.
    interior = route.path_distance(rng.start, rng.stop)
    source_travel = travel_delta_if_customer_chain_removed(route, rng) - interior
    fwd_dest_travel = fwd_travel - source_travel
    rev_dest_travel = rev_travel - source_travel

    # The chain crosses a boundary: k customers leave route and join dest_route. The
    # same-route case returned above, so these are always two distinct entries.

    # changes = (route, travel_change, load_change, customer_count_change)
    self_changes = (route, source_travel, -chain_load, -k)

    raw_fwd = RawDeltaRecord.for_customers_changing(
            self_changes, (dest_route, fwd_dest_travel, chain_load, k))
    raw_rev = RawDeltaRecord.for_customers_changing(
        self_changes, (dest_route, rev_dest_travel, chain_load, k))

    return raw_fwd, raw_rev
#endregion
#endregion


#region Customer swaps
#region Adjacent customers
# can only change travel distance or route loads)
def cost_deltas_for_adjacent_customer_swap_starting_with(customer1: CustomerVisit):
    customer2 = customer1.next_visit
    if not isinstance(customer2, CustomerVisit):
        raise ValueError("Specified customer is at the end of a src_route.")

    # Swapping adjacent customers affects only travel distance:
    # No depots/vehicles are activated and no src_route loads change.

    travel_delta = travel_delta_if_swapped_with(customer1, customer2)
    # INTRA-ROUTE: distance and nothing else. No customer crosses a route boundary, so
    # load, count, start depot and vehicle all end where they started, and the whole travel
    # delta belongs to the one route the two customers share.
    route = customer1.route
    assert isinstance(route, Route)
    return RawDeltaRecord(travel_changes={route: travel_delta})

def cost_deltas_for_adjacent_customer_swap_starting_at(route: Route, index: int):
    # Get cost for swapping customer at index with the next one.
    if index >= route.path_len - 1 or index < 0:
        if index == route.path_len - 1:
            raise ValueError("Specified customer has no next customer.")
        else:
            raise ValueError("Customer index out of range.")

    path = route.path
    customer1 = path[index]

    return cost_deltas_for_adjacent_customer_swap_starting_with(customer1)
#endregion

#region Any two customers, in one route or across two
def total_load_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit) -> tuple[Num, Num]:
    # Returns (route1 delta, route2 delta)
    route1 = customer1.route
    route2 = customer2.route

    if route1 is None or route2 is None:
        raise ValueError("Cannot swap customers that aren't assigned to routes!")

    # current_route_load_delta_if_swapped_with, not a bare demand difference: it reduces
    # numerical error when both customers share a route.
    route1_load_delta = current_route_load_delta_if_swapped_with(customer1, customer2)
    return route1_load_delta, -route1_load_delta

# Any two customers
def cost_deltas_for_customer_swap(customer1: CustomerVisit, customer2: CustomerVisit):
    # Implement all deltas in one place to prevent rework such as recomputing load deltas.

    # A swap moves LOAD but not COUNT: each route gives one customer and takes one back.
    # Intra-route swaps move nothing at all, and their entries cancel to unchanged.
    route1, route2 = customer1.route, customer2.route
    assert route1 is not None and route2 is not None
    if route1 is route2:
        raw = RawDeltaRecord(
            travel_changes={route1: travel_delta_if_swapped_with(customer1, customer2)})
    else:
        # Two routes, and the two halves are already route-local: each side is one
        # customer replaced by another in place. Neither carries an interior.
        travel1, travel2 = travel_deltas_if_swapped_with(customer1, customer2)
        route1_load_delta = current_route_load_delta_if_swapped_with(customer1, customer2)
        raw = RawDeltaRecord.for_customers_changing(
            (route1, travel1, route1_load_delta, 0),
            (route2, travel2, -route1_load_delta, 0))

    # Swapping customers does not change vehicle or depot activation. So we're ready to return.
    return raw

def cost_deltas_for_intra_route_customer_swap_at(route: Route, i: int, j: int):
    customer1 = route.path[i]
    customer2 = route.path[j]

    return cost_deltas_for_customer_swap(customer1, customer2)

def cost_deltas_for_inter_route_customer_swap_at(route: Route, i: int, other: Route, j: int):
    customer1 = route.path[i]
    customer2 = other.path[j]

    return cost_deltas_for_customer_swap(customer1, customer2)
#endregion

#region Customer chains
def customer_chains_are_adjacent(route: Route, chain: Chain, other: Route, other_chain: Chain) -> bool:
    # Only possible within one route. Adjacent chains share a boundary arc, which makes
    # the two reversals interact -- see cost_deltas_for_customer_chain_swap.
    if route is not other:
        return False
    rng1, rng2 = as_chain_range(chain), as_chain_range(other_chain)
    return rng1.stop == rng2.start or rng2.stop == rng1.start

def cost_deltas_for_customer_chain_swap(route: Route, chain: Chain, other: Route, other_chain: Chain
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
    path1, path2 = route.path, other.path

    c1_first, c1_last = path1[rng1.start], path1[rng1.stop - 1]
    c2_first, c2_last = path2[rng2.start], path2[rng2.stop - 1]

    if len(rng1) == 1 and len(rng2) == 1:
        # Reversing one customer changes nothing, so all four are equal. The
        # single-customer swap delta already covers adjacency, load and overload, so
        # delegate rather than re-derive any of it here.
        delta = cost_deltas_for_customer_swap(c1_first, c2_first)
        return delta, delta, delta, delta

    if customer_chains_are_adjacent(route, rng1, other, rng2):
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
        moved = cost_deltas_if_customer_chain_moved(route, early, route, early.start + len(late))
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

        if route is other:
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
            interior1 = route.path_distance(rng1.start, rng1.stop)
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
        if route is other:
            return RawDeltaRecord(travel_changes={route: own_travel} if own_travel
                                  else NO_CHANGES)
        return RawDeltaRecord.for_customers_changing(
            (route, own_travel, chain2_load - chain1_load, len(rng2) - len(rng1)),
            (other, other_travel, chain1_load - chain2_load, len(rng1) - len(rng2)))

    return tuple(  # type: ignore - fixed length 4, built from a 4-tuple
        raw(t) for t in travels)
#endregion
#endregion
