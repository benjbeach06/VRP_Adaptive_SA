from typing import Collection

from SimAnn_VRP_Core_Model import *
from abc import ABC, abstractmethod
import numpy as np

from SimAnn_VRP_Core_Model import Vehicle

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

    def compute_improvement(self, *args, **kwargs) -> Num:
        # Just calculate potential improvement. By default, operates, reverts, and returns the improvement.
            # But if the improvement can be computed without actually operating, then a custom
            # implementation could calculate this potential improvement faster.
        self.operate(*args, **kwargs)
        self.revert()

        return self.last_improvement


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
class ReassignRouteAt(OperatorBL):
    _revert_info: tuple[Route, Vehicle, int]|None

    def compute_improvement(self, src_vehicle: Vehicle, src_index: int, dest_vehicle: Vehicle, dest_index: int):
        if src_index >= src_vehicle.num_routes or dest_index >= dest_vehicle.num_routes:
            return INVALID_OP

        src_route: Route | None = src_vehicle.route_at(src_index)
        dest_route: Route | None = dest_vehicle.route_at(dest_index)
        if src_route is None:
            return INVALID_OP

        is_self = src_route is dest_route
        is_adjacent = src_route.is_adjacent_with(dest_route) # implies dest_route is not None

        if is_self or src_route.is_empty or is_adjacent and dest_route.is_empty: # type: ignore - if is_adjacent then dest_route exists
            # We don't operate on empty routes except for removing them!
            # And we don't move to same location.
            return INVALID_OP

        deltas = src_route.cost_deltas_if_inserted_at(dest_vehicle, dest_index)
        return self.compute_improvement_from_deltas(deltas)

    @staticmethod
    def reassign_is_adjacent(src_vehicle: Vehicle, src_index: int, dest_vehicle: Vehicle, dest_index: int) -> bool:
        if dest_index >= dest_vehicle.num_routes:
            return False

        return src_vehicle.routes[src_index].is_adjacent_with(dest_vehicle.routes[dest_index])

    def __init__(self, sln: FullSolution):
        super().__init__(sln)


    def _operate_pure_impl(self, route, vehicle, insertion_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        route.vehicle.remove_route(route)
        vehicle.insert_route(route, insertion_index)

    def _operate_impl(self, src_vehicle, src_index, dest_vehicle, dest_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.

        route = src_vehicle.routes[src_index]

        is_adjacent_swap = self.reassign_is_adjacent(src_vehicle, src_index, dest_vehicle, dest_index)
        is_same_vehicle = src_vehicle == dest_vehicle
        num_routes = dest_vehicle.num_routes

        # INVALID: index out of range. (If within same vehicle, remove decrements size, so range is smaller)
        if src_index >= src_vehicle.num_routes or dest_index > num_routes or\
                is_same_vehicle and dest_index >= num_routes:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        # NO-OP or PREVENTED: Moving empty routes
        if route.is_empty or is_same_vehicle and src_index == dest_index\
                or is_adjacent_swap and dest_vehicle.routes[dest_index].is_empty:

            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        improvement = self.compute_improvement(src_vehicle, src_index, dest_vehicle, dest_index)

        # Operate
        self.operate_pure(route, dest_vehicle, dest_index)

        # Report and prep for reversion
        self.last_improvement = improvement

        # This line is the only thing preventing us from scrapping the operator in favor of ReassignRoute!
        # We must know the src_index to populate the reversion info.
        self._revert_info = (route, src_vehicle, src_index)

    def _revert_impl(self):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        #   So: Reversion reassigns it back to its original vehicle and location split_index
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        (route, src_vehicle, src_index) = self._revert_info
        self._operate_pure_impl(route, src_vehicle, src_index)

class ReassignRoute(OperatorBL):
    _revert_info: tuple[Route, Vehicle, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

        self._reassign_route_at_operator = ReassignRouteAt(sln)

        # TODO: Make this actually shortcut properly with the one-time get rather than on each call
        self._operate_pure_impl = self._reassign_route_at_operator.operate_pure

    def _operate_pure_impl(self, route, vehicle, insertion_index):
        return self._reassign_route_at_operator.operate_pure(route, vehicle, insertion_index)

    def _operate_impl(self, route: Route, vehicle: Vehicle, insertion_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.

        # TODO: Address case that route is trivial
        #   NOTE: we implicitly assume here that all non-empty ("assignable") routes are assigned during a solve.
        #     We also implicitly assume that this won't be called on unassigned routes at all.
        #   Need to adjust this implementation for cases where the route is empty or unassigned.
        #  ALSO pure revert WON'T handle "Revert info is None" scenarios properly:
        #  Self._revert_info is NEVER ACTUALLY WRITTEN TO
        #  THUS: SELF.REVERT() IS ALWAYS A NO-OP! OMG FIX THIS

        dest_vehicle = vehicle
        dest_index = insertion_index
        src_vehicle = route.vehicle
        src_index = route.vehicle.routes.index(route)

        self._reassign_route_at_operator.operate(src_vehicle, src_index, dest_vehicle, dest_index)

        self.last_improvement = self._reassign_route_at_operator.last_improvement
        #self._revert_info = self._reassign_route_at_operator._revert_info

    def _revert_impl(self):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        #   So: Reversion reassigns it back to its original vehicle and location split_index
        #self._reassign_route_at_operator._revert_info = self._revert_info
        self._reassign_route_at_operator.revert() # Do it this way so that _reassign_route_at_operator also reverts its info


class ReassignCustomerAt(OperatorBL):
    _revert_info: tuple[Route, int, Route, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index, dest_route: Route, dest_index):
        if src_index > len(src_route.path) - 1 or dest_index > len(dest_route.path) \
                or (src_route == dest_route and dest_index == len(dest_route.path)):
            # In the last case: you're moving within the same list - so the "last insert" is no longer valid.
            # Otherwise: can move to the end of a different route (to become the new last element), but not beyond it
            return INVALID_OP # Invalid operation

        if src_route == dest_route and src_index == dest_index:
            return 0 # trivial op

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

        return self.compute_improvement_from_deltas(deltas)

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

        self.last_improvement = self.compute_improvement(src_route, src_index, dest_route, dest_index)
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
TODO: Finish this one with more efficient cost comps. It's tougher than the customer-move operators because it also involves adding in a route
    to an existing vehicle - and thus requires more involved computations. Route splitting is easier to implement.
"""
class ReassignCustomerToNewRouteAt(OperatorBL):
    _revert_info: tuple[Route, int, Vehicle, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index: int, dest_vehicle: Vehicle, dest_index: int, end_depot: Depot):
        remove_delta = src_route.cost_deltas_if_customer_popped(src_index)

        # Gotta coppy customer sans linkages: Otherwise adding it to the new route will overwrite its linkages
        customer = copy.copy(src_route.path[src_index])
        new_route = Route([customer], end_depot)

        add_delta = new_route.cost_deltas_if_inserted_at(dest_vehicle, dest_index)

        deltas = add_delta + remove_delta
        return self.compute_improvement_from_deltas(deltas)

    def _operate_pure_impl(self, src_route: Route, src_index: int, dest_vehicle: Vehicle, dest_index: int, end_depot: Depot):
        sln = self.sln

        customer = src_route.pop_customer_at(src_index)
        dest_route = Route([customer], end_depot)
        dest_vehicle.insert_route(dest_route, dest_index)
        sln.all_routes.add(dest_route)

    def _operate_impl(self, src_route: Route, src_index: int, dest_vehicle: Vehicle, dest_index: int, end_depot: Depot):
        sln = self.sln

        if src_index > len(src_route.path) - 1 or dest_index > len(dest_vehicle.routes) - 1 or\
            src_index < 0 or dest_index < 0:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        self.old_objective = sln.solution_cost()
        self._revert_info = (src_route, src_index, dest_vehicle, dest_index)

        self.operate_pure(src_route, src_index, dest_vehicle, dest_index, end_depot)

        self.last_improvement = self.old_objective - sln.solution_cost()

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        sln = self.sln

        src_route, src_index, dest_vehicle, dest_index = self._revert_info
        dest_route: Route = dest_vehicle.pop_route_at(dest_index)
        src_route.insert_customer(dest_route.path[0], src_index)

        # (Obsolete bug funny comment from when all_routes was an array):
        # The new route was most recently appended on the end. So we pop it! Like a balloon
        sln.all_routes.remove(dest_route)

class SwapCustomersAt(OperatorBL):
    _revert_info: tuple[Route, int, Route, int]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, route1: Route, index1, route2: Route, index2):
        if index1 > len(route1.path) - 1 or index2 > len(route2.path) - 1:
            return INVALID_OP

        if route1 == route2 and index1 == index2:
            return 0

        deltas = route1.cost_deltas_for_inter_route_customer_swap_at(index1, route2, index2)

        return self.compute_improvement_from_deltas(deltas)

    def _operate_pure_impl(self, route1: Route, index1, route2: Route, index2):
        if route1 == route2 and index1 == index2:
            return

        route1.swap_customers_with(index1, route2, index2)

    def _operate_impl(self, route1: Route, index1, route2: Route, index2):
        # Note: This body is nearly identical to the Reassign (move) version of this operator.
        if index1 > len(route1.path) - 1 or index2 > len(route2.path) - 1:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if route1 == route2 and index1 == index2:
            # No-op
            self._revert_info = None
            self.last_improvement = 0
            return

        self.last_improvement = self.compute_improvement(route1, index1, route2, index2)
        self._revert_info = (route1, index1, route2, index2)

        self.operate_pure(route1, index1, route2, index2)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        route1, index1, route2, index2 = self._revert_info

        # Reapplying the operator just swaps back
        self._operate_pure_impl(route1, index1, route2, index2)


def invert_permutation(permutation: Collection[int]) -> Collection[int]:
    # This stupid fast solution was found on Stack Overflow. Poster found a ~4us runtime for 1000 entries!
    inv = np.empty_like(permutation)
    inv[permutation] = np.arange(len(inv), dtype=inv.dtype)
    return inv

class PermuteRoute(OperatorBL):
    _revert_info: tuple[Route, Collection[int]]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def _operate_pure_impl(self, route: Route, permutation: Collection[int]):
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

    def compute_improvement(self, route: Route, new_end_depot: Depot):
        deltas = route.cost_deltas_if_end_depot_changes(new_end_depot)
        return self.compute_improvement_from_deltas(deltas)


    def _operate_pure_impl(self, route: Route, new_end_depot: Depot):
        route.set_end_depot(new_end_depot)


    def _operate_impl(self, route: Route, new_end_depot: Depot):
        old_end_depot = route.end_depot

        if route.is_empty:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if new_end_depot == old_end_depot:
            self.last_improvement = 0
            self._revert_info = None
            return

        self.last_improvement = self.compute_improvement(route, new_end_depot)

        self.operate_pure(route, new_end_depot)

        self._revert_info = (route, old_end_depot)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        (route, old_end_depot) = self._revert_info
        self.operate_pure(route, old_end_depot)


class DisposeOfEmptyRoutesBL(OperatorBL):
    # Disposes of the given routes. MUST check if they're empty before disposing!
    # If used correctly: This will never worsen the solution.
    # Disadvantage of making this separate: other operators won't get credit for emptying routes.
    # Advantage of making this separate: Simplifies logic and reversion for other operators,
    #   As they need not dispose of routes they empty, or revert them post-disposal.
    #_revert_info: tuple[list[Route]]

    def __init__(self, sln: FullSolution, dispose_only_trivial_routes = True):
        super().__init__(sln)

        # This property defines whether we dispose of routes that just move from one depot to another.
        self.dispose_only_trivial_routes = dispose_only_trivial_routes

    def compute_improvement(self, routes: list[Route]):
        if self.dispose_only_trivial_routes:
            return 0

        # WARNING: best to avoid calling this one directly.



        # Since pure depot moves are allowed: improvement computation becomes far heftier - possibly heftier than just
        #  recomputing the full objective in some cases, due to indexing nightmares, unless done really carefully.
        #  In this case, we opt to simply return the default option of operating, getting the improvement from the
        #  operator, then reverting.
        return super().compute_improvement(routes)

    def _operate_pure_impl(self, routes: list[Route]):
        self.sln.remove_routes(routes)

    def _operate_impl(self, routes: list[Route]):
        if len(routes) == 0:
            self._revert_info = None
            self.last_improvement = 0
            return

        sln = self.sln
        prev_obj = 0
        if not self.dispose_only_trivial_routes:
            # We just re-evaluate the objective for simplicity.
            prev_obj = sln.solution_cost()
        else:
            # No savings - trivial routes do not impact the objective.
            self.last_improvement = 0

        # This is the expensive part. Only relevant if we want to add in an undo stack. Must record before removing,
        #   Otherwise the vehicles will all be set to None!
        # TODO: CRITICAL ISSUE: Removal scheme is fragile to 1) replacement order (indices may change), and 2) route assignment (empty routes may become unassigned).
        #  SO: May need to evaluate this one completely differently.
        #  INSTEAD: We need a "route.insert_before(route2)" method with corresponding cost calc's.
        #  Really works just like vehicle.insert except you know the insert location by object reference instead of index.
        #  THEN: Revert info just pre-stores each removal route's next route at time of removal, then replace in reverse order.
        self._revert_info = ([(route, route.vehicle, route.vehicle.routes.index(route)) for route in routes],)

        self.operate_pure(routes)

        if not self.dispose_only_trivial_routes:
            self.last_improvement = -(sln.solution_cost() - prev_obj)


    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        reversions, = self._revert_info
        for route, vehicle, index in reversions:
            vehicle.insert_route(index, route)
            self.sln.all_routes.add(route)

class SplitRouteAt(OperatorBL):
    _revert_info: tuple[Route]|None
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, vehicle: Vehicle, route_id, split_index, intermediate_end_depot: Depot):
        # TODO: Implement the route splitting cost computations in the route or vehicle class instead of here!

        # To be splittable: route must have multiple customers (each customer to a different route).
        #   Index out of bounds: invalid. Index = 0 or split_index == path length => there is no customer to split.
        routes = vehicle.routes
        route = routes[route_id]
        path = route.path
        path_len = route.path_len
        if (route_id >= len(routes) or path_len <= 1 or
                0 == split_index or split_index >= path_len):
            # Invalid route cID
            return INVALID_OP

        deltas = route.cost_deltas_for_split_at(split_index, intermediate_end_depot)
        return self.compute_improvement_from_deltas(deltas)

    def _operate_pure_impl(self, vehicle: Vehicle, route_id: int, split_index: int, intermediate_end_depot: Depot):
        new_route = vehicle.split_route(route_id, split_index, intermediate_end_depot)
        self.sln.all_routes.add(new_route)

    def _operate_impl(self, vehicle: Vehicle, route_id: int, split_index: int, intermediate_end_depot: Depot):
        routes = vehicle.routes
        route = routes[route_id]
        path_len = len(route.path)
        if (route_id >= len(routes) or path_len <= 1 or
                0 == split_index or split_index >= path_len ):
            # Invalid route cID, route unsplittable, or split index doesn't meaningfully split the route
            self.last_improvement = INVALID_OP
            self._revert_info = None
            return

        self.last_improvement = self.compute_improvement(vehicle, route_id, split_index, intermediate_end_depot)
        self.operate_pure(vehicle, route_id, split_index, intermediate_end_depot)

        self._revert_info = (route,)

    def _revert_impl(self):
        assert self._revert_info is not None # This method should never be called if it's None: super().revert gatekeeps with a None check
        route, = self._revert_info

        next_route = route.next_route
        assert next_route is not None, "Invalid revert info: route does not have a next route right after a split!"

        # We added the new route to the end of all_routes - so we can simply pop.
        route.combine_with(next_route)
        self.sln.all_routes.remove(next_route)