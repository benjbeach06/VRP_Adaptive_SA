import SimAnn_VRP_BLOperators
from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Operators import *
import math
import time
import random
import bisect
import itertools
import heapq


def argmin(values):
    return min(range(len(values)), key=values.__getitem__)

class SimAnnVRPSolver:
    def __init__(self, sln: FullSolution):
        self.sln = sln
        self.operators: list[Operator] = []

        self.segment_length = 100
        self.reaction_factor = 0.2
        self.max_time = 120

        #self.cooling_factor = 0.93304 # Factor per 100 iterations
        self.cooling_factor = 1-1e-2 # Factor per iteration
        self.log_cooling_factor = math.log(self.cooling_factor, 2)
        self.temperature = 0.0
        self.log_temperature = -100.0

        # If the temp gets below low_temp_factor: reset to original temperature
        self.low_temp_factor = 1e-40

        self.curr_plateau_size = 0
        self.max_plateau_size = 10000
        self.plateau_reheat_factor = 2 # Factor of "reheat to this factor of plateau start"

        self.min_weight = 1e-6

        self.best_objective = float("inf")
        self.curr_objective = float("inf")
        self.index_in_segment = 0

        self.elapsed_time = 0.0
        self.num_reports_so_far = 0.0
        self.report_every = 1.0

        self.operators.append(RandomRouteReassignment(sln))
        self.operators.append(RandomCustomerReassignment(sln))
        self.operators.append(ReassignWorstCustomerOutOfRandomKToNewRoute(sln, k=10))
        self.operators.append(RandomCustomerSwap(sln))
        self.operators.append(CustomerBestOfkSwapInRandomRoute(sln))
        self.operators.append(RandomRoutePermutation(sln))
        self.operators.append(ChangeRandomEndDepot(sln))
        self.operators.append(DisposeOfEmptyRoutes(sln))
        #self.operators.append(SplitRandomRoute(sln))
        #self.operators.append(RandomCustomerReassignmentToNewRoute(sln))
        #self.operators.append(DisposeOfTrivialRoutes(sln))

        self.snapshots: list[tuple[float, FullSolution]] = []
        self.max_snapshots = 10

        self.num_complete_reheats = 0
        self.num_plateau_reheats = 0

    def update_weights(self):
        weights = [op.weight for op in self.operators]

        geom_mean_weight = math.exp(math.fsum([math.log(w) for w in weights]) / len(weights))
        total_moves = 0
        improving_moves = 0

        for op in self.operators:
            weight = op.weight
            (num_uses, num_improvements, score_sum) = op.get_stats()
            p = self.reaction_factor
            if num_uses > 0:
                op.weight =  (1 - p) * weight + p * (score_sum / num_uses)
                total_moves += 1
            else:
                op.weight = max(weight, (weight / geom_mean_weight) ** 0.997 * geom_mean_weight)

            if num_improvements > 0:
                improving_moves += 1

            op.reset_stats()

        if improving_moves == 0:
            self.curr_plateau_size += 1
            if self.curr_plateau_size >= self.max_plateau_size:
                self.curr_plateau_size = 0
                # Reheat factor = plateau_reheat_factor / (max_size^cooling factor). Undoes cooling during plateau, then reheats by the cooling factor.
                log_reheat_factor = math.log(self.plateau_reheat_factor, 2) - self.segment_length*self.max_plateau_size*self.log_cooling_factor
                self.log_temperature += log_reheat_factor
                self.num_plateau_reheats += 1

        self.temperature = 2**self.log_temperature


    def choose_operator(self):
        operators = self.operators
        cum_weights = list(itertools.accumulate(op.weight for op in operators))
        total = cum_weights[-1]

        r = random.random()*total

        index = bisect.bisect_left(cum_weights, r)
        return operators[index]

    # We design the solution, initialization, and operators so that at all stages, all customers show up in the src_route.
    def make_initial_solution(self):
        sln = self.sln
        depots = sln.depots
        customers = sln.customers

        vehicles = sln.vehicles
        all_routes = sln.all_routes

        customers_remaining = sln.customers.copy()

        def get_closest_depot(customer: Customer):
            return depots[argmin([customer.distance(depot) for depot in depots])]

        def get_closest_remaining_customer(customer: Customer) -> Customer:
            return customers_remaining[argmin([customer.distance(other_customer) for other_customer in customers_remaining])]

        def get_closest_customer_remaining(vehicle: Vehicle):
            depot = vehicle.final_depot
            return min(((customer, depot.distance(customer)) for customer in customers_remaining), key = lambda t : t[1])

        def get_closest_remaining_service():
            closest_customers = [(v,)+get_closest_customer_remaining(v) for (i,v) in enumerate(vehicles)]
            # Tuples at this point have values (vehicle, customer, distance)
            return min(closest_customers, key = lambda kvp: kvp[2])

        def add_next_route():
            (vehicle, customer1, _) = get_closest_remaining_service()
            customers_remaining.remove(customer1)
            route = Route([customer1], None)

            if customers_remaining:
                next_customer = get_closest_remaining_customer(customer1)
                capacity_so_far = customer1.demand
                next_capacity = next_customer.demand

                can_add_route = lambda : capacity_so_far + next_capacity <= vehicle.capacity

                while customers_remaining and can_add_route():
                    route.append_customer(next_customer)
                    capacity_so_far += next_customer.demand
                    customers_remaining.remove(next_customer)

                    if not customers_remaining:
                        break

                    next_customer = get_closest_remaining_customer(next_customer)
                    next_capacity = next_customer.demand

            # NOTE: Assumes that any vehicle has enough capacity to serve any single customer.
            route.set_end_depot(get_closest_depot(route.path[-1]))

            sln.add_route_to_vehicle(route, vehicle)

        while customers_remaining:
            add_next_route()

        self.best_objective = sln.solution_cost()
        self.curr_objective = self.best_objective

    def make_dumb_initial_solution(self):
        sln = self.sln
        new_route = Route([], end_depot=sln.depots[0])

        for customer in sln.customers:
            new_route.append_customer(customer)

        sln.add_route_to_vehicle(new_route, sln.vehicles[0])


        self.best_objective = sln.solution_cost()
        self.curr_objective = self.best_objective

    def solve(self):
        sln = self.sln
        initial_temp = 0.05 * self.best_objective
        self.temperature = initial_temp
        self.log_temperature = math.log(self.temperature, 2)

        start_time = time.time()
        elapsed_time = 0
        iterations = 0

        debug_level = 0

        while elapsed_time < self.max_time:
            self.log_temperature += self.log_cooling_factor
            iterations += 1
            if iterations % self.segment_length == 0:
                self.update_weights()

            op = self.choose_operator()

            if debug_level >= 1:
                preop_obj = self.sln.solution_cost()
            if debug_level >= 2:
                preop_costs = (self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(), self.sln.total_overload())
                preop_routes = list((list(route.path), route.start_depot, route.end_depot, route.vehicle.routes.index(route)) for route in self.sln.all_routes)

            op.operate()

            if debug_level >= 2:
                depot_breakdown = sln.depot_usage_breakdown()
                if any(depot.num_routes_starting_here != depot_breakdown[depot] for depot in sln.depots):
                    pass

                if any(customer.next_visit is None or customer.prev_visit is None for customer in self.sln.customers):
                    pass

                if any(vehicle.num_routes > 0 and (vehicle.routes[0].prev_route is not None or vehicle.routes[-1].next_route is not None)
                       for vehicle in sln.vehicles):
                    pass

                if any(route.next_route is not None and route.next_route.start_depot != route.end_depot
                       for route in sln.all_routes):
                    pass

                if not all((path_len := route.path_len) == 0 or
                           route.path[0].prev_node == route.start_depot and
                           route.path[path_len - 1].next_node == route.end_depot and
                           all((next_node := customer.next_node) == route.path[i+1] and
                               next_node.prev_visit == customer
                               for (i, customer) in enumerate(route.path[:-1]))
                           for route in sln.all_routes):
                    pass

            if debug_level >= 1:
                postop_obj = self.sln.solution_cost()
            if debug_level >= 2:
                postop_costs = (self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(), self.sln.total_overload())
                pstop_routes = list((list(route.path), route.start_depot, route.end_depot, route.vehicle.routes.index(route)) for route in self.sln.all_routes)

            improvement = op.last_improvement

            loglog_acceptance_threshold = -float('inf') if improvement >= 0 else math.log(-improvement, 2) - self.log_temperature

            accept = op.prev_operation_was_useful() and (improvement > 0 or math.log(-math.log(random.random()), 2) >= loglog_acceptance_threshold)

            if accept:
                """
                if improvement > 0:
                    print(preop_obj)
                    print(preop_costs)
                    operands = op.prev_operands
                    print(self.sln.solution_cost())
                    print((self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(), self.sln.num_overloaded_routes()))
                    op.revert()
                    print(self.sln.solution_cost())
                    print((self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(), self.sln.num_overloaded_routes()))
                    print("Hmmm")

                """
                if debug_level >= 1 and abs(improvement - (preop_obj - postop_obj)) >= 1e-6 or any(route.recompute_current_load() != route.current_load for route in self.sln.all_routes):
                    print("Accepted Move info:")
                    print(f"Move operator name: {type(op).__name__}")
                    print(f"Computed Improvement: {improvement}")
                    print(f"SLN reported improvement: {preop_obj - postop_obj}")
                    print(f"Pre-op objective: {preop_obj}")

                    if debug_level >= 2:
                        print("Pre-op cost breakdown:" + str(preop_costs))
                    print(f"Current pre-op increment-based solver-reported objective:{self.curr_objective}")
                    print(f"Post-op objective:{postop_obj}")

                    if debug_level >= 2:
                        print(f"Post-op cost breakdown:{postop_costs}")

                    operands = op.prev_operands
                    op.revert()
                    rev_obj = sln.solution_cost()

                    (improvement_recomp, operated) = op.base_operator.compute_improvement(*operands)
                    op.re_operate()

                    print()

                if improvement < 0 and self.curr_objective <= self.best_objective + 1e-12:
                    # Error-safe comparison of current and best objectives - relative error as abs/ave
                    # If we're disimproving from our running global optimum: take a snapshot.
                    op.revert() # To get back to the global minimum

                    self.take_sln_snapshot()

                    op.re_operate() # Return to the disimproved solution

                op.update_stats()

                self.curr_objective -= improvement
                self.best_objective = min(self.best_objective, self.curr_objective)
            else:
                """
                print("Rejection info:")
                print(improvement)
                print(self.curr_objective)
                print(preop_obj)
                print(preop_costs)
                print(self.sln.solution_cost())
                print((self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(),
                       self.sln.num_overloaded_routes()))
                """

                op.revert()


                if debug_level >= 2:
                    depot_breakdown = sln.depot_usage_breakdown()
                    if any(depot.num_routes_starting_here != depot_breakdown[depot] for depot in sln.depots):
                        pass

                    if any(customer.next_visit is None or customer.prev_visit is None for customer in self.sln.customers):
                        pass

                    if any(vehicle.num_routes > 0 and (
                            vehicle.routes[0].prev_route is not None or vehicle.routes[-1].next_route is not None) for vehicle in sln.vehicles):
                        pass

                    if any(route.next_route is not None and route.next_route.start_depot != route.end_depot
                           for route in sln.all_routes):
                        pass

                    if not all((path_len := route.path_len) == 0 or
                               route.path[0].prev_node == route.start_depot and
                               route.path[path_len - 1].next_node == route.end_depot and
                               all((next_node := customer.next_node) == route.path[i + 1] and
                                   next_node.prev_visit == customer
                                   for (i, customer) in enumerate(route.path[:-1]))
                               for route in sln.all_routes):
                        pass


                if debug_level >= 1 and abs(self.sln.solution_cost() - preop_obj) > 1e-6:
                    operands = op.prev_operands
                    print("Rejected Move info:")
                    print(f"Move operator name: {type(op).__name__}")
                    print(f"Computed Improvement: {improvement}")
                    print(f"SLN reported improvement: {preop_obj - postop_obj}")
                    print(f"Pre-op objective: {preop_obj}")

                    if debug_level >= 2:
                        print("Pre-op cost breakdown:" + str(preop_costs))

                    print(f"Current pre-op increment-based solver-reported objective:{self.curr_objective}")
                    print(f"Post-op objective:{postop_obj}")

                    if debug_level >= 2:
                        print(f"Post-op cost breakdown:{postop_costs}")
                    print(f"Reverted objective:{self.sln.solution_cost()}")

                    if debug_level >= 2:
                        print(f"Reverted cost breakdown:" + str((self.sln.total_path_len(), self.sln.depots_used(), self.sln.vehicles_used(), self.sln.total_overload())))
                        rev_routes = list((list(route.path), route.start_depot, route.end_depot, route.vehicle.routes.index(route)) for route in self.sln.all_routes)
                    print()

            if len(self.snapshots) > 2*self.max_snapshots:
                self.pare_snapshots_to_top_k(self.max_snapshots)

            curr_time = time.time()
            elapsed_time = curr_time - start_time

            """
            if self.temperature < self.low_temp_factor:
                
                self.temperature = initial_temp
                self.curr_plateau_size = 0

                self.num_complete_reheats += 1
            """

            if elapsed_time > self.report_every * self.num_reports_so_far:
                self.num_reports_so_far += 1
                print(f"Elapsed time: {elapsed_time:.2f} seconds, Best objective: {self.best_objective:.2f}, Current objective: {self.curr_objective:.2f}")
                print(f"Log2 Temperature: {self.log_temperature:.2f}, Complete reheats: {self.num_complete_reheats}, Plateau reheats: {self.num_plateau_reheats}, Iterations: {iterations}")

                print("op weights:" + str([(type(op).__name__, math.log(op.weight, 10)) for op in self.operators]))

        self.num_reports_so_far += 1
        print(f"Elapsed time: {elapsed_time:.2f} seconds, Best objective: {self.best_objective:.2f}, Current objective: {self.curr_objective:.2f}")
        print(f"Log2 Temperature: {self.log_temperature:.2f}, Complete reheats: {self.num_complete_reheats}, Iterations: {iterations}")

        for op in self.operators:
            op.report_stats()

        self.take_sln_snapshot()
        self.pare_snapshots_to_top_k(self.max_snapshots)

    def take_sln_snapshot(self):
        self.snapshots.append(self.sln.take_snapshot())

    def pare_snapshots_to_top_k(self, k):
        # Pares and sorts snapshots
        self.snapshots = heapq.nsmallest(k, self.snapshots, key=lambda x: x[0])

    def get_best_snapshot(self):
        return self.snapshots[0]

