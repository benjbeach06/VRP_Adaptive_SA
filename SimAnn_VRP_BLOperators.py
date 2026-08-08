from typing import Sequence

from SimAnn_VRP_Core_Model import *
from abc import ABC, abstractmethod
import numpy as np

from SimAnn_VRP_Core_Model import Vehicle, Route

INVALID_OP = -float('inf')
class OperatorBL(ABC):
    # Base class for operator BL: performing operations of a given type and computing solution deltas.
    # Requires operand selection.
    def __init__(self, sln: FullSolution):
        self.sln = sln

        self.last_improvement: Num = 0
        self._revert_info = None

        # Operate just calls the implementation.
        self.operate = self._operate_impl
        self.operate_pure = self._operate_pure_impl

    def prev_operation_was_useful(self):
        #"Useful" = "valid and nontrivial" - which in either case is exactly when revert info is not none
        return self._revert_info is not None

    def revert(self):
        """
        Calls the subclass’s _revert_impl with the last revert_info.
        """
        if self._revert_info is None:
            return # Operation was not possible - so don't revert
        self._revert_impl()
        self._revert_info = None

    @abstractmethod
    def compute_improvement(self, *args, **kwargs) -> tuple[Num, bool]:
        # Just calculate potential improvement. By default, operates, reverts, and returns the improvement.
            # But if the improvement can be computed without actually operating, then a custom
            # implementation could calculate this potential improvement faster.

        self.operate(*args, **kwargs)
        return self.last_improvement, True

    @abstractmethod
    def _operate_impl(self, *args, **kwargs):
        """
        Core BL operator
        Subclasses must:
          1) Edit self.solution in place.
          2) Set revert info and last_improvement:
             - self.revert_info = minimal data needed by _revert_impl
             - self.last_improvement = -delta_cost = -(new_cost-old_cost) (used for adaptive weighting and SA accept/reject).
                - Note that this improvement can also be computed via compute_improvement function.
             - If the operation is a no-op or is illegal: subclass must:
                -- Not operate
                -- Set self.revert_info to None
                -- Set self.last_improvement to 0
        """
        pass

    @abstractmethod
    def _revert_impl(self):
        """
        Undo exactly what _operate_impl dID, using the revert_info from last operate().
        """
        pass

    @abstractmethod
    def _operate_pure_impl(self, *args, **kwargs):
        """
        Just operates with no extra computations.
        Intention is to separate out the core solution operation from the
            determination of improvement and reversion data computation.
        """

        pass

    def compute_improvement_from_deltas(self, deltas: ObjectiveTermDelta):
        sln = self.sln
        return deltas.get_cost_improvement(travel_unit_cost=sln.unit_travel_cost, vehicle_cost=sln.cost_per_vehicle,
                                           depot_cost=sln.cost_per_depot, overload_penalty=sln.unit_overload_penalty)

# Note: Marking no-ops as invalid now to help reduce flailing in place. 0-cost ops can help; no-ops can't
class ReassignRouteBefore(OperatorBL):
    _revert_info: tuple[Route, Route|LastRoute|None]|None

    def compute_improvement(self, src_route: Route, dest_route: Route|LastRoute) -> tuple[Num, bool]:
        if dest_route.vehicle is None:
            # Destination route is unassigned!
            return INVALID_OP, False

        if (src_route.is_empty or src_route is dest_route or src_route.next_route is dest_route or
                src_route.prev_route is dest_route and dest_route.is_empty): # type: ignore - prev routes are never last routes
            # No-ops for reassign to before self, to current location, or to before previous route if prev is empty
            # (if prev is empty, the op is equivalent to moving that empty route forward one - prevented)
            return INVALID_OP, False

        deltas = src_route.cost_deltas_if_inserted_before(dest_route)
        return self.compute_improvement_from_deltas(deltas), False

    def __init__(self, sln: FullSolution):
        super().__init__(sln)


    def _operate_pure_impl(self, src_route: Route, dest_route: Route|LastRoute):
        # Operation is: Reassign src_route to target vehicle at split_index insertion_index
        src_route.link_to_vehicle_before(dest_route)

    def _operate_impl(self, src_route: Route, dest_route: Route|LastRoute):
        # Operation is: Reassign src_route to target vehicle at split_index insertion_index
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-src_route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-src_route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.

        # INVALID: destination unassigned
        if dest_route.vehicle is None:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        # NO-OP (dest is self or next) or PREVENTED: Moving empty routes
        if (src_route.is_empty or src_route is dest_route or src_route.next_route is dest_route or
                src_route.prev_route is dest_route and dest_route.is_empty): # type: ignore - prev routes are never last routes
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        (improvement, _) = self.compute_improvement(src_route, dest_route)

        self._revert_info = (src_route, src_route.next_route)

        # Operate
        self.operate_pure(src_route, dest_route)

        # Report and prep for reversion
        self.last_improvement = improvement

    def _revert_impl(self):
        # Operation is: Reassign src_route to target vehicle at split_index insertion_index
        #   So: Reversion reassigns it back to its original vehicle and location split_index
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check

        (route, successor) = self._revert_info
        if successor is None:
            # This branch should never happen as a nonempty route should never be linked
            route.unlink_from_vehicle()
        else:
            route.link_to_vehicle_before(successor)

class ReassignCustomerAt(OperatorBL):
    _revert_info: tuple[Route, int, Route, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index: int, dest_route: Route, dest_index: int) -> tuple[Num, bool]:
        if src_index > len(src_route.path) - 1 or dest_index > len(dest_route.path) \
                or (src_route == dest_route and dest_index == len(dest_route.path)):
            # In the last case: you're moving within the same list - so the "last insert" is no longer valid.
            # Otherwise: can move to the end of a different src_route (to become the new last element), but not beyond it
            return INVALID_OP, False # Invalid operation

        if src_route == dest_route and src_index == dest_index:
            return INVALID_OP, False # trivial op

        if src_route == dest_route and abs(src_index - dest_index) == 1:
            min_id = min(src_index, dest_index)
            deltas = src_route.cost_deltas_for_adjacent_customer_swap_starting_at(min_id)
        else:
            deltas = src_route.cost_deltas_if_customer_popped(src_index)
            customer = src_route.path[src_index]

            if src_route == dest_route and src_index < dest_index:
                # Must account for target index shifting before you can insert! The next customer (if any) post-reassign
                #     is the one currently at dest_index + 1 due to this shift.
                deltas += dest_route.cost_deltas_if_customer_inserted(customer, dest_index + 1)
            else:
                deltas += dest_route.cost_deltas_if_customer_inserted(customer, dest_index)

        return self.compute_improvement_from_deltas(deltas), False

    def _operate_pure_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        if src_route == dest_route and src_index == dest_index:
            return

        customer = src_route.pop_customer_at(src_index)
        dest_route.insert_customer(customer, dest_index)

    def _operate_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        #self.orig_data = f"Orig: src_route_len:{len(src_route.path)}, src_index:{src_index}, dest_route_len:{len(dest_route.path)}, dest_index:{dest_index}"

        if src_index > len(src_route.path) - 1 or \
            src_route == dest_route and dest_index == len(dest_route.path):
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if src_route == dest_route and src_index == dest_index:
            self._revert_info = None
            self.last_improvement = 0
            return

        (self.last_improvement, _) = self.compute_improvement(src_route, src_index, dest_route, dest_index)
        self._revert_info = (src_route, src_index, dest_route, dest_index)

        self.operate_pure(src_route, src_index, dest_route, dest_index)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        src_route, src_index, dest_route, dest_index = self._revert_info
        #print(self.orig_data)
        #print(f"Post: src_route_len:{len(src_route.path)}, src_index:{src_index}, dest_route_len:{len(dest_route.path)}, dest_index:{dest_index}")
        self._operate_pure_impl(dest_route, dest_index, src_route, src_index)
        #print(f"Revt: src_route_len:{len(src_route.path)}, src_index:{src_index}, dest_route_len:{len(dest_route.path)}, dest_index:{dest_index}\n")

"""
TODO: Finish this one with more efficient cost comps. It's tougher than the customer-move operators because it also involves adding in a src_route
    to an existing vehicle - and thus requires more involved computations. Route splitting is easier to implement.
"""
class ReassignCustomerToNewRouteBefore(OperatorBL):
    _revert_info: tuple[Route, int, Route]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index: int, dest_route: Route, end_depot: Depot) -> tuple[Num, bool]:
        remove_delta = src_route.cost_deltas_if_customer_popped(src_index)

        # Gotta coppy customer sans linkages: Otherwise adding it to the new src_route will overwrite its linkages
        customer = copy.copy(src_route.path[src_index])
        new_route = Route([customer], end_depot)

        add_delta = new_route.cost_deltas_if_inserted_before(dest_route)

        deltas = add_delta + remove_delta
        return self.compute_improvement_from_deltas(deltas), False

    def _operate_pure_impl(self, src_route: Route, src_index: int, dest_route: Route, end_depot: Depot) -> Route:
        sln = self.sln

        customer = src_route.pop_customer_at(src_index)
        new_route = Route([customer], end_depot)
        new_route.link_to_vehicle_before(dest_route)
        sln.all_routes.add(new_route)
        return new_route


    def _operate_impl(self, src_route: Route, src_index: int, dest_route: Route, end_depot: Depot):
        if not 0 <= src_index < src_route.num_customers or not dest_route.is_assigned:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        self.last_improvement, _ = self.compute_improvement(src_route, src_index, dest_route, end_depot)

        new_route = self.operate_pure(src_route, src_index, dest_route, end_depot)

        self._revert_info = (src_route, src_index, new_route)


    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        sln = self.sln

        src_route, src_index, new_route = self._revert_info
        new_route.unlink_from_vehicle()

        src_route.insert_customer(new_route.path[0], src_index)

        # (Obsolete bug funny comment from when all_routes was an array):
        # The new src_route was most recently appended on the end. So we pop it! Like a balloon
        sln.all_routes.remove(new_route)

class SwapCustomersAt(OperatorBL):
    _revert_info: tuple[Route, int, Route, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, route1: Route, index1: int, route2: Route, index2: int) -> tuple[Num, bool]:
        if index1 > len(route1.path) - 1 or index2 > len(route2.path) - 1:
            return INVALID_OP, False

        if route1 == route2 and index1 == index2:
            return INVALID_OP, False

        deltas = route1.cost_deltas_for_inter_route_customer_swap_at(index1, route2, index2)

        return self.compute_improvement_from_deltas(deltas), False

    def _operate_pure_impl(self, route1: Route, index1: int, route2: Route, index2):
        if route1 == route2 and index1 == index2:
            return

        route1.swap_customers_with(index1, route2, index2)

    def _operate_impl(self, route1: Route, index1: int, route2: Route, index2: int):
        # Note: This body is nearly identical to the Reassign (move) version of this operator.
        if not 0 <= index1 < len(route1.path) and 0 <= index2 < len(route2.path):
            #Index out of bounds
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if route1 == route2 and index1 == index2:
            # No-op
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        self.last_improvement, _ = self.compute_improvement(route1, index1, route2, index2)
        self._revert_info = (route1, index1, route2, index2)

        self.operate_pure(route1, index1, route2, index2)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        route1, index1, route2, index2 = self._revert_info

        # Reapplying the operator just swaps back
        self._operate_pure_impl(route1, index1, route2, index2)


def invert_permutation(permutation: Sequence[int]) -> Sequence[int]:
    # This stupid fast solution was found on Stack Overflow. Poster found a ~4us runtime for 1000 entries!
    inv = np.empty_like(permutation)
    inv[permutation] = np.arange(len(inv), dtype=inv.dtype)
    return inv

class PermuteRoute(OperatorBL):
    _revert_info: tuple[Route, Sequence[int]]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, *args, **kwargs) -> tuple[Num, bool]:
        return super().compute_improvement(*args, **kwargs)

    def _operate_pure_impl(self, route: Route, permutation: Sequence[int]):
        route.permute(permutation)

    def _operate_impl(self, route: Route, permutation: list[int]):
        sln = self.sln

        old_distance = route.total_distance()

        try:
            self.operate_pure(route, permutation)
        except(IndexError, TypeError):
            print("Warning: illegal permutation specified.")
            self._revert_info = None
            self.last_improvement = 0
            return

        new_distance = route.total_distance()

        self.last_improvement = -sln.unit_travel_cost * (new_distance - old_distance)
        self._revert_info = (route, permutation)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        route, permutation = self._revert_info
        inv_permutation = invert_permutation(permutation)
        self.operate_pure(route, inv_permutation)


class ChangeEndDepot(OperatorBL):
    _revert_info: tuple[Route, Depot]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, route: Route, new_end_depot: Depot) -> tuple[Num, bool]:
        deltas = route.cost_deltas_if_end_depot_changes(new_end_depot)
        return self.compute_improvement_from_deltas(deltas), False


    def _operate_pure_impl(self, route: Route, new_end_depot: Depot):
        route.set_end_depot(new_end_depot)


    def _operate_impl(self, route: Route, new_end_depot: Depot):
        old_end_depot = route.end_depot

        if route.is_empty:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        # No-op condition (we disallow no-ops)
        if new_end_depot == old_end_depot:
            self.last_improvement = INVALID_OP
            self._revert_info = None
            return

        self.last_improvement, _ = self.compute_improvement(route, new_end_depot)

        self.operate_pure(route, new_end_depot)

        self._revert_info = (route, old_end_depot)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        (route, old_end_depot) = self._revert_info
        self.operate_pure(route, old_end_depot)


class DisposeOfEmptyRoutesBL(OperatorBL):
    # Disposes of the given routes. MUST check if they're empty before disposing!
    # If used correctly: This will never worsen the solution.
    # Disadvantage of making this separate: dest_route operators won't get credit for emptying routes.
    # Advantage of making this separate: Simplifies logic and reversion for dest_route operators,
    #   As they need not dispose of routes they empty, or revert them post-disposal.
    _revert_info: tuple[list[tuple[Route, Route|FirstRoute|None]]]|None

    def __init__(self, sln: FullSolution, dispose_only_trivial_routes = True):
        super().__init__(sln)

        # This property defines whether we dispose of routes that just move from one depot to another.
        self.dispose_only_trivial_routes = dispose_only_trivial_routes

    def compute_improvement(self, routes: Collection[Route]) -> tuple[Num, bool]:
        if self.dispose_only_trivial_routes:
            return INVALID_OP, False

        deltas = FullSolution.cost_deltas_for_removing_empty_routes(routes)
        return self.compute_improvement_from_deltas(deltas), False

    def _operate_pure_impl(self, routes: Collection[Route]):
        self.sln.remove_routes(routes)

    def _operate_impl(self, routes: Collection[Route]):
        if len(routes) == 0:
            self._revert_info = None
            self.last_improvement = 0
            return

        assert all(route.is_empty for route in routes), "Cannot dispose of nonempty routes! You'll lose customers."

        sln = self.sln
        prev_obj = 0
        if not self.dispose_only_trivial_routes:
            # We just re-evaluate the objective for simplicity.
            prev_obj = sln.solution_cost()
        else:
            # No savings - trivial routes do not impact the objective.
            self.last_improvement = 0

        revert_stack: list[tuple[Route, Route|FirstRoute|None]] = []
        self._revert_info = (revert_stack,)
        # Each item in revert stack is a tuple of [item removed, item's predecessor].
        # Thus, to revert: in reverse order, we add in the route after its predecessor.
        # NOTE: early predecessors may be removed routes later in the list!

        # Remove all the routes from their vehicles, with predecessor info. (Routes with no predecessor shouldn't exist, but are supported.)
        all_routes = sln.all_routes
        for route in routes:
            revert_stack.append((route, route.prev_route))
            route.dispose()

        # Remove routes from all_routes
        all_routes.difference_update(routes)

        if not self.dispose_only_trivial_routes:
            self.last_improvement = -(sln.solution_cost() - prev_obj)


    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        reversions, = self._revert_info

        all_routes = self.sln.all_routes
        for route, prev_route in reversed(reversions):
            if prev_route is not None:
                route.link_to_vehicle_after(prev_route)
            all_routes.add(route)


class SplitRoute(OperatorBL):
    _revert_info: tuple[Route]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, route: Route, split_index: int, intermediate_end_depot: Depot) -> tuple[Num, bool]:
        # To be splittable: src_route must have multiple customers (each customer to a different src_route).
        #   Index out of bounds: invalid. Index = 0 or split_index == path length => there is no customer to split.
        num_customers = route.num_customers
        
        if num_customers <= 1 or 0 == split_index or split_index >= num_customers:
            # Invalid src_route cID
            return INVALID_OP, False

        deltas = route.cost_deltas_for_split_at(split_index, intermediate_end_depot)
        return self.compute_improvement_from_deltas(deltas), False

    def _operate_pure_impl(self, route: Route, split_index: int, intermediate_end_depot: Depot):
        new_route = route.split_at(split_index, intermediate_end_depot)
        self.sln.all_routes.add(new_route)

    def _operate_impl(self, route: Route, split_index: int, intermediate_end_depot: Depot):
        num_customers = route.num_customers
        if num_customers <= 1 or 0 == split_index or split_index >= num_customers:
            # Invalid src_route cID, src_route unsplittable, or split index doesn't meaningfully split the src_route
            self.last_improvement = INVALID_OP
            self._revert_info = None
            return

        self.last_improvement, _ = self.compute_improvement(route, split_index, intermediate_end_depot)
        self.operate_pure(route, split_index, intermediate_end_depot)

        self._revert_info = (route,)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        route, = self._revert_info

        next_route = route.next_route
        assert isinstance(next_route, Route), "Invalid revert info: route does not have a next route right after a split!"

        # We added the new src_route to the end of all_routes - so we can simply pop.
        route.combine_with(next_route)
        self.sln.all_routes.remove(next_route)