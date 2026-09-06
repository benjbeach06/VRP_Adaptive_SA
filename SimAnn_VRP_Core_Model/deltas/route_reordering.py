"""
Pricing for a substantial reordering of ONE route. The same customers stay on the same route, in a
new order.

Both functions are INTRA-ROUTE aggregators: they populate travel distance and nothing else. No
customer crosses a route boundary, so load, customer count, start depot and vehicle all end where
they started, and the whole travel delta belongs to that one route.

They do NOT price the same way, and the difference is worth knowing before you add a third.
A reversal has a boundary -- two arcs at the ends of the reversed span -- so it is O(1) like the
rest of the package. A permutation has no boundary at all, so it builds the new path and measures
it, which is O(path length). Its own WARNING comment says as much.

Single-customer moves and swaps are NOT reordering. They live in customer_chain_moves.
"""
from typing import Sequence

from ..basics import Chain, as_chain_range
from ..records import RawDeltaRecord
from ..routes import Route


#region Permutation (travel distance only)
def cost_deltas_for_permutation(route: Route, permutation: Sequence[int]) -> RawDeltaRecord:
    # WARNING: Must permute anyway to get the cost delta. Could be cheaper to apply the operator, compute, then unapply.
    if len(permutation) != len(route.path):
        raise ValueError("Permutation has wrong length")

    if set(permutation) != set(range(len(route.path))):
        raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

    path = route.path
    old_distance = route.total_distance()
    new_path = [route.first_visit] + [path[i] for i in permutation] + [route.last_visit]
    new_distance = sum(new_path[i].distance(new_path[i+1]) for i in range(len(new_path)-1))

    travel_delta = new_distance - old_distance

    # INTRA-ROUTE: distance and nothing else. No customer crosses a route boundary, so
    # load, count, start depot and vehicle all end where they started, and the whole
    # travel delta belongs to this one route.
    return RawDeltaRecord(travel_changes={route: travel_delta})
#endregion


#region Reversing a subpath
def cost_deltas_if_customer_chain_reversed(route: Route, chain: Chain) -> RawDeltaRecord:
    rng = as_chain_range(chain)
    assert 0 <= rng.start and rng.stop <= route.num_customers and len(rng) > 1, (
        f"cost_deltas_if_customer_chain_reversed {rng} out of range for "
        f"{route.num_customers} customers, or too short to change anything.")

    path = route.path

    # Delta just disconnects ends and reconnects in reverse!
    first_customer = path[rng.start]
    last_customer = path[rng.stop - 1]

    # Old: prev->first->...->last->next
    # New: prev->last->...->first->next
    old_distance = first_customer.distance_in + last_customer.distance_out
    new_distance = first_customer.prev_visit.distance(last_customer) + last_customer.next_visit.distance(first_customer)

    # INTRA-ROUTE: the whole travel delta belongs to this one route.
    travel_delta = new_distance - old_distance
    return RawDeltaRecord(travel_changes={route: travel_delta})
#endregion
