from typing import Sequence

from SimAnn_VRP_Core_Model import *
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Any, ClassVar, NamedTuple, cast
import numpy as np

from SimAnn_VRP_Core_Model import Vehicle, Route


class MoveKind(Enum):
    INVALID = auto()   # operands are illegal for this operator
    NOOP    = auto()   # operands are legal but the move changes nothing
    VALID   = auto()   # priced; deltas/improvement are meaningful


#region Operand shapes
# One alias per BL operator, naming the exact tuple its lifecycle consumes. This is the `Ops`
# type argument that ties an OperatorBL, the Move it produces, and the Operator wrapper that
# drives it into a single checked chain: declare it once on the class and every signature in the
# chain follows.
#
# Why a single tuple parameter instead of *operands: a subclass narrowing *operands to concrete
# named parameters violates Liskov (the base accepts any arguments, the override does not), which
# is what the linter was flagging across every operator. Widening the overrides with **kwargs
# silences that, but it silences it for ALL callers -- including genuine operand-shape mismatches,
# which have been a real bug category here (e.g. SplitRandomRoute once supplied
# (vehicle, route_id, split_index, depot) against a (route, split_index, depot) signature).
type ReassignRouteBeforeOps           = tuple[Route, Route | LastRoute]
type ReassignCustomerAtOps            = tuple[Route, int, Route, int]
type ReassignCustomerToNewRouteOps    = tuple[Route, int, Route | LastRoute, Depot]
type SwapCustomersAtOps               = tuple[Route, int, Route, int]
type PermuteRouteOps                  = tuple[Route, Sequence[int]]
type ChangeEndDepotOps                = tuple[Route, Depot]
type DisposeOfEmptyRoutesOps          = tuple[RouteSet]
type SplitRouteOps                    = tuple[Route, int, Depot]
type CombineRoutesOps                 = tuple[Route, Route]
#endregion


class Move[Ops: tuple](NamedTuple):
    """
    A move, as returned by evaluate(). Carries its own applied/not-applied state so callers
    (the solver, BestOfCandidates) never have to infer it out-of-band from the operator's class.

    Generic in Ops so the operand tuple stays typed all the way through
    evaluate() -> apply() -> revert(): a Move[CombineRoutesOps] can only be handed back to an
    operator that consumes CombineRoutesOps.
    """
    kind: MoveKind = MoveKind.INVALID
    # cast: the empty tuple is the only sensible default but isn't a valid value of an arbitrary
    # Ops. Only INVALID/NOOP sentinel Moves are ever constructed without operands.
    operands: Ops = cast(Any, ())
    deltas: ObjectiveTermDelta = ObjectiveTermDelta()
    improvement: Num = 0.0
    eval_version: int = -1
    # True iff evaluate() itself already performed the mutation (an _evaluates_by_applying
    # operator). When True, the solution currently reflects this move; apply() must NOT call
    # _apply_impl again, and revert() undoes it exactly like any other applied move.
    already_applied: bool = False

    @property
    def is_actionable(self) -> bool:
        return self.kind is MoveKind.VALID


class OperatorBL[Ops: tuple](ABC):
    """
    Lifecycle:  evaluate(operands) -> Move[Ops]    (PURE unless _evaluates_by_applying)
                apply(move) -> bool                (mutates; stores revert payload)
                commit() | revert()                (finalize | undo)

    Subclasses implement exactly three hooks; validity guards live in _evaluate_impl once,
    rather than duplicated across separate "compute" and "operate" methods.

    Ops is the operand tuple this operator consumes (see the aliases above). Subclasses bind it
    once -- `class SplitRoute(OperatorBL[SplitRouteOps])` -- and then destructure it in each hook.

    _evaluate_impl contract: return None (invalid) | MoveKind.NOOP (legal, no change) |
    ObjectiveTermDelta (valid, priced). Never return MoveKind.INVALID directly -- that's
    constructed internally by evaluate() when _evaluate_impl returns None.
    """

    # Set True only for operators that genuinely cannot price a move without performing it
    # (e.g. PermuteRoute, for now). Such operators mutate during evaluate(), atomically.
    _evaluates_by_applying: ClassVar[bool] = False

    def __init__(self, sln: FullSolution):
        self.sln = sln
        self._revert_info = None
        self._applied: Move[Ops] | None = None

    @property
    def is_applied(self) -> bool:
        return self._applied is not None

    # ---------------------------------------------------------------- hooks
    @abstractmethod
    def _evaluate_impl(self, operands: Ops) -> ObjectiveTermDelta | MoveKind | None:
        """PURE (unless _evaluates_by_applying). See class docstring for the return contract."""
        pass

    @abstractmethod
    def _apply_impl(self, operands: Ops):
        """Mutate the solution. RETURN the revert payload (do not assign it directly)."""
        pass

    @abstractmethod
    def _revert_impl(self, revert_info) -> None:
        """Undo exactly what _apply_impl did, given its returned payload."""
        pass

    # -------------------------------------------------------------- drivers
    def evaluate(self, operands: Ops) -> Move[Ops]:
        assert not self.is_applied, f"{type(self).__name__}.evaluate() called with a move still applied."

        if self._evaluates_by_applying:
            return self._evaluate_by_applying(operands)

        result = self._evaluate_impl(operands)
        if result is None:
            return Move(MoveKind.INVALID, operands)
        if result is MoveKind.NOOP:
            return Move(MoveKind.NOOP, operands)
        assert isinstance(result, ObjectiveTermDelta), (
            f"{type(self).__name__}._evaluate_impl returned {result!r}: expected None, "
            f"MoveKind.NOOP, or an ObjectiveTermDelta.")
        return Move(MoveKind.VALID, operands, result,
                    self.improvement_from_deltas(result), self.sln.version)

    def apply(self, move: Move[Ops]) -> bool:
        """
        Apply `move`, returning whether the solution now reflects it.

        Gatekeeps itself: re-applying the move that is already applied is a no-op. Callers can
        therefore drive the lifecycle uniformly -- apply/revert/commit with the move in hand --
        without tracking which operators happen to mutate during evaluate().
        """
        if not move.is_actionable:
            return False                        # never apply an INVALID/NOOP move
        if self._applied is move:
            return True                         # already applied (escape-hatch evaluate, or a repeat call)

        assert not self.is_applied, (
            f"{type(self).__name__}.apply() called while a DIFFERENT move is applied.")
        assert move.eval_version == self.sln.version, (
            f"Stale move for {type(self).__name__}: evaluated at version {move.eval_version}, "
            f"solution is now at {self.sln.version}.")

        self._revert_info = self._apply_impl(move.operands)
        self._applied = move
        self.sln.version += 1
        return True

    def revert(self, move: Move[Ops]) -> bool:
        """
        Undo `move` if it is the one currently applied; a no-op otherwise. Returns whether
        anything was actually undone.
        """
        if self._applied is not move:
            return False

        self._revert_impl(self._revert_info)
        self._revert_info = None
        self._applied = None
        # DECREMENT, and only when we genuinely reverted. A revert restores the exact state the
        # move was evaluated against, so the version has to return to that state's number too --
        # version identifies the state, not the number of mutations performed. Incrementing here
        # would make an apply -> revert -> apply round trip look stale and trip the guard in
        # apply(), even though the solution is provably identical. That round trip is exactly
        # what snapshotting does (see SimAnnVRPSolver.take_sln_snapshot).
        self.sln.version -= 1
        return True

    def commit(self, move: Move[Ops]) -> Move[Ops]:
        """Finalize `move` as permanent (it can no longer be reverted).
        TODO(undo-stack): once an undo stack exists, push (self, self._revert_info, move.deltas)
        here instead of discarding -- that's the whole reason this method exists separately
        from just clearing state on the next evaluate()."""
        assert self._applied is move, (
            f"{type(self).__name__}.commit() for a move that is not the applied one.")
        self._revert_info = None
        self._applied = None
        return move

    # ----------------------------------------------------------- escape hatch
    def _evaluate_by_applying(self, operands: Ops) -> Move[Ops]:
        """
        Override this (not _evaluate_impl) for operators that genuinely cannot price a move
        without performing it (_evaluates_by_applying = True). No shared "measure before/after"
        template here -- each such operator knows its own cheapest way to measure, and there's
        only ever going to be a couple of these, so a generic hook buys nothing.

        MUST: apply the move, set self._revert_info, set self._applied to the returned Move,
        bump self.sln.version by 1, and return a Move with kind=VALID and already_applied=True.
        """
        raise NotImplementedError(
            f"{type(self).__name__} sets _evaluates_by_applying=True but doesn't override "
            f"_evaluate_by_applying().")

    # ---------------------------------------------------------------- pricing
    def improvement_from_deltas(self, deltas: ObjectiveTermDelta) -> Num:
        sln = self.sln
        return deltas.get_cost_improvement(
            travel_unit_cost=sln.unit_travel_cost, vehicle_cost=sln.cost_per_vehicle,
            depot_cost=sln.cost_per_depot, overload_penalty=sln.unit_overload_penalty,
            vehicle_overload_penalty=sln.vehicle_overload_penalty)

class ReassignRouteBefore(OperatorBL[ReassignRouteBeforeOps]):
    def _evaluate_impl(self, operands: ReassignRouteBeforeOps):
        src_route, dest_route = operands
        if dest_route.vehicle is None:
            return None   # INVALID: destination unassigned

        if (src_route.is_empty or src_route is dest_route or src_route.next_route is dest_route or
                src_route.prev_route is dest_route and dest_route.is_empty): # type: ignore - prev routes are never last routes
            # No-ops for reassign to before self, to current location, or to before previous route if prev is empty
            # (if prev is empty, the op is equivalent to moving that empty route forward one - prevented)
            return None

        return src_route.cost_deltas_if_inserted_before(dest_route)

    def _apply_impl(self, operands: ReassignRouteBeforeOps):
        src_route, dest_route = operands
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-src_route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-src_route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.
        revert_info = (src_route, src_route.next_route)
        src_route.link_to_vehicle_before(dest_route)
        return revert_info

    def _revert_impl(self, revert_info):
        # Reassigns src_route back to its original vehicle and location.
        (route, successor) = revert_info
        if successor is None:
            # This branch should never happen as a nonempty route should never be linked
            route.unlink_from_vehicle()
        else:
            route.link_to_vehicle_before(successor)


class ReassignCustomerAt(OperatorBL[ReassignCustomerAtOps]):
    def _evaluate_impl(self, operands: ReassignCustomerAtOps):
        src_route, src_index, dest_route, dest_index = operands
        if src_index > len(src_route.path) - 1 or dest_index > len(dest_route.path) \
                or (src_route == dest_route and dest_index == len(dest_route.path)):
            # In the last case: you're moving within the same list - so the "last insert" is no longer valid.
            # Otherwise: can move to the end of a different src_route (to become the new last element), but not beyond it
            return None

        if src_route == dest_route and src_index == dest_index:
            return MoveKind.NOOP

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

        if src_route == dest_route:
            # An intra-route move only reorders the path, so the route's load -- and therefore both
            # load-derived terms -- cannot change. They must be forced to zero rather than summed:
            # pop-delta and insert-delta are each measured against the SAME original load, and
            # max(0, load - capacity) is nonlinear, so they don't cancel. E.g. at load == capacity
            # the pop contributes 0 and the insert contributes +demand, inventing overload that
            # never happens.
            deltas = deltas._replace(total_route_overload=0, vehicles_overloaded=0)

        return deltas

    def _apply_impl(self, operands: ReassignCustomerAtOps):
        src_route, src_index, dest_route, dest_index = operands
        revert_info = (src_route, src_index, dest_route, dest_index)
        customer = src_route.pop_customer_at(src_index)
        dest_route.insert_customer(customer, dest_index)
        return revert_info

    def _revert_impl(self, revert_info):
        src_route, src_index, dest_route, dest_index = revert_info
        # Reversing is just re-applying with source and destination swapped.
        customer = dest_route.pop_customer_at(dest_index)
        src_route.insert_customer(customer, src_index)


class ReassignCustomerToNewRouteBefore(OperatorBL[ReassignCustomerToNewRouteOps]):
    def _evaluate_impl(self, operands: ReassignCustomerToNewRouteOps):
        src_route, src_index, dest_route, end_depot = operands
        if not 0 <= src_index < src_route.num_customers or dest_route.vehicle is None:
            return None

        remove_delta = src_route.cost_deltas_if_customer_popped(src_index)

        # Gotta coppy customer sans linkages: Otherwise adding it to the new src_route will overwrite its linkages
        customer = copy.copy(src_route.path[src_index])
        new_route = Route([customer], end_depot)
        # New mid-solve route needs its depot-usage dict linked before pricing against it -
        # otherwise depot-activation deltas below would touch an unlinked route.
        new_route.link_depot_uses_except_customers(self.sln.depot_num_uses)

        add_delta = new_route.cost_deltas_if_inserted_before(dest_route)

        return add_delta + remove_delta

    def _apply_impl(self, operands: ReassignCustomerToNewRouteOps):
        src_route, src_index, dest_route, end_depot = operands
        sln = self.sln

        customer = src_route.pop_customer_at(src_index)
        new_route = Route([customer], end_depot)
        new_route.link_depot_uses_except_customers(sln.depot_num_uses)
        new_route.link_to_vehicle_before(dest_route)
        sln.all_routes.add(new_route)
        return src_route, src_index, new_route

    def _revert_impl(self, revert_info):
        sln = self.sln

        src_route, src_index, new_route = revert_info
        new_route.unlink_from_vehicle()

        src_route.insert_customer(new_route.path[0], src_index)

        # (Obsolete bug funny comment from when all_routes was an array):
        # The new src_route was most recently appended on the end. So we pop it! Like a balloon
        sln.all_routes.remove(new_route)


class SwapCustomersAt(OperatorBL[SwapCustomersAtOps]):
    def _evaluate_impl(self, operands: SwapCustomersAtOps):
        route1, index1, route2, index2 = operands
        if not (0 <= index1 < len(route1.path) and 0 <= index2 < len(route2.path)):
            return None

        if route1 == route2 and index1 == index2:
            return MoveKind.NOOP

        deltas = route1.cost_deltas_for_inter_route_customer_swap_at(index1, route2, index2)
        return deltas

    def _apply_impl(self, operands: SwapCustomersAtOps):
        route1, index1, route2, index2 = operands
        route1.swap_customers_with(index1, route2, index2)
        return route1, index1, route2, index2

    def _revert_impl(self, revert_info):
        # Reapplying the swap just swaps back.
        route1, index1, route2, index2 = revert_info
        route1.swap_customers_with(index1, route2, index2)

def invert_permutation(permutation: Sequence[int]) -> Sequence[int]:
    # This stupid fast solution was found on Stack Overflow. Poster found a ~4us runtime for 1000 entries!
    inv = np.empty_like(permutation)
    inv[permutation] = np.arange(len(inv), dtype=inv.dtype)
    return inv

class PermuteRoute(OperatorBL[PermuteRouteOps]):
    # Not yet given real delta math (planned for a later pass) - keeps computing its improvement
    # by actually applying the permutation and measuring the change, via the escape hatch.
    _evaluates_by_applying = True

    def _evaluate_impl(self, operands: PermuteRouteOps):
        pass   # unused: _evaluates_by_applying routes evaluate() through _evaluate_by_applying instead

    def _apply_impl(self, operands: PermuteRouteOps):
        route, permutation = operands
        route.permute(permutation)
        return route, invert_permutation(permutation)

    def _revert_impl(self, revert_info):
        route, inv_permutation = revert_info
        route.permute(inv_permutation)

    def _evaluate_by_applying(self, operands: PermuteRouteOps) -> Move[PermuteRouteOps]:
        # Route-local O(path length) measurement, not a full-solution objective_terms() diff.
        route, _permutation = operands
        before = route.total_distance()
        self._revert_info = self._apply_impl(operands)
        after = route.total_distance()
        deltas = ObjectiveTermDelta(travel_distance=after - before)
        move = Move(MoveKind.VALID, operands, deltas,
                    self.improvement_from_deltas(deltas), self.sln.version, already_applied=True)
        self._applied = move
        self.sln.version += 1
        return move


class ChangeEndDepot(OperatorBL[ChangeEndDepotOps]):
    def _evaluate_impl(self, operands: ChangeEndDepotOps):
        route, new_end_depot = operands
        if route.is_empty:
            return None

        # No-op condition (we disallow no-ops)
        if new_end_depot == route.end_depot:
            return None

        return route.cost_deltas_if_end_depot_changes(new_end_depot)

    def _apply_impl(self, operands: ChangeEndDepotOps):
        route, new_end_depot = operands
        old_end_depot = route.end_depot
        route.set_end_depot(new_end_depot)
        return route, old_end_depot

    def _revert_impl(self, revert_info):
        (route, old_end_depot) = revert_info
        route.set_end_depot(old_end_depot)


class DisposeOfEmptyRoutesBL(OperatorBL[DisposeOfEmptyRoutesOps]):
    # Disposes of the given routes. MUST check if they're empty before disposing!
    # If used correctly: This will never worsen the solution.
    # Disadvantage of making this separate: dest_route operators won't get credit for emptying routes.
    # Advantage of making this separate: Simplifies logic and reversion for dest_route operators,
    #   As they need not dispose of routes they empty, or revert them post-disposal.

    def __init__(self, sln: FullSolution, dispose_only_trivial_routes = True):
        super().__init__(sln)

        # This property defines whether we dispose of routes that just move from one depot to another.
        self.dispose_only_trivial_routes = dispose_only_trivial_routes

    def _evaluate_impl(self, operands: DisposeOfEmptyRoutesOps):
        (routes,) = operands
        if not routes:
            return MoveKind.NOOP

        assert all(route.is_empty for route in routes), "Cannot dispose of nonempty routes! You'll lose customers."

        if self.dispose_only_trivial_routes:
            return ObjectiveTermDelta()   # trivial routes are cost-neutral by definition

        return self.sln.cost_deltas_for_removing_empty_routes(routes)

    def _apply_impl(self, operands: DisposeOfEmptyRoutesOps):
        (routes,) = operands
        # Each item in revert stack is a tuple of [item removed, item's predecessor].
        # Thus, to revert: in reverse order, we add in the route after its predecessor.
        # NOTE: early predecessors may be removed routes later in the list!
        revert_stack: list[tuple[Route, Route|FirstRoute|None]] = [(r, r.prev_route) for r in routes]

        for route in routes:
            route.dispose()

        # Keep difference_update's record rather than using pop_all: it says where each removal
        # displaced an element, so the revert can put all_routes back in the SAME ORDER.
        # Membership alone isn't enough -- the solver draws operands positionally, so a
        # permutation here silently redirects the search.
        removed = self.sln.all_routes.difference_update(routes)
        return revert_stack, removed

    def _revert_impl(self, revert_info):
        revert_stack, removed = revert_info
        for route, prev_route in reversed(revert_stack):
            if prev_route is not None:
                route.link_to_vehicle_after(prev_route)
        self.sln.all_routes.undo_difference_update(removed)


class SplitRoute(OperatorBL[SplitRouteOps]):
    def _evaluate_impl(self, operands: SplitRouteOps):
        route, split_index, intermediate_end_depot = operands
        # To be splittable: src_route must have multiple customers (each customer to a different src_route).
        #   Index out of bounds: invalid. Index = 0 or split_index == path length => there is no customer to split.
        num_customers = route.num_customers

        if num_customers <= 1 or 0 == split_index or split_index >= num_customers:
            return None

        return route.cost_deltas_for_split_at(split_index, intermediate_end_depot)

    def _apply_impl(self, operands: SplitRouteOps):
        route, split_index, intermediate_end_depot = operands
        new_route = route.split_at(split_index, intermediate_end_depot)
        self.sln.all_routes.add(new_route)
        return route, new_route

    def _revert_impl(self, revert_info):
        route, new_route = revert_info
        route.combine_with(new_route)
        self.sln.all_routes.remove(new_route)


class CombineRoutes(OperatorBL[CombineRoutesOps]):
    # Merges route2's customers onto the end of route1 and discards route2. Not adjacency-
    # restricted -- any two non-trivial routes (in the same or different vehicles) can combine.
    def _evaluate_impl(self, operands: CombineRoutesOps):
        route1, route2 = operands
        # is_empty (zero customers), not just is_trivial (empty AND a depot round-trip): combine_with
        # appends route2's customers onto route1 and then relinks at the boundary index, which is
        # out of range whenever route2 has zero customers, trivial or not.
        if route1 is route2 or route1.is_empty or route2.is_empty:
            return None   # INVALID

        return route1.cost_deltas_for_combine_with(route2)

    def _apply_impl(self, operands: CombineRoutesOps):
        route1, route2 = operands
        split_index = route1.path_len
        # Capture route1's OWN end depot -- combine_with is about to overwrite it with route2's.
        # split_at(i, refill_depot) assigns refill_depot to the FIRST half (route1) and hands the
        # SECOND half whatever route1's end depot currently is. So to undo the combine we must
        # feed route1's original end depot back in; the rebuilt second half then inherits
        # route2's end depot automatically, since that's what route1 is carrying post-combine.
        # (Passing route2's end depot here instead is a no-op that silently leaves route1 with
        # route2's end depot forever.)
        own_end_depot = route1.end_depot
        other_prev_route = route2.prev_route
        route1.combine_with(route2)
        # combine_with only unlinks route2 from its vehicle -- it doesn't know about
        # FullSolution.all_routes, so that bookkeeping is on us (mirrors SplitRoute's add).
        # Keep the slot it vacated so revert can drop the rebuilt route straight back into it,
        # leaving all_routes in its original ORDER (the solver picks operands positionally).
        other_slot = self.sln.all_routes.remove(route2)
        return route1, split_index, own_end_depot, other_prev_route, other_slot

    def _revert_impl(self, revert_info):
        # TODO(revert-identity): restore into the ORIGINAL route2 object rather than building a
        # new one -- see the matching TODO on Route.split_at (needs its planned `into=` argument,
        # and route2 itself captured in the revert payload). Until then, revert is only
        # value-correct, not identity-correct: after an apply->revert cycle this Move's operands
        # still name the disposed route2, so re-evaluating the same Move (as the solver's
        # debug_level>=3 check does) reads a dead route.
        route1, split_index, own_end_depot, other_prev_route, other_slot = revert_info
        new_route = route1.split_at(split_index, own_end_depot)
        self.sln.all_routes.undo_remove(new_route, other_slot)
        if other_prev_route is not None:
            # split_at already linked new_route directly after route1; move it back to route2's
            # original slot (a no-op when route2 was route1's immediate successor).
            new_route.link_to_vehicle_after(other_prev_route)

# TODO(future-operator): SubPermuteRoute, using the existing (unused)
# Route.cost_deltas_for_subpermutation -- not yet decided how best to leverage this one.