#from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Operators import *
import math
import time
import random
import bisect
import itertools
import heapq


# Lowest weight an operator may hold, and the point at which it snaps back there.
# design/operator_selection/exploitation_governance.md
WEIGHT_FLOOR = 1e-10
WEIGHT_SNAP_BELOW = WEIGHT_FLOOR / 1e5


def argmin(values):
    return min(range(len(values)), key=values.__getitem__)


# Minimum share of selections each ROOT family is guaranteed, whatever its measured weight says.
# Floors apply at level 0 only -- below that, weight decides alone. Intra-route and inter-route work
# carry the solve, so most of a run belongs to them; the rest exist to stay reachable, not to
# compete. FULL_ROUTE sits above the other two because whole-route reassignment is already earning
# more than this on merit, and it becomes far more valuable once vehicle distances are gated.
# Reasoning in design/operator_selection/share_floors.md.
FAMILY_FLOOR: dict[Family, float] = {
    Family.INTRA_ROUTE:       0.25,
    Family.INTER_ROUTE:       0.25,
    Family.FULL_ROUTE:        0.02,
    Family.CHANGE_NUM_ROUTES: 0.01,
    Family.CHANGE_END_DEPOT:  0.01,
}
assert math.fsum(FAMILY_FLOOR.values()) < 1.0, "family floors must leave share for weighting"


# A tree node is one or the other.
type _TreeNode = _FamilyNode | _LeafNode


class _LeafNode:
    """One operator, hanging off the family node its path names."""
    __slots__ = ("operator", "parent", "weight", "proposed", "estimate")

    def __init__(self, operator: Operator, parent: _FamilyNode):
        self.operator: Operator = operator
        self.parent: _FamilyNode = parent
        self.weight: Num = 0.0
        self.proposed: bool = False       # set per segment by update_weights
        self.estimate: Num = 0.0          # improvement_estimate, folded and magnetised like weight


class _FamilyNode:
    """An interior node. Weight is the MAX over children.
    design/operator_selection/family_selection.md"""
    __slots__ = ("key", "children", "cum", "parent", "weight", "floor", "proposed",
                 "estimate")

    def __init__(self, key: Family | None, parent: _FamilyNode | None):
        self.key: Family | None = key            # None at the root only
        self.children: list[_TreeNode] = []
        self.cum: list[Num] = []
        self.parent: _FamilyNode | None = parent  # None at the root only
        self.weight: Num = 0.0
        self.floor: Num = 0.0                     # meaningful on root children only
        self.proposed: bool = False               # did anything in this subtree get proposed?
        self.estimate: Num = 0.0                  # MAX over children, like weight


def _fold(node: _TreeNode, adj_weights: dict[Operator, Num]) -> Num:
    """Post-order: set every weight from the leaves up, and build each cumulative array."""
    if isinstance(node, _LeafNode):
        node.weight = adj_weights[node.operator]
    else:
        for child in node.children:
            _fold(child, adj_weights)
        node.weight = max(child.weight for child in node.children)
        node.proposed = any(child.proposed for child in node.children)
        node.cum = list(itertools.accumulate(child.weight for child in node.children))
    return node.weight


def _fold_estimates(node: _TreeNode) -> Num:
    """Post-order MAX over improvement estimates. No cumulative array -- these do not drive draws."""
    if isinstance(node, _LeafNode):
        node.estimate = node.operator.improvement_estimate
    else:
        for child in node.children:
            _fold_estimates(child)
        node.estimate = max(child.estimate for child in node.children)
    return node.estimate


def _scale_subtree(node: _TreeNode, factor: Num, node_attr: str, op_attr: str) -> None:
    """Multiply one field across a whole subtree, the operators' own copies included."""
    setattr(node, node_attr, getattr(node, node_attr) * factor)
    if isinstance(node, _LeafNode):
        setattr(node.operator, op_attr, getattr(node.operator, op_attr) * factor)
        return
    for child in node.children:
        _scale_subtree(child, factor, node_attr, op_attr)


def _lift_unproposed(node: _FamilyNode, magnet: Num,
                     node_attr: str = "weight", op_attr: str = "weight") -> None:
    """
    Pull a subtree that saw no proposals toward its SIBLINGS' geometric mean, top-down.

    Siblings are the reference class. A mean over the whole roster compares operators that do
    different jobs -- see design/operator_selection/family_selection.md.

    Lifting a node has to mean something about its members, so the factor multiplies its entire
    subtree. That preserves the MAX relationship and the internal ordering.
    """
    children = node.children
    if len(children) > 1:
        values = [getattr(c, node_attr) for c in children]
        gm = math.exp(math.fsum(math.log(max(v, 1e-300)) for v in values) / len(values))
        for child, value in zip(children, values):
            if not child.proposed and value > 0.0:
                lifted = max(value, (value / gm) ** magnet * gm)
                if lifted > value:
                    _scale_subtree(child, lifted / value, node_attr, op_attr)

    # An only child gets no lift here, because a geometric mean of one value is that value. It is
    # reached through its parent instead, one level up.
    for child in children:
        if isinstance(child, _FamilyNode):
            _lift_unproposed(child, magnet, node_attr, op_attr)


def _leaves(node: _TreeNode) -> Iterator[_LeafNode]:
    """Every leaf in this subtree."""
    if isinstance(node, _LeafNode):
        yield node
        return
    for child in node.children:
        yield from _leaves(child)


def apply_share_floors(weights: Sequence[Num], floors: Sequence[Num]) -> list[Num]:
    """
    Selection shares that sum to 1, at or above each family's floor, proportional to weight where
    the floor does not bind. See design/operator_selection/share_floors.md.

    Requires sum(floors) < 1 and one positive weight. Together those guarantee a family stays
    unclamped, so the pool is never empty at the end.
    """
    n = len(weights)
    clamped = [False] * n
    free_share = 1.0                      # share left for unclamped families
    pool = math.fsum(weights)             # weight left among unclamped families

    changed = True
    while changed:
        changed = False
        for i in range(n):
            # Cross-multiplied form of  free_share * weights[i] / pool < floors[i]
            if not clamped[i] and free_share * weights[i] < floors[i] * pool:
                clamped[i] = True
                free_share -= floors[i]
                pool -= weights[i]
                changed = True

    scale = free_share / pool
    return [floors[i] if clamped[i] else weights[i] * scale for i in range(n)]


# NOTE(tuning): results of a 704-trial Optuna/TPE search over the annealing constants
# (2026-08-11). Full report in experiment_logs/tuning_report.txt; harness in tools/tune.py; raw
# trials in experiment_logs/tune_results.json. Defaults below are UNCHANGED -- this is a record, not an application.
#
#   The landscape is FLAT. Best-to-worst across the whole searched space is 3.6%, so no parameter
#   setting is going to rescue or ruin a run. The existing hand-tuned values were already within
#   3-5x of the optimum on parameters spanning 2-4 orders of magnitude, and an hour of search
#   bought 2-3%. Remaining performance is in the algorithm (operator quality, the scoring fix),
#   not in these numbers.
#
#   Only two parameters are resolvable above the noise floor (trial-to-trial stdev 0.0064):
#     initial_temp_factor   bin spread 0.0123   ~2x noise    best ~0.005  (current 0.05)
#     cooling_factor        bin spread 0.0101   ~1.6x noise  best ~0.97   (current 0.99)
#   These three show a consistent trend but under the noise floor -- weakly supported:
#     max_plateau_size      spread 0.0046   best ~1800   (current 10000)
#     plateau_reheat_factor spread 0.0046   best ~7.0    (current 2.0)
#
#   Direction, if applied: start cooler, cool faster, notice plateaus sooner, reheat harder --
#   i.e. short aggressive anneal-reheat cycles beat one long slow anneal. Measured -1.4% to -3.3%
#   against defaults on seeds never used during tuning, holding at 4x the tuning run length.
#
#   Caveat: cooling_factor is per-ITERATION, so its optimum is coupled to throughput. It survived
#   a 2x throughput change and a 4x run-length change here, but reparameterizing it as a fraction
#   of the expected budget would decouple it properly.


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
    # Every tunable constant is a constructor argument defaulting to its historical value, so
    # passing nothing reproduces the old behavior exactly. They're exposed as parameters mainly
    # so tools/tune.py can search over them -- see that file for the current best-known settings
    # and the caveats on which ones are worth tuning yet.
    def __init__(self, sln: FullSolution, max_time: float = 120,
                 *,
                 segment_length: int = 100,
                 reaction_factor: float = 0.01,
                 cooling_factor: float = 1 - 1e-4,
                 initial_temp_factor: float = 1e-4, # exploit first
                 max_plateau_size: int = 1000,
                 plateau_reheat_exponent: float = 0.2,
                 empty_route_cleanup_interval: int = 100,
                 explore_reward: Num = 1e-5,
                 Bayes_magnet: Num = 0.997,
                 statistic_reaction_factor: Num = -1,
                 ):
        self.sln = sln
        self.operators: list[Operator] = []

        self.segment_length = segment_length
        # Shrinkage exponent for the sibling magnet. Closer to 1 pulls more weakly.
        # design/operator_selection/family_selection.md
        self.Bayes_magnet = Bayes_magnet
        # EMA rate for the shrunk rate estimates. Negative means "track reaction_factor",
        # so the two knobs are independent only when someone sets this one.
        self.statistic_reaction_factor = (reaction_factor if statistic_reaction_factor < 0
                                         else statistic_reaction_factor)
        self.reaction_factor = reaction_factor
        self.max_time = max_time

        #self.cooling_factor = 0.93304 # Factor per 100 iterations
        self.cooling_factor = cooling_factor # Factor per iteration
        self.log_cooling_factor = math.log2(self.cooling_factor)
        self.temperature = 0.0
        self.log_temperature = -100.0

        # Starting temperature, as a fraction of the initial solution's objective (see solve()).
        self.initial_temp_factor = initial_temp_factor

        self.explore_reward = explore_reward

        self.curr_plateau_size = 0
        self.max_plateau_size = max_plateau_size
        self.plateau_reheat_exponent = plateau_reheat_exponent # Fractional exponent of "reheat to this factor of plateau start"

        self.best_objective = float("inf")
        self.curr_objective = float("inf")
        self.index_in_segment = 0

        self.elapsed_time = 0.0
        self.num_reports_so_far = 0.0
        self.report_every = 1.0

        self.operators.extend((
            RandomRouteReassignment(sln, explore_reward),
            RandomCustomerReassignment(sln, explore_reward),
            RandomCustomerChainReassignment(sln, explore_reward),
            ReassignClosestChainWithRandomCustomer(sln, explore_reward),
            ReassignClosestChainNextToNeighbor(sln, explore_reward),
            ReassignChainNextToNeighbor(sln, explore_reward),
            SwapChainsWithNeighbor(sln, explore_reward),
            ReverseClosestPairTogether(sln, explore_reward),
            RandomCustomerChainReversal(sln, explore_reward),
            RandomCustomerSwap(sln, explore_reward),
            RandomSameLengthChainSwap(sln, explore_reward),
            RandomChainSwap(sln, explore_reward),
            SwapRouteHeadsAtSharedDepot(sln, explore_reward),
            SwapRouteTailsAtSharedDepot(sln, explore_reward),
            CustomerBestOfkSwapInRandomRoute(sln, explore_reward),
            CustomerBestOfkNeighborSwapInRandomRoute(sln, explore_reward),
            RandomRoutePermutation(sln, explore_reward),
            ReorderSpanByFarthestInsertion(sln, explore_reward),
            ReorderRandomRouteByFarthestInsertion(sln, explore_reward),
            ReorderLongRouteByFarthestInsertion(sln, explore_reward),
            ReorderShortSpanExactly(sln, explore_reward),
            ChangeRandomEndDepot(sln, explore_reward),
            SplitRandomRoute(sln, explore_reward),
            CombineRandomRoutes(sln, explore_reward)
        ))

        operators = self.operators
        self.adj_weights: dict[Operator, Num] = {
            op: op.exploit_selection_penalty_factor * op.penalty for op in operators}
        self._build_family_tree()

        # DisposeOfEmptyRoutes / DisposeOfTrivialRoutes are deliberately NOT in the weighted
        # roster: disposal already happens unconditionally every empty_route_cleanup_interval
        # iterations and again before every snapshot (see _cleanup_empty_routes and
        # take_sln_snapshot), so selecting them here only re-does work that is already guaranteed.
        # Their operand selection is also O(routes) -- it rescans all_routes on every proposal --
        # so they were consuming a large share of iterations to accomplish nothing new.
        # TODO(known-bug): ReassignCustomerToNewRouteBefore's pricing is wrong for the throwaway
        # new-route case (it prices a "swap" from a VirtualDepot placeholder start, but a brand
        # new route never had a real old start to swap from). Needs a purpose-built Core delta
        # function rather than reusing cost_deltas_if_inserted_before. Disabled until fixed.
        # self.operators.append(ReassignWorstCustomerOutOfRandomKToNewRoute(sln, explore_reward, k=10))
        # self.operators.append(RandomCustomerReassignmentToNewRoute(sln, explore_reward))

        self.snapshots: list[tuple[float, FullSolution]] = []
        self.max_snapshots = 10

        self.num_complete_reheats = 0
        self.num_plateau_reheats = 0

        # Every this-many iterations, dispose of any empty routes outright rather than waiting
        # for weighted operator selection to stochastically pick DisposeOfEmptyRoutes -- since
        # all objective coefficients are non-negative, this is never a net loss.
        self.empty_route_cleanup_interval = empty_route_cleanup_interval
        # The Operator wrapper, not the bare OperatorBL: it owns the already_applied bookkeeping
        # that _dispose_empty_routes / take_sln_snapshot depend on. Kept OUT of self.operators, so
        # it is never selected by weight and never reaches update_weights.
        self._dispose_op = DisposeOfEmptyRoutes(sln, explore_reward)

    def set_deterministic_weighting(self, deterministic: bool = True):
        """
        Make operator weighting ignore wall-clock timing, so a run is reproducible from its seed.
        FOR TESTING AND BISECTION ONLY -- leave it off in production.

        Normal weighting divides an operator's score by its measured mean cost per move, which is
        genuinely valuable: it steers selection toward the best improvement-per-second rather than
        the best improvement-per-move. The side effect is that the search trajectory depends on
        machine speed and CPU state, so two runs from the same seed diverge -- which is fine for a
        stochastic solver, but makes an intermittent bug impossible to reproduce or bisect.

        With this on, every operator's mean cost is taken as 1, so selection depends only on the
        improvements achieved. Everything else (the RNG stream, the acceptance test, operand
        selection) is already seed-determined, so this is the last input needed to make a run a
        pure function of its seed.
        """
        for op in self.operators:
            op.weight_by_time = not deterministic

    def _build_family_tree(self) -> None:
        """
        Build the family tree from each operator's path.
        design/operator_selection/family_selection.md

        Sub-families are created before any leaf is attached, so a node lists its sub-families
        first and its own operators after. That ordering decides which child a draw selects.
        """
        root = _FamilyNode(None, None)
        by_prefix: dict[tuple[Family, ...], _FamilyNode] = {(): root}

        def node_for(prefix: tuple[Family, ...]) -> _FamilyNode:
            node = by_prefix.get(prefix)
            if node is None:
                parent = node_for(prefix[:-1])
                node = _FamilyNode(prefix[-1], parent)
                parent.children.append(node)
                by_prefix[prefix] = node
            return node

        for op in self.operators:
            path = getattr(type(op), "family", None)
            assert isinstance(path, tuple) and path,                 f"{type(op).__name__} is in the roster with no family path"
            node_for(path)

        for op in self.operators:
            parent = by_prefix[type(op).family]
            parent.children.append(_LeafNode(op, parent))

        # A missing floor would read as "no guarantee" when it means the table was not updated.
        missing: list[str] = []
        for child in root.children:
            assert isinstance(child, _FamilyNode) and child.key is not None,                 "a root child must be a family"
            if child.key not in FAMILY_FLOOR:
                missing.append(child.key.name)
            else:
                child.floor = FAMILY_FLOOR[child.key]
        assert not missing, f"root families with no floor: {sorted(missing)}" 

        self.family_root: _FamilyNode = root
        self.leaf_of: dict[Operator, _LeafNode] = {
            leaf.operator: leaf for leaf in _leaves(root)}

        # Selection starts before the first update_weights, so the cumulative arrays have to be
        # populated here rather than only per segment.
        self.refresh_family_tree()

    def _resolve_node(self, target: _TreeNode | tuple[Family, ...] | type) -> _TreeNode:
        """A tree node from a family path tuple, an Operator subclass, or a node itself."""
        if isinstance(target, (_FamilyNode, _LeafNode)):
            return target
        if isinstance(target, tuple):
            node: _FamilyNode = self.family_root
            for key in target:
                found = None
                for child in node.children:
                    if isinstance(child, _FamilyNode) and child.key is key:
                        found = child
                        break
                assert found is not None, f"no family node at path {target}"
                node = found
            return node
        if isinstance(target, type) and issubclass(target, Operator):
            for leaf in _leaves(self.family_root):
                assert isinstance(leaf, _LeafNode)
                if type(leaf.operator) is target:
                    return leaf
            raise AssertionError(f"{target.__name__} is not in the roster")
        raise TypeError(f"cannot remove {target!r}: want a path tuple, an Operator subclass, "
                        f"or a tree node")

    def remove(self, target: _TreeNode | tuple[Family, ...] | type) -> list[Operator]:
        """Detach an operator or a whole family; return the operators removed.
        design/operator_selection/family_selection.md"""
        node = self._resolve_node(target)
        parent = node.parent
        assert parent is not None, "cannot remove the tree root"

        gone: list[Operator] = [leaf.operator for leaf in _leaves(node)]
        parent.children.remove(node)
        for op in gone:
            self.adj_weights.pop(op, None)
            self.operators.remove(op)

        while parent.parent is not None and not parent.children:
            grandparent = parent.parent
            grandparent.children.remove(parent)
            parent = grandparent

        assert self.family_root.children, "every family was removed"
        self.refresh_family_tree()
        return gone

    def refresh_family_tree(self) -> None:
        """
        Recompute node weights and the cumulative arrays selection descends. Once per segment.
        A node's weight is the MAX over its children -- design/operator_selection/family_selection.md.
        """
        root = self.family_root
        adj_weights = self.adj_weights
        for child in root.children:
            _fold(child, adj_weights)

        # Floors bind at level 0 only. Below the root, weight decides alone.
        weights: list[Num] = []
        floors: list[Num] = []
        for child in root.children:
            assert isinstance(child, _FamilyNode), "a root child must be a family"
            weights.append(child.weight)
            floors.append(child.floor)
        root.cum = list(itertools.accumulate(apply_share_floors(weights, floors)))

    def update_weights(self):
        # Global: total collapse is a whole-roster condition, not a per-family one.
        reheat = 1e5 if max(op.weight for op in self.operators) <= 1e-10 else 1
        total_proposals = 0
        total_accepts = 0
        improving_moves = 0

        adj_weights = self.adj_weights
        for op in self.operators:
            weight = op.weight
            (num_proposals, num_accepts, num_improvements, score_sum) = op.get_stats()
            p = self.reaction_factor
            proposed = num_proposals > 0
            if proposed:
                average_score = score_sum / num_proposals if score_sum > 0 else 0
                weight = reheat*((1 - p) * weight + p * average_score)
            else:
                weight = reheat*weight      # the magnet runs on the TREE, below

            # Fires on collapse, not on decay. See exploitation_governance.md.
            if weight < WEIGHT_SNAP_BELOW:
                weight = WEIGHT_FLOOR

            if proposed:
                # Shrunk rate estimates. Denominator is PROPOSALS: a random operator is cheap but
                # rarely improves, and that is the signal. planning/scoring-rework.md
                q = self.statistic_reaction_factor
                op.improvement_estimate = max(
                    (1 - q) * op.improvement_estimate + q * (num_improvements / num_proposals),
                    ESTIMATE_FLOOR)

            op.weight = weight
            adj_weights[op] = weight * op.exploit_selection_penalty_factor * op.penalty
            self.leaf_of[op].proposed = proposed

            total_proposals += num_proposals
            total_accepts += num_accepts
            improving_moves += num_improvements

            op.reset_stats()

        # Magnet, sibling-local. Fold first so every node carries a weight and knows whether its
        # subtree was proposed, lift the unproposed ones, then push the lifted weights back into
        # adj_weights before the final fold. design/operator_selection/family_selection.md
        root = self.family_root
        for child in root.children:
            _fold(child, adj_weights)
        _lift_unproposed(root, self.Bayes_magnet)
        for op in self.operators:
            adj_weights[op] = op.weight * op.exploit_selection_penalty_factor * op.penalty

        # The improvement estimate takes the same treatment: MAX up the tree, and an unproposed
        # subtree shrinks toward its siblings rather than toward the whole roster.
        for child in root.children:
            _fold_estimates(child)
        _lift_unproposed(root, self.Bayes_magnet, "estimate", "improvement_estimate")

        # Dynamic penalty, from the MAGNETISED estimates. Normalisation is GLOBAL on purpose: a
        # family's weight is its best member's ADJUSTED weight and that carries to the root, so a
        # per-family maximum would make weights mean different things across families.
        # planning/scoring-rework.md
        improvement_scores = [max(op.improvement_estimate / op.scoring_cost,
                                  IMPROVEMENT_SCORE_FLOOR) for op in self.operators]
        best = max(improvement_scores)
        for op, improvement_score in zip(self.operators, improvement_scores):
            op.penalty = improvement_score / best
            adj_weights[op] = (op.weight * op.exploit_selection_penalty_factor * op.penalty)

        self.refresh_family_tree()

        if improving_moves == 0:
            self.curr_plateau_size += 1
            if self.curr_plateau_size >= self.max_plateau_size:
                self.curr_plateau_size = 0
                # Reheat factor = plateau_reheat_factor / (max_size^cooling factor). Undoes cooling during plateau, then reheats by the cooling factor.
                #log_reheat_factor = math.log(self.plateau_reheat_factor, 2) - self.segment_length*self.max_plateau_size*self.log_cooling_factor
                #self.log_temperature += log_reheat_factor
                # Simpler reheat factor: Given root from max, in log-space: we multiply range (obj-temp) by p. So: temp += (1-p)(obj-temp)
                self.log_temperature += (1-self.plateau_reheat_exponent)*(math.log2(self.curr_objective)-self.log_temperature)
                self.num_plateau_reheats += 1
        else:
            self.curr_plateau_size = 0



    def choose_operator(self) -> Operator:
        """Descend the tree, sampling among siblings in proportion to weight at each level.
        design/operator_selection/family_selection.md"""
        node: _TreeNode = self.family_root
        while not isinstance(node, _LeafNode):
            cum = node.cum
            node = node.children[bisect.bisect_left(cum, rand_unit() * cum[-1])]

        return node.operator

    # TODO(warm-start): add a third constructor that loads a saved solution instead of building
    # one, so a run can resume from a recorded best rather than from the greedy sweep.
    # solutions/*.json already carries everything needed: for each route a start depot, an ordered
    # customer ID list, an end depot, and a vehicle. The loader walks the routes in file order,
    # builds Route([CustomerVisit(customers[cID]) for cID in path], ...), calls set_end_depot, and
    # calls sln.add_route_to_vehicle. File order matters -- the routes of one vehicle are
    # consecutive and chain depot to depot, so appending in order satisfies the chaining invariant
    # for free. Then set best_objective and curr_objective from sln.solution_cost(), as below.
    # Check the saved instance descriptor (numpy_seed, depots, vehicles, costs) against the live
    # instance first. A solution loaded onto a different instance is silently wrong.

    # We design the solution, initialization, and operators so that at all stages, all customers show up in the src_route.
    def make_initial_solution(self):
        sln = self.sln
        depots = sln.depots
        customers = sln.customers

        vehicles = sln.vehicles

        # A set for O(1) membership, since the neighbor walks below test it once per candidate.
        # The FULL customer list stays the iteration order for every fallback scan: `customers` is
        # in cID order, so "first remaining" means "lowest cID among remaining" -- exactly the tie
        # rule argmin used before, and what keeps the constructed solution bit-identical.
        remaining = set(customers)

        def _first_remaining_from(anchor, row, source_list):
            """
            First entry of a precomputed neighbor row that is still unassigned, or None.

            Trusted only when the hit is STRICTLY nearer than the row's last entry, or the row
            already spans everything. A row holds the k smallest distances with ties broken
            arbitrarily at the cut, so a hit merely TIED with the last entry may have a lower-cID
            twin that fell outside the row. Strictly nearer means every node at that distance or
            less is inside the row; the row is ordered by (distance, index), so the first remaining
            entry is then exactly what argmin would have returned.

            Comparing against the last entry's distance, not its identity: several entries can share
            one distance, and an identity check would wave those through.
            """
            if not row:
                return None

            complete = len(row) >= len(source_list) - 1
            cutoff = anchor.distance(source_list[row[-1]])
            for index in row:
                candidate = source_list[index]
                if candidate in remaining:
                    if complete or anchor.distance(candidate) < cutoff:
                        return candidate
                    return None
            return None

        def get_closest_depot(customer: Customer):
            # Rows break ties by index, so this matches argmin's lowest-dID choice.
            return depots[sln.customer_depots[customer.cID][0]]

        def get_closest_remaining_customer_to_customer(customer: Customer) -> Customer:
            hit = _first_remaining_from(customer, sln.neighbors[customer.cID], customers)
            if hit is not None:
                assert isinstance(hit, Customer)
                return hit
            # Row exhausted, or the only hit was tied with the cut. Fall back to the original scan.
            return min((other for other in customers if other in remaining),
                       key=customer.distance)

        def get_closest_remaining_customer_to_depot(vehicle: Vehicle) -> tuple[Customer, Num]:
            depot = vehicle.final_depot
            row = sln.depot_neighbors[depot.dID]
            while True:
                hit = _first_remaining_from(depot, row, customers)
                if hit is not None:
                    assert isinstance(hit, Customer)
                    return hit, depot.distance(hit)
                # Widen this depot's row rather than dropping to a scan: depots are few, so the
                # rebuild is cheap and every later route start stays O(1).
                if not sln.grow_depot_neighbors(depot.dID):
                    break
                row = sln.depot_neighbors[depot.dID]

            best = min((customer for customer in customers if customer in remaining),
                       key=depot.distance)
            return best, depot.distance(best)

        def get_closest_remaining_service():
            closest_customers = [(v,)+get_closest_remaining_customer_to_depot(v) for v in vehicles]
            # Tuples at this point have values (vehicle, customer, distance)
            return min(closest_customers, key = lambda kvp: kvp[2])

        def add_next_route():
            (vehicle, customer1, _) = get_closest_remaining_service()
            remaining.discard(customer1)
            # End depot isn't decided until the route is full; DEFAULT_DEPOT is a harmless
            # placeholder always replaced by set_end_depot below before the route is used.
            route = Route([CustomerVisit(customer1)], DEFAULT_DEPOT)

            if remaining:
                next_customer = get_closest_remaining_customer_to_customer(customer1)
                capacity_so_far = customer1.demand
                next_capacity = next_customer.demand

                can_add_route = lambda : capacity_so_far + next_capacity <= vehicle.capacity

                while remaining and can_add_route():
                    route.append_customer(CustomerVisit(next_customer))
                    capacity_so_far += next_customer.demand
                    remaining.discard(next_customer)

                    if not remaining:
                        break

                    next_customer = get_closest_remaining_customer_to_customer(next_customer)
                    next_capacity = next_customer.demand

            # NOTE: Assumes that any vehicle has enough capacity to serve any single customer.
            route.set_end_depot(get_closest_depot(route.path[-1]))

            sln.add_route_to_vehicle(route, vehicle)

        while remaining:
            add_next_route()

        self.best_objective = sln.solution_cost()
        self.curr_objective = self.best_objective

    def make_dumb_initial_solution(self):
        sln = self.sln
        new_route = Route([], end_depot=sln.depots[0])

        for customer in sln.customers:
            new_route.append_customer(CustomerVisit(customer))

        sln.add_route_to_vehicle(new_route, sln.vehicles[0])


        self.best_objective = sln.solution_cost()
        self.curr_objective = self.best_objective

    def _dispose_empty_routes(self) -> Move | None:
        """
        Dispose every empty route, WITHOUT committing, and return the move (None if there was
        nothing to do). Leaving it uncommitted is what lets take_sln_snapshot() undo it again.
        Callers that want the disposal to stick must commit it -- see _cleanup_empty_routes.

        Driven through the Operator wrapper, not the bare OperatorBL. The wrapper owns the
        already_applied bookkeeping, so going around it meant the caller had to call
        mark_applied() by hand -- and any path that forgot left the move and the operator
        disagreeing about whether it was applied.

        Deliberately evaluate_dispose_all() rather than propose(), and the untimed apply()/revert()
        rather than apply_for_acceptance()/revert_and_reject(). This is unconditional maintenance,
        not a weighted proposal, so it must not add to segment_time, segment_proposals or the
        reporting counters -- those feed a cost model this operator never competes in.
        """
        move = self._dispose_op.evaluate_dispose_all()
        if move.kind != MoveKind.VALID:
            return None

        self._dispose_op.apply(move)
        return move

    def _cleanup_empty_routes(self):
        # Unconditional maintenance: since every objective coefficient is non-negative, removing
        # an empty route's travel/depot footprint is never a net loss. Called directly rather than
        # through weighted operator selection -- DisposeOfEmptyRoutes is deliberately absent from
        # self.operators (see __init__), so this wrapper's stats never reach update_weights.
        move = self._dispose_empty_routes()
        if move is None:
            return

        self._dispose_op.commit(move)
        self.curr_objective -= move.improvement
        self.best_objective = min(self.best_objective, self.curr_objective)

    @staticmethod
    def _check_solution_invariants(sln: FullSolution) -> list[str]:
        # debug_level >= 2 structural checks, lifted from the old inline blocks and adapted to
        # walk prev_route/next_route chains instead of RouteSet.index (which doesn't exist).
        problems = []

        depot_breakdown = sln.depot_usage_breakdown()
        # Sorted membership, not RouteSet order: removal is swap-with-last, so order churn is
        # expected and is not a defect.
        def depot_members(route_set):
            return sorted(str(route) for route in route_set)

        if any(depot_members(depot_breakdown[depot]) != depot_members(sln.depot_route_starts[depot])
               for depot in sln.depots):
            problems.append("depot usage breakdown disagrees with depot_route_starts")

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
        initial_temp = self.initial_temp_factor * self.best_objective
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
        #     verify the rejection would have been valid had it been accepted. Only ever accepts
        #     to moves that reached the accept/reject test (move.kind is VALID) -- INVALID/NOOP
        #     moves never reach that branch and must never be applied.
        #debug_level = 0

        pre_propose_obj = 0
        #post_propose_obj = 0

        iterations_since_last_recompute = 0
        iterations_between_recomputes = 10000

        while elapsed_time < self.max_time:
            self.log_temperature += self.log_cooling_factor
            iterations += 1
            iterations_since_last_recompute += 1

            if iterations_since_last_recompute >= iterations_between_recomputes:
                iterations_since_last_recompute = 0
                self.curr_objective = sln.solution_cost()

            if iterations % self.segment_length == 0:
                self.update_weights()

            if iterations % self.empty_route_cleanup_interval == 0:
                self._cleanup_empty_routes()

            op = self.choose_operator()

            if debug_level >= 1:
                pre_propose_obj = sln.solution_cost()

            move = op.propose()

            if not move.is_actionable:
                assert not move.already_applied, f"{type(op).__name__}: A non-actionable move was applied!"
                elapsed_time = time.time() - start_time
                continue

            if debug_level >= 1 and move.already_applied:
                post_propose_obj = sln.solution_cost()
                if abs(move.improvement - (pre_propose_obj - post_propose_obj)) >= 1e-6:
                    print(f"[debug] {type(op).__name__} (escape-hatch): reported improvement {move.improvement} "
                          f"!= measured {pre_propose_obj - post_propose_obj}")

            improvement = move.improvement
            loglog_acceptance_threshold = -float('inf') if improvement >= 0 else math.log(-improvement, 2) - self.log_temperature
            accept = improvement > 0 or (not op.exploit_only and math.log(-math.log(rand_unit()), 2) >= loglog_acceptance_threshold)

            if isinstance(op, CombineRandomRoutes):
                pass

            if accept:
                # Apply FIRST, so the debug_level 1 check brackets a clean before/after. apply()
                # gatekeeps itself, so this is a no-op when propose() already mutated.
                if isinstance(op, CombineRandomRoutes):
                    pass

                if debug_level >= 1 and not move.already_applied:
                    pre_op_obj = sln.solution_cost()
                    op.apply_for_acceptance(move)
                    post_op_obj = sln.solution_cost()
                    if abs(improvement - (pre_op_obj - post_op_obj)) >= 1e-6:
                        print(f"[debug] {type(op).__name__}: reported improvement {improvement} "
                              f"!= measured {pre_op_obj - post_op_obj}")
                else:
                    op.apply_for_acceptance(move)

                curr_objective = self.curr_objective
                best_objective = self.best_objective
                if improvement < 0 and curr_objective <= best_objective + 1e-12:
                    # Error-safe comparison of current and best objectives - relative error as abs/ave
                    # We're about to step away from the running global optimum, so snapshot it.
                    # Step back off the move first: the snapshot must capture the state we are
                    # LEAVING, not the one we're moving to. This round trip is exact -- revert()
                    # decrements sln.version and take_sln_snapshot() undoes its own disposal, so
                    # the re-apply lands back on move.eval_version rather than looking stale.
                    op.revert(move)
                    self.take_sln_snapshot(curr_objective, debug_level = debug_level)
                    op.apply(move)

                if debug_level >= 2:
                    problems = self._check_solution_invariants(sln)
                    if problems:
                        print(f"[debug] invariant violations after accepted {type(op).__name__}: {problems}")

                op.commit(move)
                op.update_stats_for_accept()

                self.curr_objective -= improvement
                self.best_objective = min(best_objective, curr_objective)
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
                    op.revert_and_reject(move)   # something is applied at this point either way
                    recompute = op.evaluate(move.operands)
                    op.revert(recompute)

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
                    op.revert_and_reject(move)   # gatekeeps itself: a no-op if it was never applied

                if debug_level >= 2:
                    problems = self._check_solution_invariants(sln)
                    if problems:
                        print(f"[debug] invariant violations after rejected {type(op).__name__}: {problems}")

                op.update_stats_for_reject()

            if len(self.snapshots) > 2*self.max_snapshots:
                self.pare_snapshots_to_top_k(self.max_snapshots)

            curr_time = time.time()
            elapsed_time = curr_time - start_time

            if elapsed_time > self.report_every * self.num_reports_so_far:
                self.num_reports_so_far += 1
                print(f"Elapsed time: {elapsed_time:.2f} seconds, Best objective: {self.best_objective:.2f}, Current objective: {self.curr_objective:.2f}")
                print(f"Log2 Temperature: {self.log_temperature:.2f}, Complete reheats: {self.num_complete_reheats}, Plateau reheats: {self.num_plateau_reheats}, Iterations: {iterations}")

                # Floored: a weight reaches exactly 0 when reaction_factor is 1, and a report
                # line must never be able to kill a run.
                print("op weights:" + str([(type(op).__name__, math.log(max(op.weight, 1e-300), 10))
                                           for op in self.operators]))

        self.num_reports_so_far += 1
        print(f"Elapsed time: {elapsed_time:.2f} seconds, Best objective: {self.best_objective:.2f}, Current objective: {self.curr_objective:.2f}")
        print(f"Log2 Temperature: {self.log_temperature:.2f}, Complete reheats: {self.num_complete_reheats}, Iterations: {iterations}")

        for op in self.operators:
            op.report_stats()

        self.take_sln_snapshot(self.curr_objective, debug_level=debug_level)

        self.pare_snapshots_to_top_k(self.max_snapshots)

    def take_sln_snapshot(self, curr_objective: Num | None = None, debug_level: int = 0):
        """
        Store a NORMALISED copy of the current solution: every empty route disposed, and every
        remaining route assigned to a vehicle. Anyone reading a snapshot can then rely on that
        without filtering or special-casing.

        The disposal is undone again immediately afterwards, so the live solution -- and any Move
        evaluated against it -- is exactly as it was. Only the stored copy is normalized, which is
        what keeps this safe to call with a move in flight: disposing empty routes would otherwise
        invalidate operands (ReassignCustomerAt and ReassignRouteBefore both accept an empty
        dest_route) as well as move the version out from under it.
        """
        dispose_move = self._dispose_empty_routes()
        if dispose_move is not None and dispose_move.is_actionable:
            # We're not going through a true Operator so we have to do the already_apoplied bookkeeping ourselves here.
            dispose_move.mark_applied(True)
        try:
            unassigned = [route for route in self.sln.all_routes if not route.is_assigned]
            assert not unassigned, (
                f"Cannot snapshot: {len(unassigned)} route(s) hold customers but are not assigned "
                f"to a vehicle ({', '.join(str(route) for route in unassigned[:3])}). Empty routes "
                f"were just disposed, so anything left unassigned violates the solver invariant "
                f"'between moves, every nonempty route is assigned to a vehicle'.")

            # If a route was disposed and an objective was passed in: subtract off the cost savings from disposal
            curr_objective = curr_objective if curr_objective is None or dispose_move is None else curr_objective - dispose_move.improvement

            if debug_level >= 1 and curr_objective is not None:
                # Validate current objective values for all snapshots
                cost = self.sln.solution_cost()
                if abs(curr_objective - cost) >= 1e-8+1e-10*max(abs(curr_objective), abs(cost)): # Abs+rel error
                    assert curr_objective is not None # Linter is dum-dum so add this dum-dum assert for dum-dum linter
                    print(
                        f"WARNING: Computed objective for a stored snapshot does NOT match its stored objective:\n"
                        f"Stored: {curr_objective}, Actual: {self.sln.solution_cost()}")

            self.snapshots.append(self.sln.take_snapshot(curr_objective))
        finally:
            # Restore even if the assert fires, so a failing run is still inspectable.
            if dispose_move is not None:
                self._dispose_op.revert(dispose_move)

    def pare_snapshots_to_top_k(self, k):
        # Pares and sorts snapshots
        self.snapshots = heapq.nsmallest(k, self.snapshots, key=lambda x: x[0])

    def get_best_snapshot(self):
        return self.snapshots[0]

