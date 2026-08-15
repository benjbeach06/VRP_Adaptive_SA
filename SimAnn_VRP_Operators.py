import time
from SimAnn_VRP_BLOperators import *
import random
import math
from typing import Callable, Iterable, Iterator

### Commented operators for reference. No need to reimplement ###
# Permute src_route with permutation array: src_route.permute(permutation)
# Permute subset of src_route: src_route.subpermute(permutation)

# Reassignment chain length is geometric: each extra customer continues with this probability.
# Uniform is cheaper to sample but spends most of its draws on long chains -- on a 20-customer
# route it made length 1 about 10% of proposals, where it used to be 100% of this operator's
# behaviour. Geometric keeps short chains common (P(1) = 1 - base) and lets long ones stay rare.
CHAIN_LEN_CONTINUE_P = 0.75
# Sampled by inverse CDF: one RNG draw and one log, rather than an expected 1/(1-base) Bernoulli
# trials. Reciprocal is precomputed because this runs on every proposal.
_INV_LOG_CHAIN_CONTINUE_P = 1.0 / math.log(CHAIN_LEN_CONTINUE_P)

class OperatorStats:
    def __init__(self):
        self.proposals: int = 0
        self.accepts: int = 0
        self.score_sum: Num = 0
        self.improvements: int = 0

    def record_reject(self) -> None:
        self.proposals += 1

    def record_accept(self, score: Num):
        if score > 0:
            self.improvements += 1
        self.accepts += 1
        self.proposals += 1
        self.score_sum += max(0, score)

    def reset(self):
        self.proposals = 0
        self.accepts = 0
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
        self.segment_proposals = 0
        self.segment_time = 0.0
        self.mean_apply_time = 0.0
        self._apply_time_total = 0.0
        self._apply_count = 0

        # When False, update_stats() treats every operator's mean cost per move as 1 instead of
        # measuring it. See SimAnnVRPSolver.set_deterministic_weighting -- TESTING ONLY.
        self.weight_by_time = True

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

    def evaluate(self, operands: Ops) -> Move[Ops]:
        """
        UNTIMED pricing, for callers outside weighted selection.

        propose() is the weighted-selection entry point: it selects operands and charges the
        proposal to segment_time / segment_proposals / the reporting counters. Use this instead
        whenever the caller supplies its own operands and must NOT be charged -- unconditional
        maintenance, the solver's debug re-checks, and the test suite.
        """
        return self.base_operator.evaluate(operands)

    def apply_for_acceptance(self, move: Move[Ops]):
        # Core accept path within solver: Apply, and do necessary timing/accounting
        if move.already_applied or not move.is_actionable:
            return

        t0 = time.perf_counter()
        self.base_operator.apply(move)
        dt = time.perf_counter() - t0
        self._apply_count += 1
        self._apply_time_total += dt
        self.mean_apply_time = self._apply_time_total / self._apply_count
        move.mark_applied(True)

    def apply(self, move: Move[Ops]):
        """
        UNTIMED apply, for callers outside weighted selection.

        Use apply_for_acceptance() on the solver's accept path -- it charges apply time to
        mean_apply_time, which feeds the cost term in operator scoring. Use this one when the
        operator is not competing for selection, so the cost model stays clean. Production
        callers today: SimAnnVRPSolver._dispose_empty_routes (maintenance) and the snapshot
        re-apply. Also used by the tests.
        """
        if move.already_applied:
            return

        self.base_operator.apply(move)
        move.mark_applied(True)

    def commit(self, move: Move[Ops]):
        self.base_operator.commit(move)

    def revert_and_reject(self, move: Move[Ops]):
        # Revert a rejected move and count reversion time for operators that operated-to-compute
        if not move.already_applied:
            return

        t0 = time.perf_counter()
        self.base_operator.revert(move)
        self.segment_time += time.perf_counter() - t0
        move.mark_applied(False)

        return

    def revert(self, move: Move[Ops]):
        """
        UNTIMED revert, for callers outside weighted selection.

        Use revert_and_reject() on the solver's reject path -- it charges revert time to
        segment_time, because reverting a rejected move is a real cost of having tried the
        operator. Use this one when the operator is not competing for selection. Production
        callers today: BestOfCandidates.propose (reverting each candidate is part of the
        proposal, already timed by its own outer span), SimAnnVRPSolver._dispose_empty_routes,
        and the snapshot round trip. Also used by the tests.
        """
        if not move.already_applied:
            return

        self.base_operator.revert(move)
        move.mark_applied(False)
        return

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
        print(f"\nStats for operator {type(self).__name__}: \n"
              f"LogWeight: {math.log(self.weight, 10)}, Total calls: {total_calls}, "
              f"Invalid: {self.num_invalid_calls}, Noop: {self.num_noop_calls}, Useful: {self.num_useful_calls}\n"
              f"Num improving calls: {self.num_improving_calls}, Mean improvement: {self.mean_improving_improvement}\n"
              f"Num degrading calls: {self.num_degrading_calls}, Mean degradation: {self.mean_degrading_degradation}\n"
              f"Average apply time: {self.mean_apply_time}")

    def update_stats_for_reject(self):
        self.stats.record_reject()

        # TODO: MISSING STATISTICS - Operator times for proposals must be separated from operator times for accepts.
        #  IF move rejected:
        #  1) IF move operated yet: We need to ADD IN revert time on because it's a real cost of trying out the operator.
        #  2) IF move not operated yet: We can just keep pure compute time
        #  IF move accepted:
        #  1) IF move operated yet: Committing is essentially free so we can just keep that cost.
        #  2) IF move not operated yet: We operate, add in time to operate, and record that.
        #  ALSO: Debugging operations CANNOT affect operator statistics.
        #  All operator methods that record statistics MUST only update stats like segment_time and segment_proposals on accept.

    def update_stats_for_accept(self):
        move = self.last_move
        assert move is not None # We never accept a None or non-actionable move

        # TODO(rescore): re-evaluate this scoring once the stats above are rebuilt. The two terms
        #  answer deliberately different questions -- SCORE is average nonnegative improvement per
        #  ACCEPT ("if accepted, how much do I expect to gain?"), COST is average time per
        #  PROPOSAL ("if I call this, how long will it take?") -- so the differing denominators are
        #  intentional, not an oversight. The problem is that the current stats can't express it
        #  properly: this refactor shifted the solver to "apply only when accepting, or when
        #  applying-to-evaluate", so proposal time and apply/revert time are no longer the same
        #  quantity, and neither segment_time nor mean_apply_time has been re-derived for that
        #  split. Fix the statistics first (see the TODO in update_stats_for_reject), then decide
        #  what the score should divide by -- don't tune the formula against numbers that are
        #  measuring the wrong thing.

        # Cost-aware weighting: an operator's score is its improvement per unit of time spent,
        # so cheap operators are preferred at equal improvement. Substituting 1 makes selection a
        # pure function of improvements, and therefore reproducible (see set_deterministic_weighting).
        mean_cost = (self.segment_time / max(self.segment_proposals, 1) + self.mean_apply_time
                     if self.weight_by_time else 1.0)

        sign = -1 if move.improvement < 0 else 1
        score = max(0, sign * (abs(move.improvement) ** 1.5) / max(mean_cost, 1e-9))
        self.stats.record_accept(score)

    def get_stats(self):
        stats = self.stats
        return stats.proposals, stats.accepts, stats.improvements, stats.score_sum

    def reset_stats(self):
        self.stats.reset()
        self.segment_time = 0.0

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
            move = self.evaluate(operands)
            if move.is_actionable and move.improvement > best_imp:
                best, best_imp = move, move.improvement
            self.revert(move)
        self.segment_time += time.perf_counter() - t0
        self.segment_proposals += 1
        self.prev_operands = best.operands
        self.last_move = best
        self._update_reporting_stats(best)
        return best


def random_intra_route_swap_pairs(sln: FullSolution, k: int = 20) -> Iterator[SwapCustomersAtOps]:
    route = sln.choose_random_nonempty_route()
    if route is None or route.path_len <= 1:
        return
    for _ in range(k):
        i, j = rand_distinct_indices(route.path_len, 2)
        yield route, i, route, j


def random_route_pairs(sln: FullSolution, k: int = 10) -> Iterator[CombineRoutesOps]:
    # choose_n(2) needs two routes to draw from; with few customers and many vehicles the route
    # count really can collapse to one (or zero) after disposals, and sampling then raises rather
    # than simply producing no candidates.
    if len(sln.all_routes) < 2:
        return
    for _ in range(k):
        r1, r2 = sln.all_routes.choose_n(2)
        # is_empty, not is_trivial: combine_with rejects any empty route, and an
        # empty-but-not-trivial one would otherwise be yielded and then raise on apply.
        if not (r1.is_empty or r2.is_empty):
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

class RandomCustomerChainReassignment(Operator[ReassignCustomerChainOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerChain(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        #NOTE: src_route could be empty. We allow this possibility here, expecting operator to fail gracefully.
        retries = 100
        tries = 0
        valid = False
        src_route = None
        while not valid and tries < retries:
            src_route = rand_choice(sln.all_routes)
            valid = len(src_route.path) >= 1
            tries += 1

        assert isinstance(src_route, Route)
        if not valid:
            # Note: src_route is still an empty src_route.
            return src_route, range(0, 0), src_route, 0, False

        # Chain length caps at half the route, rounded up, so the bound scales with the route
        # instead of being a fixed number. A chain past halfway starts to approximate moving the
        # whole route, which ReassignRouteBefore already does more cheaply and with the right
        # depot handling. Rounding up keeps length 1 reachable on a 1-customer route.
        src_len = len(src_route.path)
        start = rand_int_inclusive(0, src_len - 1)
        max_len = min(src_len - start, -(-src_len // 2))
        # +1e-50 guards rand_unit() == 0 (random() draws from [0, 1)). It is lost to double
        # precision everywhere else -- 1.0 + 1e-50 == 1.0 -- so the distribution is unchanged.
        length = min(max_len, 1 + int(math.log(rand_unit() + 1e-50) * _INV_LOG_CHAIN_CONTINUE_P))
        chain = range(start, start + length)

        dest_route = rand_choice(sln.all_routes)
        max_dest = (len(dest_route.path) - len(chain) if dest_route is src_route
                    else len(dest_route.path))
        if max_dest < 0:
            return src_route, chain, src_route, start, False   # NOOP: nowhere to put it
        dest_index = rand_int_inclusive(0, max_dest)

        # Trailing False is a placeholder: ReassignCustomerChain sets _evaluates_in_batch, so
        # evaluate() replaces this with the orientation it priced as better.
        return src_route, chain, dest_route, dest_index, False

class RandomCustomerReassignmentToNewRoute(Operator[ReassignCustomerToNewRouteOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerToNewRouteBefore(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        src_route = rand_choice(sln.all_routes)
        dest_route = sln.choose_random_route_insertion_destination()
        depot = rand_choice(sln.depots)

        if len(src_route.path) == 0 or dest_route is None:
            return src_route, 0, dest_route if dest_route is not None else src_route, depot

        customer_id = rand_int_inclusive(0, len(src_route.path) - 1)
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
            src_route = rand_choice(sln.all_routes)
            if len(src_route.path) == 0:
                continue

            src_customer_id = rand_int_inclusive(0, len(src_route.path) - 1)
            # "Worst" = highest cost-delta-if-removed among sampled customers, i.e. the most
            # problematic customer currently in place -- not accounting for where it'd go next.
            removal_improvement = self.base_operator.improvement_from_deltas(
                src_route.cost_deltas_if_customer_popped(src_customer_id))
            if removal_improvement > best_removal_improvement:
                best_removal_improvement = removal_improvement
                route, customer_id = src_route, src_customer_id

        dest_route = sln.choose_random_route_insertion_destination()
        depot = rand_choice(sln.depots)

        if route is None or dest_route is None:
            return sln.all_routes[0], -1, sln.all_routes[0], depot

        return route, customer_id, dest_route, depot

class RandomCustomerSwap(Operator[SwapCustomersAtOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomersAt(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        # NOTE: It's worse in this case than in the random reassignment case if the customers choices are invalid.
        route1 = rand_choice(sln.all_routes)

        if len(route1.path) == 0:
            return route1, 0, route1, 0

        index1 = rand_int_inclusive(0, len(route1.path) - 1)
        route2 = rand_choice(sln.all_routes)

        if len(route2.path) == 0:
            return route1, 0, route1, 0
        index2 = rand_int_inclusive(0, len(route2.path) - 1)

        return route1, index1, route2, index2

class RandomCustomerChainReversal(Operator[ReverseCustomerChainOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReverseCustomerChain(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = rand_choice(sln.all_routes)

        if len(route.path) < 2:
            return route, range(0, 0)   # degenerate: NOOP, not a fake one-element chain

        # Cannot truly be uniform: resolves to pre-ordered order statistics more or less
        # Mean length averages out to about half the path length, as (route_end_idx-start)/2 averages to about len(route)/2 over uniform starts.
        start = rand_int_inclusive(0, len(route.path)-2)
        end = rand_int_inclusive(start+1, len(route.path)-1)

        return route, range(start, end + 1)

class CustomerBestOfkSwapInRandomRoute(BestOfCandidates[SwapCustomersAtOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomersAt(sln), random_intra_route_swap_pairs, k=20)


class RandomRoutePermutation(Operator[PermuteRouteOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, PermuteRoute(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = rand_choice(sln.all_routes)

        permutation = list(range(len(route.path)))

        if len(route.path) <= 1:
            return route, permutation

        rand_shuffle(permutation)

        return route, permutation

class ChangeRandomEndDepot(Operator[ChangeEndDepotOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, ChangeEndDepot(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = rand_choice(sln.all_routes)
        depot = rand_choice(sln.depots)

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

    def evaluate_dispose_all(self) -> Move[DisposeOfEmptyRoutesOps]:
        """
        Select every disposable route and price the disposal, WITHOUT the proposal bookkeeping.

        For callers that run disposal as unconditional maintenance rather than as a weighted
        proposal -- see SimAnnVRPSolver._dispose_empty_routes, which runs on a fixed interval and
        before every snapshot. Such a caller must not touch segment_time, segment_proposals or the
        reporting counters, because this operator never competes for selection; propose() would.

        Returns a NOOP move when nothing is disposable, so callers need no separate empty check.
        """
        return self.evaluate(self._operand_selection_impl())

class SplitRandomRoute(Operator[SplitRouteOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SplitRoute(sln))

    def _operand_selection_impl(self):
        sln = self.sln

        route = rand_choice(sln.all_routes)
        path = route.path

        if len(path) <= 1:
            return route, 0, sln.depots[0]   # reported as invalid by SplitRoute._evaluate_impl

        depot = rand_choice(sln.depots)
        split_index = rand_int_inclusive(1, len(path) - 1)

        return route, split_index, depot


class CombineRandomRoutes(BestOfCandidates[CombineRoutesOps]):
    def __init__(self, sln: FullSolution, k: int = 10):
        super().__init__(sln, CombineRoutes(sln), random_route_pairs, k=k)