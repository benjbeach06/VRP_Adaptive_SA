#from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Operators import *
import math
import time
import random
import bisect
import itertools
import heapq


def argmin(values):
    return min(range(len(values)), key=values.__getitem__)


# TODO(debug-tooling): improvements to the verification machinery, ordered by payoff. Each of
# these was reconstructed ad hoc while chasing the depot-usage / combine-linkage bug set, and
# would have found those bugs immediately (and at their true source) had it already existed.
#
# 1) Visit-linkage checks in _check_solution_invariants. It currently covers depot counts, the
#    vehicle route chain, successor start_depot agreement, and cached load -- but NOT the visit
#    doubly-linked list: last_visit.prev_visit is path[-1], path[-1].next_visit is last_visit,
#    first_visit.next_visit is path[0], and path[i].prev_visit is path[i-1] for all i. A
#    combine_with bug left last_visit.prev_visit pointing at the pre-merge last customer; it was
#    invisible here and only surfaced later as a wrong ChangeEndDepot delta in a different
#    operator. This is the single highest-value addition.
#
# 2) Structured debug findings instead of formatted print() strings. Emit records
#    (operator, check_kind, predicted, actual, operands) where check_kind is one of
#    delta_mismatch / revert_not_restored / invariant_violated, and aggregate on check_kind.
#    Free-form strings are easy to bucket wrongly: grouping on the text before the first ':'
#    silently merges "revert() did not restore objective" into the delta-mismatch bucket, which
#    sent a debugging pass after the wrong bug class for several rounds.
#
# 3) Per-term delta reporting as its own debug level. Compare move.deltas against a diff of two
#    objective_terms() calls field by field and report WHICH term is wrong. "improvement off by
#    27.78" is a search; "travel_distance wrong, other four exact" is a location. This is what
#    localized both the intra-route overload bug and the combine-with-next travel bug.
#
# 4) Iteration-count termination alongside max_time. Wall-clock termination makes runs
#    non-reproducible: an instrumented run executes a different number of iterations than a clean
#    one, so it explores a different trajectory and may not reproduce the bug at all. A fixed
#    iteration budget makes runs comparable, bisectable, and deterministic given a seed.
#
# 5) A per-operator property harness in the repo (not scratch scripts). For each BL operator, on
#    random legal operands: assert evaluate() is pure (objective_terms unchanged), assert
#    per-term deltas match ground truth after apply, assert invariants hold, then revert and
#    assert an exact structural+cost fingerprint round-trip. Revert-exactness is the check that
#    caught CombineRoutes failing to restore route1's end depot -- a bug no accepted-move check
#    can see, since it only manifests on the apply->revert path.

class SimAnnVRPSolver:
    def __init__(self, sln: FullSolution, max_time: int = 120):
        self.sln = sln
        self.operators: list[Operator] = []

        self.segment_length = 100
        self.reaction_factor = 0.2
        self.max_time = max_time

        #self.cooling_factor = 0.93304 # Factor per 100 iterations
        self.cooling_factor = 1-1e-2 # Factor per iteration
        self.log_cooling_factor = math.log2(self.cooling_factor)
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
        self.operators.append(RandomCustomerSwap(sln))
        self.operators.append(CustomerBestOfkSwapInRandomRoute(sln))
        self.operators.append(RandomRoutePermutation(sln))
        self.operators.append(ChangeRandomEndDepot(sln))
        self.operators.append(DisposeOfEmptyRoutes(sln))
        self.operators.append(SplitRandomRoute(sln))
        self.operators.append(DisposeOfTrivialRoutes(sln))
        self.operators.append(CombineRandomRoutes(sln))
        # TODO(known-bug): ReassignCustomerToNewRouteBefore's pricing is wrong for the throwaway
        # new-route case (it prices a "swap" from a VirtualDepot placeholder start, but a brand
        # new route never had a real old start to swap from). Needs a purpose-built Core delta
        # function rather than reusing cost_deltas_if_inserted_before. Disabled until fixed.
        # self.operators.append(ReassignWorstCustomerOutOfRandomKToNewRoute(sln, k=10))
        # self.operators.append(RandomCustomerReassignmentToNewRoute(sln))

        self.snapshots: list[tuple[float, FullSolution]] = []
        self.max_snapshots = 10

        self.num_complete_reheats = 0
        self.num_plateau_reheats = 0

        # Every this-many iterations, dispose of any empty routes outright rather than waiting
        # for weighted operator selection to stochastically pick DisposeOfEmptyRoutes -- since
        # all objective coefficients are non-negative, this is never a net loss.
        self.empty_route_cleanup_interval = 100
        self._dispose_bl = DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes=False)

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

        customers_remaining = customers.copy()

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
            # End depot isn't decided until the route is full; DEFAULT_DEPOT is a harmless
            # placeholder always replaced by set_end_depot below before the route is used.
            route = Route([CustomerVisit(customer1)], DEFAULT_DEPOT)

            if customers_remaining:
                next_customer = get_closest_remaining_customer(customer1)
                capacity_so_far = customer1.demand
                next_capacity = next_customer.demand

                can_add_route = lambda : capacity_so_far + next_capacity <= vehicle.capacity

                while customers_remaining and can_add_route():
                    route.append_customer(CustomerVisit(next_customer))
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

    def _cleanup_empty_routes(self):
        # Unconditional maintenance: since every objective coefficient is non-negative, removing
        # an empty route's travel/depot footprint is never a net loss. Called directly rather than
        # through weighted operator selection.
        empty_routes = RouteSet(r for r in self.sln.all_routes if r.is_empty)
        if not empty_routes:
            return
        move = self._dispose_bl.evaluate(empty_routes)
        if move.is_actionable:
            self._dispose_bl.apply(move)
            self._dispose_bl.commit()
            self.curr_objective -= move.improvement
            self.best_objective = min(self.best_objective, self.curr_objective)

    @staticmethod
    def _check_solution_invariants(sln: FullSolution) -> list[str]:
        # debug_level >= 2 structural checks, lifted from the old inline blocks and adapted to
        # walk prev_route/next_route chains instead of RouteSet.index (which doesn't exist).
        problems = []

        depot_breakdown = sln.depot_usage_breakdown()
        if any(depot_breakdown[depot] != sln.depot_num_uses[depot] for depot in sln.depots):
            problems.append("depot usage breakdown disagrees with depot_num_uses")

        # sln.customers holds the raw problem-data Customer objects, not the per-route
        # CustomerVisit wrappers that carry linkage -- check the actual visits in each route.
        if any(visit.next_visit is None or visit.prev_visit is None
               for route in sln.all_routes for visit in route.path):
            problems.append("a customer visit has an unlinked visit")

        for vehicle in sln.vehicles:
            node = vehicle.first_route.next_route   # first_route itself is the FirstRoute sentinel, not a Route
            seen = 0
            while node is not vehicle.last_route:
                if not isinstance(node, Route):
                    problems.append(f"vehicle {vehicle.vID} chain broke before reaching last_route")
                    break
                seen += 1
                node = node.next_route
            if seen != vehicle.num_routes:
                problems.append(f"vehicle {vehicle.vID} chain length {seen} != num_routes {vehicle.num_routes}")

        if any(isinstance(route.next_route, Route) and route.next_route.start_depot != route.end_depot
               for route in sln.all_routes):
            problems.append("a route's successor start_depot doesn't match its own end_depot")

        if any(route.recompute_current_load() != route.current_load for route in sln.all_routes):
            problems.append("a route's cached current_load is stale")

        return problems

    def solve(self, debug_level: int = 0):
        sln = self.sln
        initial_temp = 0.05 * self.best_objective
        self.temperature = initial_temp
        self.log_temperature = math.log(self.temperature, 2)

        start_time = time.time()
        elapsed_time = 0
        iterations = 0

        # 0 = none.
        # 1 = verify accepted moves' reported improvement against solution_cost() before/after
        #     apply() (or before/after propose() for escape-hatch operators, which mutate there).
        # 2 = also run _check_solution_invariants() after every accepted/rejected move.
        # 3 = also force a rejected move through apply -> recompute -> revert -> recompute, to
        #     verify the rejection would have been valid had it been accepted. Only ever applies
        #     to moves that reached the accept/reject test (move.kind is VALID) -- INVALID/NOOP
        #     moves never reach that branch and must never be applied.
        #debug_level = 0

        pre_propose_obj = 0
        #post_propose_obj = 0

        while elapsed_time < self.max_time:
            self.log_temperature += self.log_cooling_factor
            iterations += 1
            if iterations % self.segment_length == 0:
                self.update_weights()

            if iterations % self.empty_route_cleanup_interval == 0:
                self._cleanup_empty_routes()

            op = self.choose_operator()

            if debug_level >= 1:
                pre_propose_obj = sln.solution_cost()

            move = op.propose()

            if not move.is_actionable:
                if move.already_applied:
                    op.revert()
                elapsed_time = time.time() - start_time
                continue

            if debug_level >= 1 and move.already_applied:
                post_propose_obj = sln.solution_cost()
                if abs(move.improvement - (pre_propose_obj - post_propose_obj)) >= 1e-6:
                    print(f"[debug] {type(op).__name__} (escape-hatch): reported improvement {move.improvement} "
                          f"!= measured {pre_propose_obj - post_propose_obj}")

            improvement = move.improvement
            loglog_acceptance_threshold = -float('inf') if improvement >= 0 else math.log(-improvement, 2) - self.log_temperature
            accept = improvement > 0 or math.log(-math.log(random.random()), 2) >= loglog_acceptance_threshold

            if accept:
                if improvement < 0 and self.curr_objective <= self.best_objective + 1e-12:
                    # Error-safe comparison of current and best objectives - relative error as abs/ave
                    # If we're disimproving from our running global optimum: take a snapshot
                    # BEFORE stepping away from it.
                    self.take_sln_snapshot()

                if not move.already_applied:
                    if debug_level >= 1:
                        pre_op_obj = sln.solution_cost()
                        op.apply(move)
                        post_op_obj = sln.solution_cost()
                        if abs(improvement - (pre_op_obj - post_op_obj)) >= 1e-6:
                            print(f"[debug] {type(op).__name__}: reported improvement {improvement} "
                                  f"!= measured {pre_op_obj - post_op_obj}")
                    else:
                        op.apply(move)
                # else: already mutated during propose() -- nothing left to operate.

                if debug_level >= 2:
                    problems = self._check_solution_invariants(sln)
                    if problems:
                        print(f"[debug] invariant violations after accepted {type(op).__name__}: {problems}")

                op.commit()
                op.update_stats()

                self.curr_objective -= improvement
                self.best_objective = min(self.best_objective, self.curr_objective)
            else:
                if debug_level >= 3:
                    # move.kind is VALID here (checked above) -- never force-apply an INVALID/NOOP move.
                    if move.already_applied:
                        # Already mutated during propose() -- nothing to force-apply. Baseline is
                        # from before THAT mutation, i.e. pre_propose_obj.
                        pre_op_obj = pre_propose_obj
                    else:
                        pre_op_obj = sln.solution_cost()
                        op.apply(move)
                    post_op_obj = sln.solution_cost()
                    if abs(improvement - (pre_op_obj - post_op_obj)) >= 1e-6:
                        print(f"[debug] {type(op).__name__} (rejected): reported improvement {improvement} "
                              f"!= measured {pre_op_obj - post_op_obj}")
                    if debug_level >= 2:
                        problems = self._check_solution_invariants(sln)
                        if problems:
                            print(f"[debug] invariant violations mid-rejection-check for {type(op).__name__}: {problems}")
                            problems = self._check_solution_invariants(sln)
                    op.revert()   # something is applied at this point either way -- always revert
                    recompute = op.base_operator.evaluate(*move.operands)
                    op.revert()

                    if debug_level >= 2:
                        problems = self._check_solution_invariants(sln)
                        if problems:
                            print(f"[debug] invariant violations mid-rejection-check for {type(op).__name__}: {problems}")
                            problems = self._check_solution_invariants(sln)

                    reverted_obj = sln.solution_cost()
                    if abs(reverted_obj - pre_op_obj) >= 1e-6:
                        print(f"[debug] {type(op).__name__}: revert() did not restore objective "
                              f"({reverted_obj} != {pre_op_obj})")
                else:
                    if move.already_applied:
                        op.revert()
                    # else: never applied, nothing to revert

                if debug_level >= 2:
                    problems = self._check_solution_invariants(sln)
                    if problems:
                        print(f"[debug] invariant violations after rejected {type(op).__name__}: {problems}")

            if len(self.snapshots) > 2*self.max_snapshots:
                self.pare_snapshots_to_top_k(self.max_snapshots)

            curr_time = time.time()
            elapsed_time = curr_time - start_time

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

