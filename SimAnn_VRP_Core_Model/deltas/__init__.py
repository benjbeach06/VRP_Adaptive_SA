"""
Move pricing: every delta computation in the core model, and nothing else.

Nothing here mutates, and nothing here reads an objective coefficient. A function takes the data
model as it stands and returns what a proposed change WOULD cost -- either a Num of travel
distance, or a RawDeltaRecord of raw structural change. Turning the second into objective terms is
the AccountingProcessor's job. See design/raw_delta_accounting/.

Import these from the core model like anything else:

    from SimAnn_VRP_Core_Model import cost_deltas_if_removed
    from SimAnn_VRP_Core_Model.deltas import route_moves

THE DEPENDENCY RUNS ONE WAY. This package imports the data model. The data model never imports
this package -- no module in it holds so much as a deferred reference. That is what lets the split
work with no cycle, no bottom-of-file import, and no TYPE_CHECKING guard anywhere in here. If you
ever need a core-model type to call a function from this package, that is the signal to stop and
reconsider, not to add an import.

These were methods on Route, RouteVisit and FullSolution until they were lifted out. `self` became
an explicitly typed first parameter named for its class -- `route`, `visit`, `sln`. The bodies did
not otherwise change.

WHERE THINGS LIVE
-----------------
    visit_arcs            the primitives: what one visit's arcs cost, before and after a change
    route_moves           the ROUTE moves: end depot, remove, insert, append, swap with successor
    customer_chain_moves  CUSTOMERS move: one or a chain, in, out, across, or swapped
    route_reordering      one route's own customers, same route, new order
    route_segmentation    split and combine: how many routes the vehicle's customers divide into
    solution_sweeps       many routes at once

DEPENDENCIES BETWEEN THESE MODULES, in full. `visit_arcs` imports none of the others, and neither
does `route_reordering`. `route_moves`, `customer_chain_moves` and `solution_sweeps` each import
only `visit_arcs`. `route_segmentation` imports `visit_arcs`, plus `travel_delta_if_route_removed`
from `route_moves` -- a combine prices the disappearance of the absorbed route. That is every edge,
and there are no cycles.
"""

from .visit_arcs import (current_route_load_delta_if_swapped_with,
                         end_travel_delta_if_route_removed,
                         get_replacement_travel_delta,
                         get_replacement_travel_deltas,
                         start_travel_delta_if_depot_swapped,
                         start_travel_delta_if_route_removed,
                         travel_delta_if_customer_replaced,
                         travel_delta_if_depot_stop_added_after_this,
                         travel_delta_if_swapped_with,
                         travel_delta_if_visit_removed,
                         travel_deltas_if_swapped_with)

from .route_moves import (cost_deltas_if_appended_to,
                          cost_deltas_if_end_depot_changes,
                          cost_deltas_if_inserted_before,
                          cost_deltas_if_removed,
                          cost_deltas_if_swapped_with_next_route,
                          travel_delta_if_appended_to,
                          travel_delta_if_end_depot_changes,
                          travel_delta_if_inserted_before,
                          travel_delta_if_route_removed)

from .customer_chain_moves import (cost_deltas_for_adjacent_customer_swap_starting_at,
                                   cost_deltas_for_adjacent_customer_swap_starting_with,
                                   cost_deltas_for_customer_chain_swap,
                                   cost_deltas_for_customer_swap,
                                   cost_deltas_for_inter_route_customer_swap_at,
                                   cost_deltas_for_intra_route_customer_swap_at,
                                   cost_deltas_if_customer_appended,
                                   cost_deltas_if_customer_chain_inserted_before,
                                   cost_deltas_if_customer_chain_moved,
                                   cost_deltas_if_customer_chain_removed,
                                   cost_deltas_if_customer_inserted_before,
                                   cost_deltas_if_customer_popped,
                                   cost_deltas_if_customer_removed,
                                   customer_chains_are_adjacent,
                                   total_load_deltas_for_customer_swap,
                                   travel_delta_if_customer_chain_removed,
                                   travel_delta_if_customer_inserted_before,
                                   travel_delta_if_customer_popped,
                                   travel_delta_if_customer_removed,
                                   travel_delta_if_unassigned_customer_appended,
                                   travel_deltas_if_customer_chain_inserted_before,
                                   travel_deltas_if_customer_chain_moved)

from .route_reordering import (cost_deltas_for_permutation,
                               cost_deltas_if_customer_chain_reversed)

from .route_segmentation import (cost_deltas_for_combine_with,
                                 cost_deltas_for_split_at,
                                 travel_delta_for_combine_with,
                                 travel_delta_for_combine_with_next,
                                 travel_delta_for_combine_with_nonadjacent,
                                 travel_delta_for_combine_with_prev)

from .solution_sweeps import cost_deltas_for_removing_empty_routes

from . import (customer_chain_moves, route_moves, route_reordering, route_segmentation,
               solution_sweeps, visit_arcs)
