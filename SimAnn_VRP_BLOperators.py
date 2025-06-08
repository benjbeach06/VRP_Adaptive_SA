from SimAnn_VRP_Core_Model import *
from abc import ABC, abstractmethod
import numpy as np

INVALID_OP = -float('inf')
class OperatorBL(ABC):
    # Base class for operator BL: performing operations of a given type and computing solution deltas.
    # Requires operand selection.
    def __init__(self, sln: FullSolution):
        self.sln = sln

        self.last_improvement = 0
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

    def compute_improvement(self, *args, **kwargs):
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
        Undo exactly what _operate_impl did, using the revert_info from last operate().
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

class ReassignRouteAt(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def _operate_pure_impl(self, route, vehicle, insertion_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        route.vehicle.pop_route(route)
        vehicle.insert_route(route, insertion_index)

    def _operate_impl(self, src_vehicle, src_index, dest_vehicle, dest_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.

        sln = self.sln

        route = src_vehicle.routes[src_index]
        vehicle = dest_vehicle
        insertion_index = dest_index

        if src_vehicle == dest_vehicle and dest_index >= len(dest_vehicle.routes):
            # Cannot move past the end of the current route! Invalid operation
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if src_vehicle == dest_vehicle and src_index == dest_index:
            # It's a no-op!
            self._revert_info = None
            self.last_improvement = 0.0
            return

        route_was_overloaded = route.is_overloaded()

        swap_is_adjacent = src_vehicle == dest_vehicle and abs(src_index - dest_index) == 1

        # Moving the route changes: this route's starting location, and any immediately subsequent route's starting location.
        #   This change in starting location only
        #   The number of active vehicles can also be changed - so we will account for this.

        next_src_route = None
        next_dest_route = None

        if swap_is_adjacent:
            # Adjacent move within one vehicle:
            #   only source route, destination route, and any single subsequent route are impacted.
            # Route order (and thus start location determination) will go from
            #   (prev)->one->other->(next_if_applicable) to (prev)->other->one->(next_if_applicable)

            max_index = max(src_index, dest_index)

            other_route = vehicle.routes[insertion_index]
            old_travel_distance = route.first_move_distance() + other_route.first_move_distance()

            if max_index <= len(vehicle.routes) - 2:
                old_travel_distance += vehicle.routes[max_index+1].first_move_distance()

            cost_delta = 0

            self._operate_pure_impl(route, vehicle, insertion_index)

            # Adjacent move: only source route, destination route, and any single subsequent route are impacted.
            new_travel_distance = route.first_move_distance() + other_route.first_move_distance()

            if max_index <= len(vehicle.routes) - 2:
                new_travel_distance += vehicle.routes[max_index + 1].first_move_distance()

        else:
            # Non-adjacent move, so source and destination start-location changes are independent.
            #   Must independently assess impact on routes surrounding both the source and destination,
            #       and respective vehicles.
            old_travel_distance = route.first_move_distance()

            if src_index <= len(src_vehicle.routes) - 2:
                next_src_route = src_vehicle.routes[src_index + 1]
                old_travel_distance += next_src_route.first_move_distance()
            if src_vehicle == dest_vehicle and src_index < dest_index <= len(dest_vehicle.routes) - 2:
                next_dest_route = dest_vehicle.routes[dest_index+1]
                old_travel_distance += next_dest_route.first_move_distance()
            elif dest_index <= len(dest_vehicle.routes) - 1:
                next_dest_route = dest_vehicle.routes[dest_index]
                old_travel_distance += next_dest_route.first_move_distance()

            src_will_be_deactivated = int(len(src_vehicle.routes) == 1) # Note: since route has vehicle src_vehicle, we have that this length is >=1.
            dest_will_be_activated = int(len(dest_vehicle.routes) == 0)

            cost_delta = sln.cost_per_vehicle*(dest_will_be_activated - src_will_be_deactivated)

            # Operate
            self._operate_pure_impl(route, vehicle, insertion_index)

            # Finish cost delta computation

            new_travel_distance = route.first_move_distance()
            if next_src_route is not None:
                new_travel_distance += next_src_route.first_move_distance()
            if next_dest_route is not None:
                new_travel_distance += next_dest_route.first_move_distance()

        route_is_overloaded = route.is_overloaded()
        overload_delta = sln.overload_penalty * (route_is_overloaded - route_was_overloaded)

        # A negative cost delta is a positive improvement.
        cost_delta += sln.unit_travel_cost * (new_travel_distance - old_travel_distance)
        cost_delta += overload_delta
        improvement = -cost_delta

        # Report and prep for reversion
        self.last_improvement = improvement
        self._revert_info = (route, src_vehicle, src_index)

    def _revert_impl(self):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        #   So: Reversion reassigns it back to its original vehicle and location split_index
        (route, src_vehicle, src_index) = self._revert_info
        self._operate_pure_impl(route, src_vehicle, src_index)

class ReassignRoute(OperatorBL):

    def __init__(self, sln: FullSolution):
        super().__init__(sln)

        self._reassign_route_at_operator = ReassignRouteAt(sln)

        self._operate_pure_impl = self._reassign_route_at_operator.operate_pure

    def _operate_pure_impl(self, route, vehicle, insertion_index):
        return self._reassign_route_at_operator.operate_pure(route, vehicle, insertion_index)

    def _operate_impl(self, route, vehicle, insertion_index):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.

        sln = self.sln
        dest_vehicle = vehicle
        dest_index = insertion_index
        src_vehicle = route.vehicle
        src_index = route.vehicle.routes.index(route)

        self._reassign_route_at_operator.operate(src_vehicle, src_index, dest_vehicle, dest_index)

        self.last_improvement = self._reassign_route_at_operator.last_improvement
        self._revert_info = self._reassign_route_at_operator._revert_info

    def _revert_impl(self):
        # Operation is: Reassign route to target vehicle at split_index insertion_index
        #   So: Reversion reassigns it back to its original vehicle and location split_index
        self._reassign_route_at_operator._revert_info = self._revert_info
        self._reassign_route_at_operator.revert() # Do it this way so that _reassign_route_at_operator also reverts its info


class ReassignCustomerAt(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index, dest_route: Route, dest_index):
        if src_index > len(src_route.path) - 1 or dest_index > len(dest_route.path) \
                or (src_route == dest_route and dest_index == len(dest_route.path)):
            # In the last case: you're moving within the same list - so the "last insert" is no longer valid.
            # Otherwise: can move to the end of a different route (to become the new last element), but not beyond it
            return INVALID_OP # Invalid operation

        customer = src_route.path[src_index]

        pop_delta = src_route.get_visit_pop_travel_delta(src_index)

        if src_route == dest_route and src_index == dest_index:
            return 0

        # Account for src/dest capacity overloading
        src_route_capacity = src_route.vehicle.capacity
        dest_route_capacity = dest_route.vehicle.capacity

        old_src_route_load = src_route.current_load
        new_src_route_load = src_route.current_load - customer.demand

        old_dest_route_load = dest_route.current_load
        new_dest_route_load = dest_route.current_load + customer.demand

        src_was_overloaded = old_src_route_load > src_route_capacity
        dest_was_overloaded = old_dest_route_load > dest_route_capacity

        src_is_overloaded = new_src_route_load > src_route_capacity
        dest_is_overloaded = new_dest_route_load > dest_route_capacity

        delta_cost_overload = self.sln.overload_penalty * (src_is_overloaded + dest_is_overloaded - src_was_overloaded - dest_was_overloaded)

        dest_vehicle_activated = dest_route.should_dispose() and not dest_route.vehicle.is_used
        src_vehicle_deactivated = len(src_route.path) == 1 and src_route.start_depot == src_route.end_depot \
                                  and src_route.vehicle.num_used() == 1

        # Quirk: Depot will still count as used (until route is disposed), but vehicle will count as unused.
        #   The route disposal operator will take care of depot now-unused savings.
        delta_cost_vehicle_usage = self.sln.cost_per_vehicle*(dest_vehicle_activated - src_vehicle_deactivated)

        # Now account for altered travel distances
        if src_route != dest_route or src_index >= dest_index + 2:
            # Different routes, or same routes popping from later. No weird list shifts to handle.
            insert_delta = dest_route.get_visit_insert_travel_delta(customer, dest_index)
        elif src_index <= dest_index - 2:
            # In this special case: the insertion is from src_index to a later point - insertion will be after dest_index
            insert_delta = dest_route.get_visit_insert_travel_delta(customer, dest_index+1)
        else:
            # In this case, index1 and index2 are adjacent. So the order (prev, min_id, max_id, next) turns to (prev, max, min, next).
            min_id = min(src_index, dest_index)
            max_id = max(src_index, dest_index)

            path = src_route.path
            path_len = len(src_route.path)

            prev_node = src_route.start_depot if (min_id == 0) else path[min_id - 1]
            node1 = path[min_id]
            node2 = path[max_id]
            next_node = src_route.end_depot if (max_id == path_len - 1) else path[max_id + 1]

            prev_distance = prev_node.distance(node1) + node1.distance(node2) + node2.distance(next_node)
            next_distance = prev_node.distance(node2) + node2.distance(node1) + node1.distance(next_node)

            pop_delta = 0
            insert_delta = next_distance - prev_distance

        delta_cost = self.sln.unit_travel_cost * (pop_delta + insert_delta) + delta_cost_overload + delta_cost_vehicle_usage

        return -delta_cost

    def _operate_pure_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        sln = self.sln

        if src_route == dest_route and src_index == dest_index:
            return

        customer = src_route.pop_visit_at(src_index)
        dest_route.insert_visit(customer, dest_index)

    def _operate_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        sln = self.sln

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
        src_route, src_index, dest_route, dest_index = self._revert_info
        #print(self.orig_data)
        #print(f"Post: src_route_len:{len(src_route.path)}, src_index:{src_index}, dest_route_len:{len(dest_route.path)}, dest_index:{dest_index}")
        self._operate_pure_impl(dest_route, dest_index, src_route, src_index)
        #print(f"Revt: src_route_len:{len(src_route.path)}, src_index:{src_index}, dest_route_len:{len(dest_route.path)}, dest_index:{dest_index}\n")

"""
TODO: Finish this one. It's tougher than the customer-move operators because it also involves adding in a route
    to an existing vehicle - and thus requires more involved computations. Route splitting is easier to implement.
class ReassignCustomerToNewRouteAt(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, src_route: Route, src_index, dest_vehicle: Vehicle, dest_index, end_depot):
        if src_index > len(src_route.path) - 1:
            return INVALID_OP # Invalid operation
        
        customer = src_route.path[src_index]
        route = Route(path=[customer], end_depot=end_depot)

        pop_delta = src_route.get_visit_pop_travel_delta(src_index)

        if src_route == dest_route and src_index == dest_index:
            return 0

        if src_route != dest_route or src_index >= dest_index + 2:
            insert_delta = dest_route.get_visit_insert_travel_delta(customer, dest_index)
        elif src_index <= dest_index - 2:
            insert_delta = src_route.get_visit_insert_travel_delta(customer, dest_index)
        else:
            # In this case, index1 and index2 are adjacent. So the order (prev, min_id, max_id, next) turns to (prev, max, min, next).
            min_id = min(src_index, dest_index)
            max_id = max(src_index, dest_index)

            path = src_route.path
            path_len = len(src_route.path)

            prev_node = src_route.start_depot if (min_id == 0) else path[min_id - 1]
            node1 = path[min_id]
            node2 = path[max_id]
            next_node = src_route.end_depot if (max_id == path_len - 1) else path[max_id + 1]

            prev_distance = prev_node.distance(node1) + node1.distance(node2) + node2.distance(next_node)
            next_distance = prev_node.distance(node2) + node2.distance(node1) + node2.distance(next_node)

            insert_delta = next_distance - prev_distance

        delta_cost = self.sln.unit_travel_cost * (pop_delta + insert_delta)

        return -delta_cost

    def _operate_pure_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        sln = self.sln

        if src_route == dest_route and src_index == dest_index:
            return

        customer = src_route.pop_visit_at(src_index)
        dest_route.insert_visit(customer, dest_index)

    def _operate_impl(self, src_route: Route, src_index, dest_route: Route, dest_index):
        sln = self.sln

        if src_index > len(src_route.path) - 1:
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
        src_route, src_index, dest_route, dest_index = self._revert_info

        self._operate_pure_impl(dest_route, dest_index, src_route, src_index)
"""

class SwapCustomersAt(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, route1: Route, index1, route2: Route, index2):
        if index1 > len(route1.path) - 1 or index2 > len(route2.path) - 1:
            return INVALID_OP

        if route1 == route2 and index1 == index2:
            return 0

        node_before_1 = route1.start_depot if (index1 == 0) else route1.path[index1-1]
        customer1 = route1.path[index1]
        node_after_1 = route1.end_depot if (index1 == len(route1.path)-1) else route1.path[index1+1]

        node_before_2 = route2.start_depot if (index2 == 0) else route2.path[index2-1]
        customer2 = route2.path[index2]
        node_after_2 = route2.end_depot if (index2 == len(route2.path)-1) else route2.path[index2+1]


        # Account for src/dest capacity overloading
        route1_capacity = route1.vehicle.capacity
        route2_capacity = route2.vehicle.capacity

        old_route1_load = route1.current_load
        new_route1_load = route1.current_load - customer1.demand + customer2.demand

        old_route2_load = route2.current_load
        new_route2_load = route2.current_load + customer1.demand - customer2.demand

        route1_was_overloaded = old_route1_load > route1_capacity
        route2_was_overloaded = old_route2_load > route2_capacity

        route1_is_overloaded = new_route1_load > route1_capacity
        route2_is_overloaded = new_route2_load > route2_capacity

        delta_cost_overload = self.sln.overload_penalty * (
                    route1_is_overloaded + route2_is_overloaded - route1_was_overloaded - route2_was_overloaded)

        if route1 != route2 or abs(index1 - index2) >= 2:
            # Non-adjacent case.
            old_len_1 = node_before_1.distance(customer1) + customer1.distance(node_after_1)
            old_len_2 = node_before_2.distance(customer2) + customer2.distance(node_after_2)

            new_len_1 = node_before_1.distance(customer2) + customer2.distance(node_after_1)
            new_len_2 = node_before_2.distance(customer1) + customer1.distance(node_after_2)

            travel_delta = (new_len_1 + new_len_2) - (old_len_1 + old_len_2)
        else:
            # In this case, index1 and index2 are adjacent within the same rout. So the order (prev, first, second, next) turns to (prev, second, first, next).
            if index1 < index2:
                prev_node = node_before_1
                first_node = customer1
                second_node = customer2
                next_node = node_after_2
            else:
                prev_node = node_before_2
                first_node = customer2
                second_node = customer1
                next_node = node_after_1

            old_distance = prev_node.distance(first_node) + first_node.distance(second_node) + second_node.distance(next_node)
            new_distance = prev_node.distance(second_node) + second_node.distance(first_node) + first_node.distance(next_node)

            travel_delta = new_distance - old_distance

        return -self.sln.unit_travel_cost * travel_delta - delta_cost_overload

    def _operate_pure_impl(self, route1: Route, index1, route2: Route, index2):
        if route1 == route2 and index1 == index2:
            return

        route1.swap_visits_with(index1, route2, index2)

    def _operate_impl(self, route1: Route, index1, route2: Route, index2):
        # Note: This body is nearly identical to the Reassign (move) version of this operator.
        if index1 > len(route1.path) - 1 or index2 > len(route2.path) - 1:
            self._revert_info = None
            self.last_improvement = INVALID_OP
            return

        if route1 == route2 and index1 == index2:
            self._revert_info = None
            self.last_improvement = 0
            return

        self.last_improvement = self.compute_improvement(route1, index1, route2, index2)
        self._revert_info = (route1, index1, route2, index2)

        self.operate_pure(route1, index1, route2, index2)

    def _revert_impl(self):
        route1, index1, route2, index2 = self._revert_info

        # Reapplying the operator just swaps back
        self._operate_pure_impl(route1, index1, route2, index2)


def invert_permutation(permutation):
    # This stupid fast solution was found on Stack Overflow. Poster found a ~4us runtime for 1000 entries!
    inv = np.empty_like(permutation)
    inv[permutation] = np.arange(len(inv), dtype=inv.dtype)
    return inv

class PermuteRoute(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def _operate_pure_impl(self, route, permutation):
        sln = self.sln
        route.permute(permutation)

    def _operate_impl(self, route, permutation):
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
        self._revert_info = (route, invert_permutation(permutation))

    def _revert_impl(self):
        route, inv_permutation = self._revert_info
        self.operate_pure(route, inv_permutation)


class ChangeEndDepot(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, vehicle: Vehicle, route_id, new_end_depot: Depot):
        sln = self.sln
        routes = vehicle.routes
        num_routes = len(routes)

        route = routes[route_id]
        path = route.path
        path_len = len(path)

        old_end_depot = route.end_depot

        if new_end_depot == old_end_depot:
            return 0

        prev_node = route.start_depot if (path_len == 0) else path[path_len - 1]

        old_distance = prev_node.distance(old_end_depot)
        new_distance = prev_node.distance(new_end_depot)

        if route_id <= num_routes - 2:
            # Then the starting location of the next route has changed. So: we fix it
            next_route = routes[route_id + 1]
            next_path = next_route.path
            next_path_len = len(next_path)

            next_node = next_route.end_depot if (next_path_len == 0) else next_path[0]

            old_distance += old_end_depot.distance(next_node)
            new_distance += new_end_depot.distance(next_node)

        delta_cost = new_distance - old_distance

        if new_end_depot.num_routes_starting_here == 0:
            delta_cost += sln.cost_per_depot
        if old_end_depot.num_routes_starting_here == 1:
            delta_cost -= sln.cost_per_depot

        return -delta_cost

    def _operate_pure_impl(self, vehicle: Vehicle, route_id, new_end_depot: Depot):
        route = vehicle.routes[route_id]
        new_end_depot.num_routes_starting_here += 1
        route.end_depot.num_routes_starting_here -= 1

        route.end_depot = new_end_depot

        if route_id <= vehicle.num_routes - 2:
            vehicle.routes[route_id+1].start_depot = new_end_depot

    def _operate_impl(self, vehicle: Vehicle, route_id, new_end_depot: Depot):
        route = vehicle.routes[route_id]

        old_end_depot = route.end_depot
        if new_end_depot == old_end_depot:
            self.last_improvement = 0
            self._revert_info = None
            return

        self.last_improvement = self.compute_improvement(vehicle, route_id, new_end_depot)

        self.operate_pure(vehicle, route_id, new_end_depot)

        self._revert_info = (vehicle, route_id, old_end_depot)

    def _revert_impl(self):
        (vehicle, route_id, old_end_depot) = self._revert_info
        self.operate_pure(vehicle, route_id, old_end_depot)



class DisposeOfEmptyRoutesBL(OperatorBL):
    # Disposes of the given routes. MUST check if they're empty before disposing!
    # If used correctly: This will never worsen the solution.
    # Disadvantage of making this separate: other operators won't get credit for emptying routes.
    # Advantage of making this separate: Simplifies logic and reversion for other operators,
    #   As they need not dispose of routes they empty, or revert them post-disposal.
    def __init__(self, sln: FullSolution, dispose_only_trivial_routes = True):
        super().__init__(sln)

        # This property defines whether we dispose of routes that just move from one depot to another.
        self.dispose_only_trivial_routes = dispose_only_trivial_routes

    def compute_improvement(self, routes: list[Route]):
        if self.dispose_only_trivial_routes:
            sln = self.sln
            depots = sln.depots

            route_reductions = {depot: 0 for depot in depots}
            for route in routes:
                route_reductions[route.start_depot] += 1

            depot_improvement = sln.cost_per_depot * sum(bool(depot.num_routes_starting_here == route_reductions[depot]) for depot in depots)

            return depot_improvement

        # If pure depot moves are allowed: improvement computation becomes far heftier - possibly heftier than just
        #  recomputing the full objective in some cases, due to indexing nightmares, unless done really carefully.
        #  In this case, we opt to simply return the default option of operating, getting the improvement from the
        #  operator, then reverting.
        return super().compute_improvement(routes)

    def _operate_pure_impl(self, routes: list[Route]):
        self.sln.remove_routes(routes)

    def _operate_impl(self, routes: list[Route]):
        sln = self.sln
        prev_obj = 0
        if not self.dispose_only_trivial_routes:
            # We just re-evaluate the objective for simplicity.
            prev_obj = sln.solution_cost()
        else:
            # Savings can be cheap to compute - so we compute them cheaply.
            self.last_improvement = self.compute_improvement(routes)

        # This is the expensive part. Only relevant if we want to add in an undo stack. Must record before removing,
        #   Otherwise the vehicles will all be set to None!
        self._revert_info = ([(route, route.vehicle, route.vehicle.routes.index(route)) for route in routes])

        self.operate_pure(routes)

        if not self.dispose_only_trivial_routes:
            self.last_improvement = -(sln.solution_cost() - prev_obj)


    def _revert_impl(self):
        reversions, = self._revert_info
        for route, vehicle, index in reversions:
            vehicle.insert_route(index, route)
            self.sln.all_routes.append(route)

class SplitRouteAt(OperatorBL):
    def __init__(self, sln: FullSolution):
        super().__init__(sln)

    def compute_improvement(self, vehicle: Vehicle, route_id, split_index, intermediate_end_depot: Depot):

        # To be splittable: route must have multiple customers (each customer to a different route).
        #   Index out of bounds: invalid. Index = 0 or split_index == path length => there is no customer to split.
        routes = vehicle.routes
        route = routes[route_id]
        path_len = len(route.path)
        if (route_id >= len(routes) or path_len <= 1 or
                0 == split_index or split_index >= path_len):
            # Invalid route id
            return INVALID_OP

        route = vehicle.routes[route_id]
        path = route.path
        path_len = len(path)
        if split_index > path_len:
            # No customer at that split_index!
            return INVALID_OP

        if split_index in {0, path_len} or path_len <= 1:
            return 0

        customer1 = path[split_index - 1]
        customer2 = path[split_index]

        old_distance = customer1.distance(customer2)
        new_distance = customer1.distance(intermediate_end_depot) + intermediate_end_depot.distance(customer2)

        delta_cost = self.sln.unit_travel_cost * (new_distance - old_distance)
        return -delta_cost

    def _operate_pure_impl(self, vehicle: Vehicle, route_id, split_index, intermediate_end_depot: Depot):
        new_route = vehicle.split_route(route_id, split_index, intermediate_end_depot)
        self.sln.all_routes.append(new_route)

    def _operate_impl(self, vehicle: Vehicle, route_id, split_index, intermediate_end_depot: Depot):
        routes = vehicle.routes
        route = routes[route_id]
        path_len = len(route.path)
        if (route_id >= len(routes) or path_len <= 1 or
                0 == split_index or split_index >= path_len ):
            # Invalid route id, route unsplittable, or split index doesn't meaningfully split the route
            self.last_improvement = INVALID_OP
            self._revert_info = None
            return

        self.last_improvement = self.compute_improvement(vehicle, route_id, split_index, intermediate_end_depot)
        self.operate_pure(vehicle, route_id, split_index, intermediate_end_depot)

        self._revert_info = (vehicle, route_id)

    def _revert_impl(self):
        vehicle, route_id = self._revert_info

        self.sln.all_routes.remove(vehicle.routes[route_id+1])
        vehicle.combine_routes_at(route_id, route_id+1)