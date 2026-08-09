import time
from SimAnn_VRP_BLOperators import *
import random
import math
from typing import Callable, Iterable, Iterator

### Commented operators for reference. No need to reimplement ###
# Permute src_route with permutation array: src_route.permute(permutation)
# Permute subset of src_route: src_route.subpermute(permutation)

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

class Operator[Ops: tuple](ABC):
    """
    Base for all argument-free operators seen by the solver.
    Subclasses only need to override _operand_selection_impl().

    propose() selects operands and prices the move (evaluate()) without mutating the solution,
    unless the underlying OperatorBL is escape-hatch flavored (_evaluates_by_applying), in which
    case it mutates atomically as part of pricing. apply()/commit()/revert() drive the BL operator
    the same way; see OperatorBL for the actual lifecycle.

    Ops is the operand tuple shape (see the aliases in SimAnn_VRP_BLOperators). Binding it here --
    `class SplitRandomRoute(Operator[SplitRouteOps])` -- makes the wrapper, its base_operator and
    the Moves passing between them one type-checked chain, so an operand tuple of the wrong shape
    is a static error rather than a runtime surprise inside a delta function.
    """

    def __init__(self, sln: FullSolution, base_operator: OperatorBL[Ops]):
        self.sln = sln
        self.base_operator = base_operator
        self.stats = OperatorStats()

        # Adaptive-weight bookkeeping
        self.weight = 1.0
        self.prev_operands: Ops | None = None
        self.last_move: Move[Ops] | None = None

        # Segment-granularity timing: time.time()/perf_counter() has ~15ms resolution on Windows,
        # while these operators run in single-digit microseconds, so per-call timing is useless.
        # Accumulate over a whole segment (see SimAnnVRPSolver.update_weights) instead.
        self.segment_time = 0.0
        self.segment_proposals = 0
        self.mean_apply_time = 0.0
        self._apply_time_total = 0.0
        self._apply_count = 0

        self.num_invalid_calls = 0
        self.num_noop_calls = 0
        self.num_useful_calls = 0

        self.num_improving_calls = 0
        self.total_improving_improvement = 0
        self.mean_improving_improvement = 0

        self.num_degrading_calls = 0
        self.total_degrading_degradation = 0
        self.mean_degrading_degradation = 0

        self.num_neutral_calls = 0

    def propose(self) -> Move[Ops]:
        """Select operands and price the move. Never mutates the solution (unless the base
        operator is escape-hatch flavored, in which case it already has, atomically)."""
        t0 = time.perf_counter()
        operands = self._operand_selection_impl()
        move = self.base_operator.evaluate(operands)
        self.segment_time += time.perf_counter() - t0
        self.segment_proposals += 1
        self.prev_operands = operands
        self.last_move = move
        self._update_reporting_stats(move)
        return move

    def apply(self, move: Move[Ops]) -> bool:
        # Caller (the solver loop) only calls this for a move that isn't already applied --
        # see OperatorBL.apply()'s own assert.
        t0 = time.perf_counter()
        ok = self.base_operator.apply(move)
        dt = time.perf_counter() - t0
        self._apply_count += 1
        self._apply_time_total += dt
        self.mean_apply_time = self._apply_time_total / self._apply_count
        return ok

    def commit(self) -> Move[Ops]:
        return self.base_operator.commit()

    def revert(self) -> None:
        self.base_operator.revert()

    def _update_reporting_stats(self, move: Move[Ops]):
        eps = 1e-9
        if move.kind is MoveKind.INVALID:
            self.num_invalid_calls += 1
        elif move.kind is MoveKind.NOOP:
            self.num_noop_calls += 1
        else:
            self.num_useful_calls += 1
            improvement = move.improvement
            if improvement > eps:
                self.num_improving_calls += 1
                self.total_improving_improvement += improvement
                self.mean_improving_improvement = self.total_improving_improvement / self.num_improving_calls
            elif improvement < -eps:
                self.num_degrading_calls += 1
                self.total_degrading_degradation -= improvement
                self.mean_degrading_degradation = self.total_degrading_degradation / self.num_degrading_calls
            else:
                self.num_neutral_calls += 1

    def report_stats(self):
        total_calls = self.num_invalid_calls + self.num_noop_calls + self.num_useful_calls
        print(f"Stats for operator {type(self).__name__}: \n"
              f"LogWeight: {math.log(self.weight, 10)}, Total calls: {total_calls}, "
              f"Invalid: {self.num_invalid_calls}, Noop: {self.num_noop_calls}, Useful: {self.num_useful_calls}\n"
              f"Num improving calls: {self.num_improving_calls}, Mean improvement: {self.mean_improving_improvement}\n"
              f"Num degrading calls: {self.num_degrading_calls}, Mean degradation: {self.mean_degrading_degradation}\n")

    def update_stats(self):
        move = self.last_move
        if move is None or not move.is_actionable:
            self.stats.record_use(0)
            return

        mean_cost = self.segment_time / max(self.segment_proposals, 1) + self.mean_apply_time
        sign = -1 if move.improvement < 0 else 1
        score = max(0, sign * (abs(move.improvement) ** 1.5) / max(mean_cost, 1e-9))
        self.stats.record_use(score)

    def get_stats(self):
        stats = self.stats
        return stats.uses, stats.improvements, stats.score_sum

    def reset_stats(self):
        self.stats.reset()
        self.segment_time = 0.0
        self.segment_proposals = 0

    @abstractmethod
    def _operand_selection_impl(self) -> Ops:
        """
        Subclasses only need to choose operands via some method, and return them
        """
        pass


class BestOfCandidates[Ops: tuple](Operator[Ops]):
    """
    Evaluates candidate operand tuples and returns the argmax. Works with any BL operator, pure
    or escape-hatch: a candidate whose evaluate() mutated the solution (move.already_applied) is
    reverted immediately, before the next candidate is evaluated, so every candidate is always
    priced against the same true baseline.
    """
    def __init__(self, sln: FullSolution, base_operator: OperatorBL[Ops],
                 candidate_source: Callable[[FullSolution], Iterable[Ops]], k: int | None = None):
        super().__init__(sln, base_operator)
        self.candidate_source = candidate_source   # callable(sln) -> Iterable[operand tuple]
        self.k = k

    def _operand_selection_impl(self) -> Ops:
        raise NotImplementedError("BestOfCandidates overrides propose() directly.")

    def propose(self) -> Move[Ops]:
        # We're only ever evaluating candidates here, never committing to one -- so every
        # candidate is reverted immediately after being measured, unconditionally (a no-op for
        # pure operators, undoes the mutation for escape-hatch ones). That keeps every candidate
        # priced against the same true baseline, and means the move we hand back is always
        # not-yet-applied, same as a plain Operator's.
        t0 = time.perf_counter()
        best, best_imp = Move(MoveKind.NOOP), -float('inf')
        for i, operands in enumerate(self.candidate_source(self.sln)):
            if self.k is not None and i >= self.k:
                break
            move = self.base_operator.evaluate(operands)
            if move.is_actionable and move.improvement > best_imp:
                best, best_imp = move, move.improvement
            self.base_operator.revert()
        self.segment_time += time.perf_counter() - t0
        self.segment_proposals += 1
        # best was reverted like every other candidate above, so it's not applied -- even though
        # its own already_applied field (baked in at evaluate() time) may still say True.
        # sln.version also moved on since `best` was evaluated (every candidate's evaluate+revert
        # bumps it), so re-stamp that too: the solution content is identical to what it was when
        # `best` was measured (everything got reverted), just under a later version number.
        best = best._replace(already_applied=False, eval_version=self.sln.version)
        self.prev_operands = best.operands
        self.last_move = best
        self._update_reporting_stats(best)
        return best


def random_intra_route_swap_pairs(sln: FullSolution, k: int = 20) -> Iterator[SwapCustomersAtOps]:
    route = sln.choose_random_nonempty_route()
    if route is None or route.path_len <= 1:
        return
    for _ in range(k):
        i, j = random.sample(range(route.path_len), 2)
        yield route, i, route, j


def random_route_pairs(sln: FullSolution, k: int = 10) -> Iterator[CombineRoutesOps]:
    for _ in range(k):
        r1, r2 = sln.all_routes.choose_n(2)
        if not (r1.is_trivial or r2.is_trivial):
            yield r1, r2

class RandomRouteReassignment(Operator[ReassignRouteBeforeOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignRouteBefore(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        src_route = sln.choose_random_nonempty_route()
        dest_route = sln.choose_random_route_insertion_destination()

        if src_route is None or dest_route is None:
            # Degenerate solution (no routes / no vehicles) - report as invalid rather than raising.
            src_route = src_route if src_route is not None else sln.all_routes.choose_random()
            dest_route = dest_route if dest_route is not None else src_route

        return src_route, dest_route

class RandomCustomerReassignment(Operator[ReassignCustomerAtOps]):
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
            tries += 1

        if not valid:
            # Note: src_route is still an empty src_route.
            return src_route, 0, src_route, 0

        src_index = random.randint(0, len(src_route.path)-1)
        dest_route = random.choice(sln.all_routes)
        dest_index = random.randint(0, len(dest_route.path))

        return src_route, src_index, dest_route, dest_index

class RandomCustomerReassignmentToNewRoute(Operator[ReassignCustomerToNewRouteOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerToNewRouteBefore(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        src_route = random.choice(sln.all_routes)
        dest_route = sln.choose_random_route_insertion_destination()
        depot = random.choice(sln.depots)

        if len(src_route.path) == 0 or dest_route is None:
            return src_route, 0, dest_route if dest_route is not None else src_route, depot

        customer_id = random.randint(0, len(src_route.path) - 1)
        return src_route, customer_id, dest_route, depot

class ReassignWorstCustomerOutOfRandomKToNewRoute(Operator[ReassignCustomerToNewRouteOps]):
    def __init__(self, sln: FullSolution, k):
        super().__init__(sln, ReassignCustomerToNewRouteBefore(sln))
        self.k = k

    # TODO(future-operator): this always relocates the worst customer to a brand-new route.
    # Worth generalizing later to also try reassigning/swapping it into an existing route.
    def _operand_selection_impl(self):
        sln = self.sln

        route, customer_id = None, -1
        best_removal_improvement = -float('inf')

        for _ in range(self.k):
            src_route = random.choice(sln.all_routes)
            if len(src_route.path) == 0:
                continue

            src_customer_id = random.randint(0, len(src_route.path) - 1)
            # "Worst" = highest cost-delta-if-removed among sampled customers, i.e. the most
            # problematic customer currently in place -- not accounting for where it'd go next.
            removal_improvement = self.base_operator.improvement_from_deltas(
                src_route.cost_deltas_if_customer_popped(src_customer_id))
            if removal_improvement > best_removal_improvement:
                best_removal_improvement = removal_improvement
                route, customer_id = src_route, src_customer_id

        dest_route = sln.choose_random_route_insertion_destination()
        depot = random.choice(sln.depots)

        if route is None or dest_route is None:
            return sln.all_routes[0], -1, sln.all_routes[0], depot

        return route, customer_id, dest_route, depot


class RandomCustomerSwap(Operator[SwapCustomersAtOps]):
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

class CustomerBestOfkSwapInRandomRoute(BestOfCandidates[SwapCustomersAtOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomersAt(sln), random_intra_route_swap_pairs, k=20)


class RandomRoutePermutation(Operator[PermuteRouteOps]):
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

class ChangeRandomEndDepot(Operator[ChangeEndDepotOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ChangeEndDepot(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = random.choice(sln.all_routes)
        depot = random.choice(sln.depots)

        return route, depot

class DisposeOfTrivialRoutes(Operator[DisposeOfEmptyRoutesOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = True))

    def _operand_selection_impl(self):
        # Will dispose of all routes that do absolutely nothing: no customers served, end where they started.
        return RouteSet(route for route in self.sln.all_routes if route.should_dispose()),

class DisposeOfEmptyRoutes(Operator[DisposeOfEmptyRoutesOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = False))

    def _operand_selection_impl(self):
        # Will dispose of all routes that can be disposed: they serve no customers, but may do a depot-to-depot move.
        return RouteSet(route for route in self.sln.all_routes if route.can_dispose()),

class SplitRandomRoute(Operator[SplitRouteOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SplitRoute(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = random.choice(sln.all_routes)
        path = route.path

        if len(path) <= 1:
            return route, 0, sln.depots[0]   # reported as invalid by SplitRoute._evaluate_impl

        depot = random.choice(sln.depots)
        split_index = random.randint(1, len(path) - 1)

        return route, split_index, depot


class CombineRandomRoutes(BestOfCandidates[CombineRoutesOps]):
    def __init__(self, sln: FullSolution, k: int = 10):
        super().__init__(sln, CombineRoutes(sln), random_route_pairs, k=k)