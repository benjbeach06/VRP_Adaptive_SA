import time
from SimAnn_VRP_BLOperators import *
import random
import itertools
import bisect
import math

### Commented operators for reference. No need to reimplement ###
# Permute route with permutation array: route.permute(permutation)
# Permute subset of route: route.subpermute(permutation)

class OperatorStats:
    def __init__(self):
        self.uses = 0
        self.score_sum = 0
        self.improvements = 0

    def record_use(self, score):
        if score > 0:
            self.improvements += 1
        self.uses += 1
        self.score_sum += max(0,score)

    def reset(self):
        self.uses = 0
        self.improvements = 0
        self.score_sum = 0

def pick_random_vehicle_and_route_index(sln):
    vehicles = sln.vehicles

    if len(vehicles) == 0 or all(len(v.routes) == 0 for v in vehicles):
        raise ValueError("No routes to pick from")

    """
    Uniformly pick one (vehicle, route_index) among all routes in sln.

    We build a cumulative‐sum array of route counts [r0, r0+r1, r0+r1+r2, ...],
    where ri = len(vehicle_i.routes). Then pick a random integer R in [0, total-1],
    find the vehicle split_index via bisect, and subtract to get route_index.
    """
    # 1) Build the cumulative sums array: of route counts per vehicle
    #   e.g. len(v) = [3, 0, 5, 2]  → cum = [3, 3, 8, 10]
    cum_counts = list(itertools.accumulate(len(v.routes) for v in vehicles))  # e.g. [3, 0, 5, 2]

    total_routes = cum_counts[-1]

    # 2) Draw a random integer in [1, total_routes]. (The cumsum elements only work for 1-indexed arrays - so we
    #   subtract 1 from the resulting route index at the end.
    if total_routes == 1:
        R = 1
    else:
        R = random.randrange(1, total_routes)

    # 3) Find the vehicle split_index: the smallest i such that cum_counts[i] > R
    #    Note: bisect_left must be used to avoid picking an empty vehicle
    #    For example: In the previous example, vehicle 0 and 1 have the same len cumsum, but vehicle 1 is empty.
    vehicle_idx = bisect.bisect_left(cum_counts, R)
    R -= 1

    # 4) Compute the route’s local split_index within that vehicle:
    #    If vehicle_idx == 0, then route_idx = R: split_index in list = split_index in vehicle
    #    Otherwise route_idx = R - cum_counts[vehicle_idx-1] :
    #    (split_index within vehicle = overall split_index - routes before current vehicle)
    if vehicle_idx == 0:
        route_idx = R
    else:
        route_idx = R - cum_counts[vehicle_idx - 1]

    vehicle = vehicles[vehicle_idx]

    return vehicle, route_idx

class Operator(ABC):
    """
    Base for all in‐place, argument‐free operators.
    Subclasses only need to override _operate_impl() and _revert_impl().
    Operate() measures elapsed time and stores revert_info + improvement.
    """

    def __init__(self, sln: FullSolution, base_operator: OperatorBL):
        self.sln = sln
        self.base_operator = base_operator
        self.stats = OperatorStats()

        # Adaptive‐weight bookkeeping
        self.weight = 1.0
        self.last_elapsed = 0.0
        self.last_improvement = 0.0

        self.num_useless_calls = 0
        self.total_useless_call_time = 0
        self.mean_useless_call_time = 0

        self.num_useful_calls = 0
        self.total_useful_call_time = 0
        self.mean_useful_call_time = 0

        self.num_improving_calls = 0
        self.total_improving_improvement = 0
        self.mean_improving_improvement = 0
        self.total_improving_call_time = 0
        self.mean_improving_call_time = 0

        self.num_degrading_calls = 0
        self.total_degrading_degradation = 0
        self.mean_degrading_degradation = 0
        self.total_degrading_call_time = 0
        self.mean_degrading_call_time = 0

        self.num_neutral_calls = 0
        self.total_neutral_call_time = 0
        self.mean_neutral_call_time = 0

        # Revert method. Just calls op_BL's revert method.
        self.revert = self.base_operator.revert

        self.prev_operands = None

        """
            Subclass __init__ methods must choose its own OperatorBL class and pass it in here.
        """

    def update_reporting_stats(self):
        elapsed = self.last_elapsed
        improvement = self.last_improvement
        if self.prev_operation_was_useful():
            self.num_useful_calls += 1
            self.total_useful_call_time += elapsed
            self.mean_useful_call_time = self.total_useful_call_time / self.num_useful_calls

            eps = 1e-9
            if improvement > eps:
                self.num_improving_calls += 1
                self.total_improving_improvement += improvement
                self.mean_improving_improvement = self.total_improving_improvement / self.num_improving_calls
                self.total_improving_call_time += elapsed
                self.mean_improving_call_time = self.total_improving_call_time / self.num_improving_calls
            elif improvement < -eps:
                self.num_degrading_calls += 1
                self.total_degrading_degradation -= improvement
                self.mean_degrading_degradation = self.total_degrading_degradation / self.num_degrading_calls
                self.total_degrading_call_time += elapsed
                self.mean_degrading_call_time = self.total_degrading_call_time / self.num_degrading_calls
            else:
                self.num_neutral_calls += 1
                self.total_neutral_call_time += elapsed
                self.mean_neutral_call_time = self.total_neutral_call_time / self.num_neutral_calls

        else:
            self.num_useless_calls += 1
            self.total_useless_call_time += elapsed
            self.mean_useless_call_time = elapsed / self.num_useless_calls


    def report_stats(self):
        print(f"Stats for operator {type(self).__name__}: \n"
              f"LogWeight: {math.log(self.weight, 10)}, Total calls: {self.num_useful_calls + self.num_useless_calls}, Num useful calls: {self.num_useful_calls}, Useful call time: {self.total_useful_call_time}s, Mean useful call time:{self.mean_useful_call_time*1e6}us\n"
              f"Num improving calls: {self.num_improving_calls}, Mean improvement: {self.mean_improving_improvement}, Mean improving call time: {self.mean_improving_call_time*1e6}us\n"
              f"Num degrading calls: {self.num_degrading_calls}, Mean degradation: {self.mean_degrading_degradation}, Mean degrading call time: {self.mean_degrading_call_time*1e6}us\n" )



    def operate(self):
        """
        Wrapper that calls _operate_impl, measures elapsed time,
        and stores revert_info + improvement. Returns revert_info.
        """
        t0 = time.time()
        operands = self._operand_selection_impl()
        self.prev_operands = operands
        self.base_operator.operate(*operands)
        elapsed = time.time() - t0

        # Save for SA to inspect and possibly revert
        self.last_elapsed = elapsed
        self.last_improvement = self.base_operator.last_improvement

        self.update_reporting_stats()

    def re_operate(self):
        operands = self.prev_operands
        self.base_operator.operate(*operands)

    def re_operate_with_stats(self):

        t0 = time.time()
        operands = self.prev_operands
        self.prev_operands = operands
        self.base_operator.operate(*operands)
        elapsed = time.time() - t0

        # Save for SA to inspect and possibly revert
        self.last_elapsed = elapsed
        self.last_improvement = self.base_operator.last_improvement

        self.update_reporting_stats()

    def prev_operation_was_useful(self):
        return self.base_operator.prev_operation_was_useful()

    def update_stats(self):
        last_improvement = self.last_improvement
        last_elapsed = self.last_elapsed

        if not self.prev_operation_was_useful():
            self.stats.record_use(0)
            return

        eps = 1e-9
        sign = -1 if last_improvement < 0 else 1
        score = max(0, sign * (abs(last_improvement) ** 1.5) / max(last_elapsed, eps))
        self.stats.record_use(score)

    def get_stats(self):
        stats = self.stats
        return stats.uses, stats.improvements, stats.score_sum

    def reset_stats(self):
        self.stats.reset()

    @abstractmethod
    def _operand_selection_impl(self):
        """
        Subclasses only need to choose operands via some method, and return them
        """
        pass

class RandomRouteReassignment(Operator):
    def __init__(self, sln: FullSolution):
        use_reassign_at = (len(sln.vehicles) < sln.num_routes_lb/len(sln.vehicles)*2)

        if use_reassign_at:
            base_operator = ReassignRouteAt(sln)
        else:
            base_operator = ReassignRoute(sln)

        super().__init__(sln, base_operator)

        self.use_reassign_at = use_reassign_at

    def _operand_selection_impl(self):
        # If operator is ReassignRoute, do the first version.
        if self.use_reassign_at:
            return self.pick_vehicles_and_route_indices()
        else:
            return self.pick_route_and_dest_info()

    def pick_route_and_dest_info(self):
        sln = self.sln

        route = random.choice(sln.all_routes)
        vehicle = random.choice(sln.vehicles)
        insert_index = random.randint(0, len(vehicle.routes))

        return route, vehicle, insert_index

    def pick_vehicles_and_route_indices(self):
        sln = self.sln
        vehicles = sln.vehicles

        if len(vehicles) == 0 or all(len(v.routes) == 0 for v in vehicles):
            raise ValueError("No routes to pick from")

        (src_vehicle, src_index) = pick_random_vehicle_and_route_index(sln)

        dest_vehicle = random.choice(sln.vehicles)
        dest_index = random.randint(0, len(dest_vehicle.routes))

        return src_vehicle, src_index, dest_vehicle, dest_index

class RandomCustomerReassignment(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        #NOTE: src_route could be empty. We allow this possibility here, expecting operator to fail gracefully.
        retries = 100
        tries = 0
        valid = False
        src_route = None
        while not valid and tries < retries:
            src_route = random.choice(sln.all_routes)
            valid = len(src_route.path) >= 1

        if not valid:
            # Note: src_route is still an empty route.
            return src_route, 0, src_route, 0

        src_index = random.randint(0, len(src_route.path)-1)
        dest_route = random.choice(sln.all_routes)
        dest_index = random.randint(0, len(dest_route.path))

        return src_route, src_index, dest_route, dest_index

class RandomCustomerReassignmentToNewRoute(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerToNewRouteAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        src_route = random.choice(sln.all_routes)
        if len(src_route.path) == 0:
            return src_route, 0, sln.vehicles[0], 0, sln.depots[0]

        customer_id = random.randint(0, len(src_route.path) - 1)

        dest_vehicle = random.choice(sln.vehicles)
        dest_index = random.randint(0, len(dest_vehicle.routes))
        depot = random.choice(sln.depots)

        return src_route, customer_id, dest_vehicle, dest_index, depot

class ReassignWorstCustomerOutOfRandomKToNewRoute(Operator):
    def __init__(self, sln: FullSolution, k):
        super().__init__(sln, ReassignCustomerToNewRouteAt(sln))
        self.k = k

    def _operand_selection_impl(self):
        sln = self.sln

        route = None
        customer_id = -1
        worst_travel = -float('inf')

        for i in range(0, self.k):
            src_route = random.choice(sln.all_routes)
            if len(src_route.path) == 0:
                continue

            src_customer_id = random.randint(0, len(src_route.path) - 1)

            prev_node = src_route.start_depot if src_customer_id == 0 else src_route.path[src_customer_id-1]
            customer = src_route.path[src_customer_id]
            next_node = src_route.end_depot if src_customer_id == len(src_route.path) - 1\
                else src_route.path[src_customer_id+1]

            distance = prev_node.distance(customer) + customer.distance(next_node)
            if distance > worst_travel:
                worst_travel = distance
                route = src_route
                customer_id = src_customer_id

        if route is None:
            return sln.all_routes[0], -1, sln.vehicles[0], -1, sln.depots[0]

        dest_vehicle = random.choice(sln.vehicles)
        dest_index = random.randint(0, len(dest_vehicle.routes))
        depot = random.choice(sln.depots)

        return route, customer_id, dest_vehicle, dest_index, depot


class RandomCustomerSwap(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomersAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        #NOTE: It's worse in this case than in the random reassignment case if the customers choices are invalid.
        route1 = random.choice(sln.all_routes)

        if len(route1.path) == 0:
            return route1, 0, route1, 0

        index1 = random.randint(0, len(route1.path)-1)
        route2 = random.choice(sln.all_routes)

        if len(route2.path) == 0:
            return route1, 0, route1, 0
        index2 = random.randint(0, len(route2.path)-1)

        return route1, index1, route2, index2

class CustomerBestOfkSwapInRandomRoute(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomersAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln
        route = random.choice(sln.all_routes)
        path = route.path
        path_len = len(path)

        if path_len <= 1:
            return route, 0, route, 0

        (index1, index2, _) = max(((index1, index2, self.base_operator.compute_improvement(route, index1, route, index2))
                                   for index1 in range(0, path_len) for index2 in range(0, path_len) if index1 < index2), key = lambda tp: tp[2])

        return route, index1, route, index2


class RandomRoutePermutation(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, PermuteRoute(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = random.choice(sln.all_routes)

        permutation = list(range(len(route.path)))

        if len(route.path) <= 1:
            return route, permutation

        random.shuffle(permutation)

        return route, permutation

class ChangeRandomEndDepot(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ChangeEndDepot(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = random.choice(sln.all_routes)
        depot = random.choice(sln.depots)

        return route, depot

class DisposeOfTrivialRoutes(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = True))

    def _operand_selection_impl(self):
        # Will dispose of all routes that do absolutely nothing: no customers served, end where they started.
        return [route for route in self.sln.all_routes if route.should_dispose()],

class DisposeOfEmptyRoutes(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = False))

    def _operand_selection_impl(self):
        # Will dispose of all routes that can be disposed: they serve no customers, but may do a depot-to-depot move.
        return [route for route in self.sln.all_routes if route.can_dispose()],

class SplitRandomRoute(Operator):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SplitRouteAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        (vehicle, route_id) = pick_random_vehicle_and_route_index(sln)
        route = vehicle.routes[route_id]
        path = route.path

        if len(path) <= 1:
            return vehicle, route_id, 0, sln.depots[0] # should gracefully report as a no-op instead of an invalid operation

        depot = random.choice(sln.depots)
        split_index = random.randint(1, len(path) - 1)

        return vehicle, route_id, split_index, depot