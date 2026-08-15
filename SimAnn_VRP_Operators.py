import time
from SimAnn_VRP_BLOperators import *
import random
import math
from typing import Callable, Iterable, Iterator

### Commented operators for reference. No need to reimplement ###
# Permute src_route with permutation array: src_route.permute(permutation)
# Permute subset of src_route: src_route.subpermute(permutation)

# Multi-customer chain length is geometric: each extra customer continues with this probability.
# Only shapes lengths >= 2 -- RandomCustomerReassignment owns length 1 as its own roster entry, so
# the single-vs-multi mix is priced by the adaptive weighting rather than set by this constant.
# Uniform was tried and lost a paired A/B: it spends most draws on long chains.
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
        self._last_propose_time = 0.0
        self._apply_time_total = 0.0
        self._apply_count = 0
        self._proposal_count = 0
        self._propose_time_total = 0.0

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

    @property
    def mean_apply_time(self) -> float:
        count = self._apply_count
        return 0 if count==0 else self._apply_time_total/self._apply_count
    @property
    def mean_propose_time(self) -> float:
        return self._propose_time_total/self._proposal_count
    @property
    def mean_call_time(self)->float:
        return (self._propose_time_total + self._apply_time_total) / (self._apply_count + self._proposal_count)

    def propose(self) -> Move[Ops]:
        """Select operands and price the move. Never mutates the solution (unless the base
        operator is escape-hatch flavored, in which case it already has, atomically)."""
        t0 = time.perf_counter()
        operands = self._operand_selection_impl()
        move = self.base_operator.evaluate(operands)
        propose_time = time.perf_counter() - t0
        self.segment_time += propose_time
        self.segment_proposals += 1
        self._last_propose_time = propose_time

        self._proposal_count += 1
        self._propose_time_total += propose_time

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
        dt = 0
        if move.already_applied or not move.is_actionable:
            pass
        else:
            t0 = time.perf_counter()
            self.base_operator.apply(move)
            dt = time.perf_counter() - t0
            move.mark_applied(True)

        # _last_propose_time must have been set by the propose() that produced this move. It once
        # was not, for BestOfCandidates only, which priced CustomerBestOfkSwapInRandomRoute at
        # 3.10us against a real 95us and let it take a third of the roster's proposals. Exact
        # check, no threshold: a proposal has happened, so the field cannot still be zero.
        assert not (self._proposal_count > 0 and self._last_propose_time == 0.0), (
            f"{type(self).__name__}: propose() ran but never recorded _last_propose_time, so "
            f"apply cost will exclude it and this operator will be under-priced.")

        self._apply_count += 1
        self._apply_time_total += dt + self._last_propose_time

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
              f"Average apply time: {self.mean_apply_time}, Average propose time: {self.mean_propose_time}")

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
        mean_cost = (self.mean_call_time if self.weight_by_time else 1.0)

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


# TODO(greedy-operator): add a GreedyOperator variant that does NOT necessarily route through
# OperatorBL.evaluate(). Where a decision is fully specified by a greedy rule, the move is already
# known, so pricing candidates to rediscover it is wasted work -- the operator can construct the
# required Move directly. BestOfCandidates is the sampling answer to the same question; this is
# the deterministic one. It still owes the same lifecycle contract (a Move carrying deltas,
# improvement and eval_version) so apply/revert/commit and stress.py keep working unchanged.
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
        propose_time = time.perf_counter() - t0
        self.segment_time += propose_time
        self.segment_proposals += 1
        self.prev_operands = best.operands
        self.last_move = best

        self._proposal_count += 1
        self._propose_time_total += propose_time
        self._last_propose_time = propose_time

        self._update_reporting_stats(best)
        return best


def random_intra_route_swap_pairs(sln: FullSolution, k: int = 20) -> Iterator[SwapCustomerChainsOps]:
    route = sln.choose_random_nonempty_route()
    if route is None or route.path_len <= 1:
        return
    for _ in range(k):
        # Distinct indices, so the two length-1 chains never overlap. Adjacent is fine -- the BL
        # handles it. Trailing Falses are the reverse placeholders; for length-1 chains all four
        # priced deltas are equal, so evaluate() settles on (False, False).
        i, j = rand_distinct_indices(route.path_len, 2)
        yield route, i, route, j, False, False


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

def random_chain_destination(sln: FullSolution, src_route: Route, chain_len: int) -> tuple[Route, int]:
    """A destination route and a legal insert index for a chain of chain_len customers.

    dest_idx is the chain's start index AFTER removal, so a same-route move has chain_len fewer
    slots to land in than a cross-route one. Written once because every reassignment selector
    needs this same bound, and separate copies are separate chances to disagree with the bound
    ReassignCustomerChain actually gates on.
    """
    dest_route = rand_choice(sln.all_routes)
    # Never negative: a same-route chain is drawn FROM this path, so chain_len <= len(path).
    max_dest = (len(dest_route.path) - chain_len if dest_route is src_route
                else len(dest_route.path))
    return dest_route, rand_int_inclusive(0, max_dest)


class _ChainReassignmentBase(Operator[ReassignCustomerChainOps], ABC):
    """
    Shared operand selection for the chain-reassignment family.

    Subclasses override _choose_chain and nothing else. The roster carries these as separate
    entries so the adaptive weighting can price chain LENGTH separately -- length is therefore the
    only thing that should differ, and source/destination selection lives here once.
    """

    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReassignCustomerChain(sln))

    @abstractmethod
    def _choose_chain(self, src_route: Route) -> Chain | None:
        """None means this route cannot supply the kind of chain this operator makes."""
        raise NotImplementedError

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
        customer_chain = self._choose_chain(src_route) if valid else None
        if customer_chain is None:
            # Empty range reports INVALID rather than raising. Shows up in the operator's own
            # invalid-call counter, which is where a degenerate selector becomes visible.
            return src_route, range(0, 0), src_route, 0, False

        dest_route, dest_index = random_chain_destination(sln, src_route, len(as_chain_range(customer_chain)))

        # Trailing False is a placeholder: ReassignCustomerChain sets _evaluates_in_batch, so
        # evaluate() replaces this with the orientation it priced as better.
        return src_route, customer_chain, dest_route, dest_index, False


class RandomCustomerReassignment(_ChainReassignmentBase):
    """Chain of exactly one -- the classic single-customer relocate."""

    def _choose_chain(self, src_route: Route) -> Chain | None:
        # A bare int IS a Chain; as_chain_range normalizes it downstream.
        return rand_int_inclusive(0, len(src_route.path) - 1)


class RandomCustomerChainReassignment(_ChainReassignmentBase):
    """
    Chain of two or more, so it never duplicates RandomCustomerReassignment. Splitting the two
    lets the weighting discover the mix; previously it was fixed by the length distribution, and a
    paired A/B showed that choice was worth about 31 objective units.
    """

    def _choose_chain(self, src_route: Route) -> Chain | None:
        src_len = len(src_route.path)
        if src_len < 2:
            return None

        # start is bounded so a 2-chain always fits from it. The cap is half the route, rounded
        # up, so it scales with the route: a chain past halfway approximates moving the whole
        # route, which ReassignRouteBefore does more cheaply and with the right depot handling.
        start = rand_int_inclusive(0, src_len - 2)
        max_len = min(src_len - start, -(-src_len // 2))
        if max_len < 2:
            return None   # e.g. a 2-customer route, where the half-cap forbids a 2-chain

        # Geometric, shifted so the minimum is 2. +1e-50 guards rand_unit() == 0 (random() draws
        # from [0, 1)); it is lost to double precision elsewhere, so the distribution is unchanged.
        extra = int(math.log(rand_unit() + 1e-50) * _INV_LOG_CHAIN_CONTINUE_P)
        return range(start, start + min(max_len, 2 + extra))


class ReassignClosestChainWithRandomCustomer(_ChainReassignmentBase):
    """
    Relocates the run of customers sitting BETWEEN a random customer and its nearest
    non-adjacent neighbour in the same route.

    Those two are spatially close but sequence-distant, so whatever lies between them is a
    detour: removing it leaves a cheap arc where an expensive pair of arcs used to be. This is
    relatedness applied to the removal side, where the other two selectors only randomise.

    Length is not drawn -- it is whatever the geometry gives. The long detours are the ones with
    the most to gain, so capping would discard exactly the cases worth having.
    """

    def _choose_chain(self, src_route: Route) -> Chain | None:
        num_customers = len(src_route.path)
        anchor = rand_int_inclusive(0, num_customers - 1)
        other = src_route.closest_non_adjacent_customer(anchor)
        if other is None:
            return None

        low, high = (anchor, other) if anchor < other else (other, anchor)
        # The open interval leaves both anchors in place, so it spans at most num_customers - 2
        # and can never empty the source route. The whole-route case simply cannot arise here.
        return range(low + 1, high)


def closest_pair_reversals(sln: FullSolution) -> Iterator[ReverseCustomerChainOps]:
    """
    The two reversals that bring an anchored close pair together.

    With low and high as the pair's positions, reversing [low+1 .. high] or [low .. high-1] both
    leave them adjacent; they differ only in which OUTER arcs move. Both are 2-opt, and
    cost_deltas_if_customer_chain_reversed is O(1), so pricing both costs two arc computations
    against a proposal already paid for. Choosing one at random would discard half a neighbourhood
    for no saving.
    """
    route = sln.choose_random_nonempty_route()
    if route is None or route.path_len < 3:
        return

    anchor = rand_int_inclusive(0, route.path_len - 1)
    other = route.closest_non_adjacent_customer(anchor)
    if other is None:
        return

    low, high = (anchor, other) if anchor < other else (other, anchor)
    yield route, range(low + 1, high + 1)
    yield route, range(low, high)


class ReverseClosestPairTogether(BestOfCandidates[ReverseCustomerChainOps]):
    """Neighbour-driven 2-opt. Random reversal mostly proposes reversals that fix nothing; this
    anchors on a pair that is spatially close but sequence-distant, which is where the crossing is."""

    def __init__(self, sln: FullSolution):
        super().__init__(sln, ReverseCustomerChain(sln), closest_pair_reversals, k=2)

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

def geometric_chain_length(max_length: int) -> int:
    # +1e-50 guards rand_unit() == 0 (random() draws from [0, 1)); it is lost to double precision
    # elsewhere, so the distribution is unchanged.
    return min(max_length, 1 + int(math.log(rand_unit() + 1e-50) * _INV_LOG_CHAIN_CONTINUE_P))


def disjoint_chain_start(num_customers: int, start1: int, length1: int, length2: int) -> int | None:
    """
    A start index for a length2-chain that does not overlap [start1, start1+length1) in a route of
    num_customers. None when neither side has room.

    Sides are weighted by how many legal starts each holds. A uniform side choice would oversample
    whichever side is smaller, which on short routes is most of them.
    """
    left_starts = max(0, start1 - length2 + 1)
    right_starts = max(0, num_customers - length2 - (start1 + length1) + 1)
    if left_starts + right_starts == 0:
        return None

    if rand_int_inclusive(1, left_starts + right_starts) <= left_starts:
        return rand_int_inclusive(0, start1 - length2)
    return rand_int_inclusive(start1 + length1, num_customers - length2)


def routes_sharing_depot(sln: FullSolution, depot: Depot, at_end: bool) -> list[Route]:
    """
    Non-empty routes whose end (or start) depot is `depot`.

    The START case is a direct lookup: depot_route_starts already indexes exactly that, and it
    only holds ACTIVE routes so no emptiness filter is needed. The END case keeps an O(n) scan --
    end-depot usage is not tracked, and TODO(end-depot-index) on SwapRouteTailsAtSharedDepot
    records why it is not cheap to add.
    """
    if not at_end:
        return list(sln.depot_route_starts[depot])

    return [route for route in sln.all_routes
            if not route.is_empty and route.end_depot == depot]


class _ChainSwapBase(Operator[SwapCustomerChainsOps], ABC):
    """
    Shared operand plumbing for the chain-swap family. Subclasses override _choose_chains only.

    Separate roster entries let the weighting price each selection strategy on its own, which is
    the split that beat a fixed mix for reassignment.
    """

    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomerChains(sln))

    @abstractmethod
    def _choose_chains(self, sln: FullSolution) -> tuple[Route, Chain, Route, Chain] | None:
        """None means this draw found no legal pair."""
        raise NotImplementedError

    @staticmethod
    def _degenerate(route: Route) -> SwapCustomerChainsOps:
        # Self-overlapping, so the BL's overlap guard reports INVALID. Used instead of a retry
        # loop, which keeps the degeneracy visible in the operator's own invalid counter.
        return route, 0, route, 0, False, False

    def _operand_selection_impl(self):
        chosen = self._choose_chains(self.sln)
        if chosen is None:
            return self._degenerate(rand_choice(self.sln.all_routes))

        route1, chain1, route2, chain2 = chosen
        # Trailing Falses are placeholders: SwapCustomerChains sets _evaluates_in_batch, so
        # evaluate() replaces them with the orientations it priced as best.
        return route1, chain1, route2, chain2, False, False


class RandomCustomerSwap(_ChainSwapBase):
    """
    Two single customers -- a chain of one each. Reversing one customer changes nothing, so the
    four priced deltas are equal and min settles on (False, False).
    """

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        route2 = rand_choice(sln.all_routes)
        if route1.is_empty or route2.is_empty:
            return None

        index1 = rand_int_inclusive(0, len(route1.path) - 1)
        if route1 is route2:
            index2 = disjoint_chain_start(len(route1.path), index1, 1, 1)
            if index2 is None:
                return None   # a 1-customer route has nowhere to put the second pick
        else:
            index2 = rand_int_inclusive(0, len(route2.path) - 1)

        return route1, index1, route2, index2

class RandomSameLengthChainSwap(_ChainSwapBase):
    """
    Two chains of the SAME length. Equal lengths hit the in-place path in
    swap_customer_chains_with -- no splice, no index shift -- so this is the cheapest swap.
    """

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        route2 = rand_choice(sln.all_routes)
        len1, len2 = len(route1.path), len(route2.path)

        if route1 is route2:
            # Two disjoint equal-length chains must both fit, so neither can exceed half.
            max_length = len1 // 2
            if max_length < 1:
                return None
            length = geometric_chain_length(max_length)
            start1 = rand_int_inclusive(0, len1 - length)
            start2 = disjoint_chain_start(len1, start1, length, length)
            if start2 is None:
                return None
        else:
            max_length = min(len1, len2)
            if max_length < 1:
                return None
            length = geometric_chain_length(max_length)
            start1 = rand_int_inclusive(0, len1 - length)
            start2 = rand_int_inclusive(0, len2 - length)

        return (route1, range(start1, start1 + length),
                route2, range(start2, start2 + length))


class RandomChainSwap(_ChainSwapBase):
    """
    Two chains of independently drawn lengths. Equal by chance is fine and not worth forcing
    apart. This is the selector that reaches the unequal-size mutator paths.
    """

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        route2 = rand_choice(sln.all_routes)
        len1, len2 = len(route1.path), len(route2.path)
        if len1 < 1 or len2 < 1:
            return None

        if route1 is route2:
            if len1 < 2:
                return None
            # Leave at least one slot for the second chain.
            length1 = geometric_chain_length(len1 - 1)
            start1 = rand_int_inclusive(0, len1 - length1)
            length2 = geometric_chain_length(len1 - length1)
            start2 = disjoint_chain_start(len1, start1, length1, length2)
            if start2 is None:
                return None
        else:
            length1 = geometric_chain_length(len1)
            length2 = geometric_chain_length(len2)
            start1 = rand_int_inclusive(0, len1 - length1)
            start2 = rand_int_inclusive(0, len2 - length2)

        return (route1, range(start1, start1 + length1),
                route2, range(start2, start2 + length2))


class _SharedDepotEndSwapBase(_ChainSwapBase):
    """
    Swap the leading or trailing runs of two routes that meet at the same depot.

    No depot moves: the first/last visit sentinels stay with their own routes and only customers
    travel. The shared-depot restriction is about which pairs are worth proposing -- two routes
    that meet at a depot are spatially related, so their ends are more likely to recombine well.
    """
    _at_end: ClassVar[bool]

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        if route1.is_empty:
            return None

        depot = route1.end_depot if self._at_end else route1.start_depot
        candidates = [route for route in routes_sharing_depot(sln, depot, self._at_end)
                      if route is not route1]
        if not candidates:
            return None
        # A head or tail pair inside ONE route always overlaps, so the routes must be distinct.
        route2 = candidates[rand_int_inclusive(0, len(candidates) - 1)]

        len1, len2 = len(route1.path), len(route2.path)
        length1 = geometric_chain_length(len1)
        length2 = geometric_chain_length(len2)

        if self._at_end:
            return (route1, range(len1 - length1, len1), route2, range(len2 - length2, len2))
        return route1, range(0, length1), route2, range(0, length2)


class SwapRouteHeadsAtSharedDepot(_SharedDepotEndSwapBase):
    _at_end = False


class SwapRouteTailsAtSharedDepot(_SharedDepotEndSwapBase):
    # TODO(end-depot-index): this one keeps the O(n) routes_sharing_depot scan even after start
    # uses become an index, because END-depot usage is not tracked and is not cheap to track.
    #
    # A route's end depot IS the next route's start depot along a vehicle chain, so the set of
    # routes ending at D is nearly "the predecessors of the routes starting at D". Two corrections
    # break the equivalence: routes at the START of a vehicle have no predecessor and must be
    # dropped, and each vehicle's LAST route ends at the vehicle's final depot, which is no
    # route's start depot and must be added. Deriving it per proposal means copying and fixing up
    # the start set; maintaining it directly means new accounting on every set_end_depot, split,
    # combine, dispose and vehicle relink.
    #
    # Deferred deliberately: that is a lot of machinery for one operator's selection cost.
    _at_end = True


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

class CustomerBestOfkSwapInRandomRoute(BestOfCandidates[SwapCustomerChainsOps]):
    def __init__(self, sln: FullSolution):
        super().__init__(sln, SwapCustomerChains(sln), random_intra_route_swap_pairs, k=20)


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
    # INVALID -- by far the worst in the roster -- and every one of those is this operator picking
    # the depot the route already has, which ChangeEndDepot rejects as a no-op. The weighting then
    # prices the operator on the surviving two thirds.
    # O(1) fix, no rejection loop: draw from [0, num_depots - 2], then increment the drawn index
    # if it is >= the current end depot's index. That maps the smaller range onto "every depot
    # except the current one" with a single comparison.
    def __init__(self, sln: FullSolution):
        self.num_depots = len(sln.depots)
        super().__init__(sln, ChangeEndDepot(sln))

    def _operand_selection_impl(self):
        sln = self.sln
        if self.num_depots <= 1:
            route = sln.all_routes[0]
            return route, route.end_depot

        route = rand_choice(sln.all_routes)
        depot_id = rand_int_inclusive(0, self.num_depots - 2)
        current_depot = route.end_depot

        # Grab current index. Then, on match-current, pick last-depot, which was excluded from the draw.
        depot = sln.depots[depot_id]
        if depot == current_depot:
            depot = sln.depots[-1]

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