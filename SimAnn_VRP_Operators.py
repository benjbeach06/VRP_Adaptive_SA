import bisect
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

    def record_accept(self, score: Num, improved: bool) -> None:
        self.improvements += improved
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

    def __init__(self, sln: FullSolution, explore_reward: Num, base_operator: OperatorBL[Ops]):
        self.sln = sln
        self.base_operator = base_operator
        self.stats = OperatorStats()

        # Adaptive-weight bookkeeping
        self.weight = 1.0
        self.prev_operands: Ops | None = None
        self.last_move: Move[Ops] | None = None

        # Segment-granularity timing: accumulate over a whole segment (see
        # SimAnnVRPSolver.update_weights) rather than trusting any single call.
        #
        # NOTE: this comment used to say perf_counter has ~15ms resolution on Windows, which is
        # false and was measured to be false -- time.get_clock_info('perf_counter').resolution is
        # 1e-7s here, and back-to-back reads advance by ~100ns. The ~15ms figure is the OLD
        # time.time() tick, not perf_counter's. The design is still right, for a different reason:
        # two perf_counter calls around a 4us operator cost a few percent of the thing being
        # measured, and a single call can be straddled by a GC pause or a scheduler slice.
        # Segment sums average both away. Per-call timing is viable when wanted -- see
        # tools/profile_operators.py, which uses it deliberately and reports medians.
        self.segment_proposals = 0
        self.segment_time = 0.0
        self._last_propose_time = 0.0
        self._apply_time_total = 0.0
        self._apply_count = 0
        self._proposal_count = 0
        self._propose_time_total = 0.0

        self.explore_reward = explore_reward

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

        self.exploit_only = False # For operators that determine moves by optimizing instead of through random choice
        self.exploit_selection_penalty_factor = 1.0

    # All three guard a zero denominator, because report_stats() reads every one at the end of
    # solve() and a proposal count really can be zero.
    #
    # In a REAL solve that would be alarming -- at millions of iterations even a 0.02% selection
    # share is hundreds of proposals. It is reachable only under an ITERATION CAP. Measured on the
    # 2000-iteration test at 20 customers: weights had already spread 5800:1
    # (SwapRouteHeadsAtSharedDepot 6.2e3 against 1.08 for most of the roster), so the leader took
    # 67% of all proposals and the tail got one to three each. No weight had collapsed; the
    # distribution was simply that peaked that early, and one more roster entry was enough to push
    # an operator to zero. mean_apply_time was already guarded; the other two were not, so adding
    # operators turned a passing suite into ZeroDivisionError.
    @property
    def mean_apply_time(self) -> float:
        count = self._apply_count
        return 0 if count == 0 else self._apply_time_total / count
    @property
    def mean_propose_time(self) -> float:
        count = self._proposal_count
        return 0 if count == 0 else self._propose_time_total / count
    @property
    def mean_call_time(self) -> float:
        count = self._apply_count + self._proposal_count
        return 0 if count == 0 else (self._propose_time_total + self._apply_time_total) / count

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
        _apply_time_total, and so into mean_call_time, which is the cost term in operator scoring
        (see update_stats_for_accept). Use this one when the operator is not competing for
        selection, so the cost model stays clean. Production callers today:
        SimAnnVRPSolver._dispose_empty_routes (maintenance) and the snapshot re-apply. Also used
        by the tests.

        This used to say the charge lands in mean_apply_time, "which feeds the cost term in
        operator scoring". It does not: mean_apply_time has exactly one caller, the stats print
        at the end of a run. Scoring reads mean_call_time. The distinction matters because
        mean_apply_time is averaged over ACCEPTED moves only, and several operators are accepted
        just a handful of times in a whole solve -- CombineRandomRoutes was accepted once in
        33,654 proposals in a 60s run at n=200. Its printed "Average apply time" is therefore a
        one-sample figure, and reading it as a cost is a mistake. Scoring is unaffected.
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
              f"LogWeight: {math.log(self.weight, 10)}, Total calls: {total_calls}, Total proposals: {self._proposal_count}, Total applies: {self._apply_count}\n"
              f"Invalid: {self.num_invalid_calls}, Noop: {self.num_noop_calls}, Useful: {self.num_useful_calls}\n"
              f"Num improving calls: {self.num_improving_calls}, Mean improvement: {self.mean_improving_improvement}\n"
              f"Num degrading calls: {self.num_degrading_calls}, Mean degradation: {self.mean_degrading_degradation}\n"
              f"Average apply time: {self.mean_apply_time}, Average propose time: {self.mean_propose_time}, Average call time: {self.mean_call_time}")

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

        improvement = move.improvement
        sign = -1 if improvement < 0 else 1
        improved = improvement>1e-9
        score = max(self.explore_reward, sign * (abs(improvement) ** 1.5) )/ max(mean_cost, 1e-9)
        self.stats.record_accept(score, improved)

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
    def __init__(self, sln: FullSolution, explore_reward: Num, base_operator: OperatorBL[Ops],
                 candidate_source: Callable[[FullSolution], Iterable[Ops]], k: int | None = None):
        super().__init__(sln, explore_reward, base_operator)
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


def neighbor_intra_route_swap_pairs(sln: FullSolution, k: int = 5) -> Iterator[SwapCustomerChainsOps]:
    """
    Swaps pairing ONE anchor with its k nearest route-mates, nearest first.

    The random version above draws k independent index pairs. In a 71-customer route that is k
    lottery tickets, and the operator still reached 9.79% acceptance while consuming 44% of all
    solver time -- the move is good, the aiming is not.

    One scan serves every candidate here, rather than one scan per candidate: the anchor is fixed,
    so its near route-mates are collected in a single pass and then yielded in rank order.
    BestOfCandidates prices them in that order, so a smaller k costs the WORST candidates, not
    random ones. That is why k=5 is defensible where k=5 random pairs would not be.

    Sequence-adjacent positions are skipped for the same reason
    Route.closest_non_adjacent_customer skips them: two customers already side by side have
    nothing to gain from a swap that brings them together.
    """
    route = sln.choose_random_nonempty_route()
    if route is None or route.path_len <= 2:
        return

    anchor = rand_index(route.path_len)
    ranks = sln.neighbor_rank[route.path[anchor].cID]

    hits = []
    for i, visit in enumerate(route.path):
        if abs(i - anchor) <= 1:
            continue
        rank = ranks.get(visit.cID)
        if rank is not None:
            hits.append((rank, i))

    hits.sort()
    for _, i in hits[:k]:
        yield route, anchor, route, i, False, False


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
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, ReassignRouteBefore(sln))

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


# How many routes a neighbor-guided selector will draw before giving up. Higher than
# DEPOT_PARTNER_DRAWS because each draw here is a handful of dict lookups, not a delta computation.
NEIGHBOR_ROUTE_DRAWS = 32


def draw_route_with_neighbor(sln: FullSolution, anchor_cid: int,
                             exclude: Route) -> tuple[Route, int] | None:
    """
    A route holding one of anchor's nearest customers, and that customer's index within it.

    Returns the BEST-ranked neighbor present, not the first one found, so a route containing
    several of them lands the chain beside the closest.

    Cost is bounded by ROUTE length, not customer count: one dict lookup per visit and no distance
    arithmetic at all. That is ~2.8us on a 71-customer route and ~0.16us on a 4-customer one.
    Drawing routes at random and rejecting misses, rather than building a candidate list, mirrors
    _draw_partner -- O(1) per draw against O(routes) to filter.

    `exclude` is the source route. Skipping it keeps every move cross-route, which is what makes
    the caller's dest_idx a plain index with no after-removal adjustment.
    """
    ranks = sln.neighbor_rank[anchor_cid]
    all_routes = sln.all_routes

    for _ in range(NEIGHBOR_ROUTE_DRAWS):
        route = rand_choice(all_routes)
        if route is exclude or route.is_empty:
            continue

        best_index, best_rank = None, len(ranks)
        for index, visit in enumerate(route.path):
            rank = ranks.get(visit.cID)
            if rank is not None and rank < best_rank:
                best_index, best_rank = index, rank

        if best_index is not None:
            return route, best_index

    return None


def neighbor_destination(sln: FullSolution, src_route: Route,
                         chain: Chain) -> tuple[Route, int] | None:
    """
    Land a chain beside one of its own near neighbors, in a different route.

    Shared by every reassignment selector that wants a geometric destination, so the
    "before or after the neighbor" convention lives in one place rather than per operator.
    """
    anchor = src_route.path[as_chain_range(chain).start]
    found = draw_route_with_neighbor(sln, anchor.cID, exclude=src_route)
    if found is None:
        return None

    dest_route, neighbor_index = found
    # Immediately before or after the neighbor, drawn evenly. Both put the chain one arc from it,
    # and which side wins depends on the neighbor's OTHER neighbor -- not something this selector
    # prices. dest_idx == len(path) is a legal append, so +1 never overruns.
    return dest_route, neighbor_index + rand_int_inclusive(0, 1)


def best_neighbor_in_same_route(sln: FullSolution, route: Route, index: int) -> int | None:
    """
    Index of the nearest customer to path[index] that shares its route and is NOT beside it.

    Same shape and same exclusion rationale as Route.closest_non_adjacent_customer -- a pair that
    is already adjacent has nothing to gain from being brought together -- but it tests
    neighbor_rank membership instead of computing a distance per step, so the inner loop is a dict
    lookup rather than a cached hypot.

    The tradeoff is reach: this only sees customers in the anchor's global top-k, so it returns
    None when no near neighbor happens to share the route. The caller treats that as a dead draw.
    """
    ranks = sln.neighbor_rank[route.path[index].cID]
    path = route.path

    best_index, best_rank = None, len(ranks)
    for i, visit in enumerate(path):
        if abs(i - index) <= 1:
            continue
        rank = ranks.get(visit.cID)
        if rank is not None and rank < best_rank:
            best_index, best_rank = i, rank

    return best_index


class _ChainReassignmentBase(Operator[ReassignCustomerChainOps], ABC):
    """
    Shared operand selection for the chain-reassignment family.

    Subclasses override _choose_chain, and optionally _choose_destination. Most override only the
    first: the roster carries the length variants as separate entries so the adaptive weighting can
    price chain LENGTH separately, and for those, source selection lives here once.

    _choose_destination exists because "where does this chain go" is the other half of the move, and
    the measured evidence is that it matters more. Random destinations accept 0.00-0.04% of
    proposals at 500 customers; the one operator with no destination to choose accepts 18.51%.
    """

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, ReassignCustomerChain(sln))

    @abstractmethod
    def _choose_chain(self, src_route: Route) -> Chain | None:
        """None means this route cannot supply the kind of chain this operator makes."""
        raise NotImplementedError

    def _choose_destination(self, src_route: Route, chain: Chain) -> tuple[Route, int] | None:
        """
        Where the chosen chain should land. None means this draw found nowhere legal.

        Takes the CHAIN, not just its length: a geometric selector needs the endpoint customers to
        decide, and only the chain identifies them.
        """
        return random_chain_destination(self.sln, src_route, len(as_chain_range(chain)))

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
        destination = (self._choose_destination(src_route, customer_chain)
                       if customer_chain is not None else None)
        if destination is None:
            # Empty range reports INVALID rather than raising. Shows up in the operator's own
            # invalid-call counter, which is where a degenerate selector becomes visible. Both
            # hooks failing land here, so one counter covers both kinds of degeneracy.
            return src_route, range(0, 0), src_route, 0, False

        dest_route, dest_index = destination

        # Trailing False is a placeholder: ReassignCustomerChain sets _evaluates_in_batch, so
        # evaluate() replaces this with the orientation it priced as better.
        return src_route, customer_chain, dest_route, dest_index, False


class RandomCustomerReassignment(_ChainReassignmentBase):
    """Chain of exactly one -- the classic single-customer relocate."""

    def _choose_chain(self, src_route: Route) -> Chain | None:
        # A bare int IS a Chain; as_chain_range normalizes it downstream.
        return rand_int_inclusive(0, len(src_route.path) - 1)


class ReassignChainNextToNeighbor(_ChainReassignmentBase):
    """
    Relocate one customer to sit beside a near neighbor of its own, in a different route.

    Same move as RandomCustomerReassignment; the only difference is that the destination is chosen
    rather than drawn. That difference is the whole point: a random destination in a 500-customer
    instance is essentially never right, and the roster's random-destination operators accept
    0.00-0.04% of proposals against 18.51% for the one operator that has no destination to choose.

    Or-opt with neighbor lists, from the VRP literature. The diagnosis that the roster needed it is
    from this solver's own acceptance data.
    """

    def _choose_chain(self, src_route: Route) -> Chain | None:
        return rand_int_inclusive(0, len(src_route.path) - 1)

    def _choose_destination(self, src_route: Route, chain: Chain) -> tuple[Route, int] | None:
        return neighbor_destination(self.sln, src_route, chain)


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


class ReassignClosestChainNextToNeighbor(ReassignClosestChainWithRandomCustomer):
    """
    The detour chain above, but landed beside a near neighbor instead of anywhere.

    Its parent uses geometry to decide what to REMOVE and then picks the destination at random,
    which is half a move: it accepted 0.04% of proposals at 500 customers. Both operators stay in
    the roster so the adaptive weighting arbitrates between them inside one run, which is the only
    comparison on this project that reliably resolves anything -- a paired 60s objective A/B could
    not separate a 15-unit difference across five seeds.
    """

    def _choose_destination(self, src_route: Route, chain: Chain) -> tuple[Route, int] | None:
        return neighbor_destination(self.sln, src_route, chain)


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

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, ReverseCustomerChain(sln), closest_pair_reversals, k=2)

class RandomCustomerReassignmentToNewRoute(Operator[ReassignCustomerToNewRouteOps]):
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, ReassignCustomerToNewRouteBefore(sln))

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
    def __init__(self, sln: FullSolution, explore_reward: Num, k):
        super().__init__(sln, explore_reward, ReassignCustomerToNewRouteBefore(sln))
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


def routes_sharing_depot(sln: FullSolution, depot: Depot, at_end: bool) -> RouteSet | list[Route]:
    """
    Non-empty routes whose end (or start) depot is `depot`.

    START is a direct index lookup, O(1): depot_route_starts holds exactly this, and only ACTIVE
    routes, so no emptiness filter is needed. END has no index and is scanned, O(routes) -- see
    TODO(end-depot-index) on SwapRouteTailsAtSharedDepot for why one is not cheap to maintain.

    The two return DIFFERENT types on purpose, and callers still need no branch: rand_choice and
    len() both accept any sequence with indexing, RouteSet included. Forcing the scan to build a
    RouteSet instead would only pay for an index map nothing here reads -- measured at roughly
    double the cost of the list. Adding an end index later changes only the scan line below.

    The START result is the LIVE index, not a copy. Callers must not mutate it.
    """
    if not at_end:
        return sln.depot_route_starts[depot]

    return [route for route in sln.all_routes
            if not route.is_empty and route.end_depot == depot]


class _ChainSwapBase(Operator[SwapCustomerChainsOps], ABC):
    """
    Shared operand plumbing for the chain-swap family. Subclasses override _choose_chains only.

    Separate roster entries let the weighting price each selection strategy on its own, which is
    the split that beat a fixed mix for reassignment.
    """

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, SwapCustomerChains(sln))

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

class SwapChainsWithNeighbor(_ChainSwapBase):
    """
    Swap two chains anchored on customers that are near each other but in different routes.

    Cross-exchange, guided. RandomChainSwap and RandomSameLengthChainSwap make the same move with
    both anchors drawn at random and accept 0.00% of proposals at 500 customers; the move type is
    not the problem, the blind pairing is.

    Both routes differ by construction, so the chains cannot overlap and the BL's same-route
    overlap guard is never the thing that rejects this.
    """

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        if route1.is_empty:
            return None

        index1 = rand_int_inclusive(0, len(route1.path) - 1)
        found = draw_route_with_neighbor(sln, route1.path[index1].cID, exclude=route1)
        if found is None:
            return None

        route2, index2 = found
        # Chains grow FORWARD from each anchor so the anchors themselves are always included --
        # they are the pair we chose these routes for. Clipping to each route keeps both non-empty.
        length1 = geometric_chain_length(len(route1.path) - index1)
        length2 = geometric_chain_length(len(route2.path) - index2)

        return route1, range(index1, index1 + length1), route2, range(index2, index2 + length2)


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

    # Draws to find a partner that is not route1 before giving up. With k routes at the depot the
    # chance of repeatedly redrawing route1 is k**-DEPOT_PARTNER_DRAWS, so 3 is ample for k >= 2.
    DEPOT_PARTNER_DRAWS: ClassVar[int] = 3

    def _choose_chains(self, sln: FullSolution):
        route1 = rand_choice(sln.all_routes)
        if route1.is_empty:
            return None

        depot = route1.end_depot if self._at_end else route1.start_depot
        # A head or tail pair inside ONE route always overlaps, so the routes must be distinct.
        route2 = self._draw_partner(sln, route1, depot)
        if route2 is None:
            return None

        len1, len2 = len(route1.path), len(route2.path)
        length1 = geometric_chain_length(len1)
        length2 = geometric_chain_length(len2)

        if self._at_end:
            return (route1, range(len1 - length1, len1), route2, range(len2 - length2, len2))
        return route1, range(0, length1), route2, range(0, length2)

    def _draw_partner(self, sln: FullSolution, route1: Route, depot: Depot) -> Route | None:
        """
        Another route meeting route1 at `depot`, or None.

        One code path for both sides. route1 itself always belongs to the set -- it is non-empty
        and meets the depot by construction -- so a size under 2 means it is the only one there.
        Drawing beats filtering: building a candidate list to exclude route1 would be O(k) for a
        single pick, which is exactly what the index exists to avoid.
        """
        route_set = routes_sharing_depot(sln, depot, self._at_end)
        if len(route_set) < 2:
            return None

        for _ in range(self.DEPOT_PARTNER_DRAWS):
            route2 = rand_choice(route_set)
            if route2 is not route1:
                return route2
        return None


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
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, ReverseCustomerChain(sln))

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
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, SwapCustomerChains(sln), random_intra_route_swap_pairs, k=20)


class CustomerBestOfkNeighborSwapInRandomRoute(BestOfCandidates[SwapCustomerChainsOps]):
    """
    Same intra-route swap, aimed geometrically and at a quarter the candidate count.

    Both this and the k=20 random version stay in the roster so the adaptive weighting arbitrates
    between them inside one run. Note what that comparison can and cannot say: the two differ in
    BOTH k and candidate selection, so a win identifies the better OPERATOR and attributes nothing
    to either factor alone. A clean k ablation would need a third entry holding selection fixed.

    Cost is linear in k, and the random version is 44% of all solver time, so k=20 -> 5 is a large
    saving if the aiming holds up.
    """

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, SwapCustomerChains(sln), neighbor_intra_route_swap_pairs, k=5)


class RandomRoutePermutation(Operator[PermuteChainOps]):
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, PermuteChain(sln))

    def _operand_selection_impl(self):
        route = rand_choice(self.sln.all_routes)
        path_len = len(route.path)
        permutation = list(range(path_len))
        # PermuteChain returns NOOP for a chain of length <= 1, so no length guard is needed here.
        rand_shuffle(permutation)
        return route, range(0, path_len), permutation

def farthest_insertion_order(points: Sequence[tuple[Num, Num]], left: tuple[Num, Num], right: tuple[Num, Num]) -> list[int]:
    """
    Order `points` between two fixed endpoints by farthest insertion. Returns indices into
    `points`. The fixed-endpoint Hamiltonian path problem, solved approximately.

    Why farthest insertion and not the alternatives, and the measured O(n^2):
    design/span_reorder/farthest_insertion_order.md
    """
    n = len(points)
    if n == 0:
        return []

    def sq(p: tuple[Num, Num], q: tuple[Num, Num]):
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2

    # SELECTION uses squared distance; PLACEMENT below uses true distance. Not
    # interchangeable -- a sum of squares does not order like a sum of lengths.
    sq_dist_to_path: list[Num] = [min(sq(p, left), sq(p, right)) for p in points]
    seq: list[tuple[int, tuple]] = [(-1, left), (-2, right)]
    remaining = set(range(n))

    while remaining:
        # One linear scan, ties to the lowest index. Sorting here costs a log factor; see
        # design/span_reorder/farthest_insertion_order.md
        chosen, best_dist = -1, -1.0
        for index in remaining:
            dst = sq_dist_to_path[index]
            if dst > best_dist or (dst == best_dist and index < chosen):
                chosen, best_dist = index, dst
        remaining.discard(chosen)
        here = points[chosen]

        best_at, best_cost = 0, float("inf")
        for pos in range(len(seq) - 1):
            a, b = seq[pos][1], seq[pos + 1][1]
            cost = math.dist(a, here) + math.dist(here, b) - math.dist(a, b)
            if cost < best_cost:
                best_at, best_cost = pos + 1, cost
        seq.insert(best_at, (chosen, here))

        for i in remaining:
            d = sq(points[i], here)
            if d < sq_dist_to_path[i]:
                sq_dist_to_path[i] = d

    result = [index for index, _ in seq if index >= 0]
    if result == list(range(n)):
        return []
    else:
        return result


# Longest span the exact reorderer will attempt. Cost is K! in the worst case and INDEPENDENT of
# problem size, so the lever is this ceiling, not a selection discount. To be ablated.
EXACT_REORDER_MAX_SPAN = 8


def _span_cost(order, dist, n):
    """Cost of visiting `order` between the anchors. dist is (n+2)x(n+2); n=left, n+1=right."""
    total = dist[n][order[0]]
    for a, b in zip(order, order[1:]):
        total += dist[a][b]
    return total + dist[order[-1]][n + 1]


def exact_span_order(points: Sequence[tuple[Num, Num]], left: tuple[Num, Num],
                     right: tuple[Num, Num]) -> list[int]:
    """
    OPTIMAL order of `points` between two fixed endpoints, by branch and bound.

    Returns [] when the current order is already optimal.

    Why exact rather than heuristic, why K! is not the real cost, and why the ceiling is
    EXACT_REORDER_MAX_SPAN rather than a selection penalty:
    design/span_reorder/reorder_operators.md
    """
    n = len(points)
    if n < 3:
        return []

    # (n+2)^2 <= 100 entries, computed once. The search below is then integer lookups, not
    # math.dist calls, which is what makes thousands of branches affordable.
    nodes = list(points) + [left, right]
    dist = [[math.dist(a, b) for b in nodes] for a in nodes]

    identity = list(range(n))
    best_order = identity
    best = _span_cost(identity, dist, n)

    # Seed from farthest insertion too: tighter bound when the incumbent is poorly ordered.
    # It INVERTS when pruning is already good or the span is small -- see the design doc.
    seeded = farthest_insertion_order(points, left, right)
    if seeded:
        seeded_cost = _span_cost(seeded, dist, n)
        if seeded_cost < best:
            best_order, best = seeded, seeded_cost

    order = [0] * n
    used = [False] * n

    def search(depth: int, prev: int, cost: float):
        """Pick BACK-TO-FRONT: prev starts at the right anchor and walks left."""
        nonlocal best, best_order
        if depth == n:
            total = cost + dist[prev][n]          # close against the left anchor
            if total < best:
                best, best_order = total, order[::-1]
            return
        for i in range(n):
            if used[i]:
                continue
            step = cost + dist[prev][i]
            if step >= best:                      # cannot beat the incumbent down this branch
                continue
            used[i] = True
            order[depth] = i
            search(depth + 1, i, step)
            used[i] = False

    search(0, n + 1, 0.0)
    return [] if best_order == identity else best_order


class _SpanReorderBase(Operator[PermuteChainOps]):
    """
    Rebuild a contiguous span of one route.

        _choose_span()                -> (route, start, stop)      WHERE
        _reorder(points, left, right) -> span-relative order, []   HOW

    The inheritance below marks family boundaries for ablation, not only code reuse.
    design/span_reorder/reorder_operators.md
    """

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, PermuteChain(sln))

    def _choose_span(self) -> tuple[Route, int, int] | None:
        """Route and half-open span [start, stop) to rebuild. None when nothing is selectable."""
        raise NotImplementedError

    def _reorder(self, points: Sequence[tuple[Num, Num]],
                 left: tuple[Num, Num], right: tuple[Num, Num]) -> list[int]:
        """Order `points` between the fixed endpoints. Empty list means leave it alone."""
        raise NotImplementedError

    def _operand_selection_impl(self):
        chosen = self._choose_span()
        if chosen is None:
            route = rand_choice(self.sln.all_routes)
            return route, range(0, 0), []

        route, start, stop = chosen
        path = route.path
        span = range(start, stop)
        if stop - start < 3:
            # Identity of the SPAN only. PermuteChain reports NOOP for length <= 1; a short span
            # still prices as a zero-delta move, matching RandomRoutePermutation's behaviour.
            return route, span, list(range(stop - start))

        # Fixed endpoints are OUTSIDE the span -- whatever it attaches to on each side. Falling
        # back to the depots is what makes a WHOLE-route rebuild well posed.
        left = (path[start - 1].source_customer.location if start > 0
                else route.start_depot.location)
        right = (path[stop].source_customer.location if stop < len(path)
                 else route.end_depot.location)

        # The permutation is RELATIVE to the span, so a short span in a long route costs the span,
        # not the route. No full-length identity array is built.
        order = self._reorder([path[i].source_customer.location for i in span], left, right)
        if not order:
            return route, 0, order
        return route, span, order


class _FarthestInsertionReorderBase(_SpanReorderBase):
    """
    Span rebuild by farthest insertion. Subclasses choose the span only.

    Design, cost, and the reasoning behind each variant: design/span_reorder/reorder_operators.md
    """

    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward)

        # This operator is nearly pure-exploitation, especially if used on a full route.
        # Using it for exploration can make the solution get stuck.
        self.exploit_only = True

        conservative_customer_capacity = sln.mean_customer_capacity/2
        max_vehicle_capacity = sln.max_vehicle_capacity
        conservative_vehicle_customers = 0 if abs(conservative_customer_capacity) < 1e-9 else min(len(sln.customers), max_vehicle_capacity/conservative_customer_capacity)

        self.exploit_selection_penalty_factor = 1 if abs(sln.mean_vehicle_capacity) < 1e-9 else 1.0/conservative_vehicle_customers # O(k^2) operation. Amortize cost down to ~O(k)

    def _reorder(self, points, left, right):
        return farthest_insertion_order(points, left, right)


class ReorderSpanByFarthestInsertion(_FarthestInsertionReorderBase):
    """A uniformly random span of a random route. Position and length both uniform."""
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward)
        self.exploit_selection_penalty_factor *= 4 # Average span is half a route, so average cost is half

    def _choose_span(self):
        route = self.sln.choose_random_nonempty_route_ordered()
        if route is None:
            return None
        path_len = len(route.path)
        if path_len < 3:
            return route, 0, path_len
        length = rand_int_inclusive(3, path_len)
        start = rand_int_inclusive(0, path_len - length)
        return route, start, start + length


class ReorderRandomRouteByFarthestInsertion(_FarthestInsertionReorderBase):
    """The whole of a uniformly random route, depot to depot."""

    def _choose_span(self):
        route = self.sln.choose_random_nonempty_route_ordered()
        if route is None:
            return None
        return route, 0, len(route.path)


class ReorderLongRouteByFarthestInsertion(_FarthestInsertionReorderBase):
    """
    Whole route, chosen weighted by SQUARED travel distance.

    Selection is O(total customers) per proposal -- no route caches its length. Accepted for
    now; planning/route-distance-tracking.md makes it O(1).
    """
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward)
        self.exploit_selection_penalty_factor /= 4 # Bias towards long routes increases cost.

    def _choose_span(self):
        routes = self.sln.all_routes
        if len(routes) == 0:
            return None

        # Cumulative squared distance, one weighted draw. Read-only, so it cannot permute the
        # RouteSet the way choose_random_nonempty_route does.
        cumulative, running = [], 0.0
        for route in routes:
            distance = route.total_distance()
            running += distance * distance
            cumulative.append(running)
        if running <= 0.0:
            return None

        index = bisect.bisect_left(cumulative, rand_unit() * running)
        route = routes[min(index, len(routes) - 1)]
        if route.is_empty:
            return None
        return route, 0, len(route.path)


class ReorderShortSpanExactly(_SpanReorderBase):
    """
    A random span of at most EXACT_REORDER_MAX_SPAN customers, reordered OPTIMALLY.

    Carries neither exploit_only nor a selection penalty, both deliberately.
    design/span_reorder/reorder_operators.md
    """

    def _reorder(self, points, left, right):
        return exact_span_order(points, left, right)

    def _choose_span(self):
        route = self.sln.choose_random_nonempty_route_ordered()
        if route is None:
            return None
        path_len = len(route.path)
        if path_len < 3:
            return route, 0, path_len
        length = rand_int_inclusive(3, min(path_len, EXACT_REORDER_MAX_SPAN))
        start = rand_int_inclusive(0, path_len - length)
        return route, start, start + length


class ChangeRandomEndDepot(Operator[ChangeEndDepotOps]):
    # INVALID -- by far the worst in the roster -- and every one of those is this operator picking
    # the depot the route already has, which ChangeEndDepot rejects as a no-op. The weighting then
    # prices the operator on the surviving two thirds.
    # O(1) fix, no rejection loop: draw from [0, num_depots - 2], then increment the drawn index
    # if it is >= the current end depot's index. That maps the smaller range onto "every depot
    # except the current one" with a single comparison.
    def __init__(self, sln: FullSolution, explore_reward: Num):
        self.num_depots = len(sln.depots)
        super().__init__(sln, explore_reward, ChangeEndDepot(sln))

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
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = True))

    def _operand_selection_impl(self):
        # Will dispose of all routes that do absolutely nothing: no customers served, end where they started.
        return RouteSet(route for route in self.sln.all_routes if route.should_dispose()),

class DisposeOfEmptyRoutes(Operator[DisposeOfEmptyRoutesOps]):
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, DisposeOfEmptyRoutesBL(sln, dispose_only_trivial_routes = False))

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
    def __init__(self, sln: FullSolution, explore_reward: Num):
        super().__init__(sln, explore_reward, SplitRoute(sln))

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
    def __init__(self, sln: FullSolution, explore_reward: Num, k: int = 10):
        super().__init__(sln, explore_reward, CombineRoutes(sln), random_route_pairs, k=k)