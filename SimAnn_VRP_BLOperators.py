from typing import Sequence

from SimAnn_VRP_Core_Model import *
from abc import ABC, abstractmethod
from enum import Enum, auto
from dataclasses import dataclass
from typing import Any, ClassVar, cast
import numpy as np

from SimAnn_VRP_Core_Model import Vehicle, Route, LastRoute, Depot, FirstRoute


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
# Trailing bool is the reverse decision, filled in by evaluate() -- see _evaluates_in_batch.
type ReassignCustomerChainOps         = tuple[Route, Chain, Route, int, bool]
type ReassignCustomerToNewRouteOps    = tuple[Route, int, Route | LastRoute, Depot]
# Trailing bools are the two reverse decisions, filled by evaluate() -- see _evaluates_in_batch.
type SwapCustomerChainsOps            = tuple[Route, Chain, Route, Chain, bool, bool]
type ReverseCustomerChainOps          = tuple[Route, Chain]
type PermuteRouteOps                  = tuple[Route, Sequence[int]]
type ChangeEndDepotOps                = tuple[Route, Depot]
type DisposeOfEmptyRoutesOps          = tuple[RouteSet]
type SplitRouteOps                    = tuple[Route, int, Depot]
type CombineRoutesOps                 = tuple[Route, Route]
#endregion


@dataclass(frozen=True, slots=True, eq=False)
class Move[Ops: tuple]:
    """
    A move, as returned by evaluate(). Carries its own applied/not-applied state so callers
    (the solver, BestOfCandidates) never have to infer it out-of-band from the operator's class:
    "was this move applied?" is answered by asking the move, not by interrogating the operator.
    That's what lets Operator gatekeep the lifecycle without threading boolean returns back out
    of apply()/revert().

    Generic in Ops so the operand tuple stays typed all the way through
    evaluate() -> apply() -> revert(): a Move[CombineRoutesOps] can only be handed back to an
    operator that consumes CombineRoutesOps.

    MUTABILITY: exactly one field, already_applied, is mutable, and only via mark_applied().
    Everything else is frozen -- the priced result of evaluate() must never drift after the fact.
    Mutating in place rather than rebuilding is load-bearing, not a convenience: OperatorBL
    gatekeeps on `self._applied is move`, so producing a new object to change the flag silently
    breaks that identity check (which is exactly how a committed move stopped matching the
    applied one). eq=False keeps == as identity too, so there is no second notion of "same move".
    """
    kind: MoveKind = MoveKind.INVALID
    # cast: the empty tuple is the only sensible default but isn't a valid value of an arbitrary
    # Ops. Only INVALID/NOOP sentinel Moves are ever constructed without operands.
    operands: Ops = cast(Any, ())
    deltas: ObjectiveTermDelta = ObjectiveTermDelta()
    improvement: Num = 0.0
    # Solution version recorded BEFORE the move is applied
    eval_version: int = -1
    # True iff the solution currently reflects this move -- either because an
    # _evaluates_by_applying operator mutated during evaluate(), or because apply() ran since.
    already_applied: bool = False

    @property
    def is_actionable(self) -> bool:
        return self.kind is MoveKind.VALID

    def mark_applied(self, applied: bool) -> None:
        """
        The ONLY sanctioned mutation on a Move; every other field raises FrozenInstanceError.

        object.__setattr__ is the standard frozen-dataclass escape hatch. It's deliberate and
        deliberately narrow: one named method, trivial to grep, so any future divergence between
        a move's own state and OperatorBL._applied has exactly one place to have come from.
        """
        object.__setattr__(self, "already_applied", applied)

class OperatorBL[Ops: tuple](ABC):
    """
    Lifecycle:  evaluate(operands) -> Move[Ops]    (PURE unless _evaluates_by_applying)
                                                   (see _evaluates_in_batch for operand fill-in)
                apply(move) -> bool                (mutates; stores revert payload)
                commit() | revert()                (finalize | undo)

    Subclasses implement exactly three hooks; validity guards live in _evaluate_impl once,
    rather than duplicated across separate "compute" and "operate" methods.

    Ops is the operand tuple this operator consumes (see the aliases above). Subclasses bind it
    once -- `class SplitRoute(OperatorBL[SplitRouteOps])` -- and then destructure it in each hook.

    _evaluate_impl contract: return (deltas, kind, *decisions).
      deltas    -- ObjectiveTermDelta when kind is VALID, None otherwise.
      kind      -- INVALID (operands illegal) | NOOP (legal, changes nothing) | VALID (priced).
      decisions -- only when _evaluates_in_batch; see that flag.

    One return shape for every operator, so evaluate() has a single path. The two flags below are
    independent and neither one gets its own overridable hook: an operator that prices by mutating
    and an operator that decides during pricing are still just _evaluate_impl.
    """

    # Set True only for operators that genuinely cannot price a move without performing it
    # (e.g. PermuteRoute, for now). Such operators mutate during evaluate(), atomically, and must
    # set self._revert_info themselves -- evaluate() asserts they did.
    _evaluates_by_applying: ClassVar[bool] = False

    # Set True for operators that decide part of their own operands while pricing, because the
    # decision is only knowable from the deltas (e.g. "is this chain cheaper reversed?"). Such an
    # operator prices every option in ONE _evaluate_impl call -- the alternative is evaluating the
    # same operands once per option, which recomputes every shared term. The returned decisions
    # replace the trailing operand slots positionally, BEFORE the Move is built, so the Move still
    # records exactly what apply() will do and nothing frozen is mutated.
    _evaluates_in_batch: ClassVar[bool] = False

    def __init__(self, sln: FullSolution):
        self.sln = sln
        self._revert_info = None
        self._applied: Move[Ops] | None = None

    @property
    def is_applied(self) -> bool:
        return self._applied is not None

    # ---------------------------------------------------------------- hooks
    @abstractmethod
    def _evaluate_impl(self, operands: Ops) -> tuple[ObjectiveTermDelta | None, MoveKind, *tuple[Any, ...]]:
        """PURE (unless _evaluates_by_applying). See class docstring for the return contract."""
        pass

    @abstractmethod
    def _apply_impl(self, operands: Ops) -> tuple:
        """Mutate the solution. RETURN the revert payload (do not assign it directly)."""
        pass

    @abstractmethod
    def _revert_impl(self, move: Move[Ops], revert_info) -> None:
        """
        Undo exactly what _apply_impl did, given its returned payload.

        `move` is passed in for reverts that need to see what was priced. It must NOT be mutated:
        a revert that cannot restore the original operand objects is a revert-identity bug in the
        operator, not something to paper over by repointing the move (see TODO(revert-identity)).
        """
        pass

    # -------------------------------------------------------------- drivers
    def evaluate(self, operands: Ops) -> Move[Ops]:
        assert not self.is_applied, f"{type(self).__name__}.evaluate() called with a move still applied."

        deltas, kind, *decisions = self._evaluate_impl(operands)
        applied_yet = self._evaluates_by_applying

        if self._evaluates_in_batch:
            split = len(operands) - len(decisions)
            # Asserted BEFORE substituting: once the tuple is rebuilt a type error is indis-
            # tinguishable from operands that were always wrong, and the trailing slots are the
            # only place a decision can legally land.
            assert split >= 0 and all(isinstance(d, type(o)) for d, o in zip(decisions, operands[split:])), (
                f"{type(self).__name__} returned decisions {decisions!r} that do not match the "
                f"trailing operand slots {operands[split:]!r}.")
            operands = cast(Ops, (*operands[:split], *decisions))

        # Single assert, no wrapping `if`: under -O the whole line vanishes, where a bare `if`
        # would be left hanging with an empty body.
        assert not (applied_yet and kind is MoveKind.VALID and self._revert_info is None), (
            f"{type(self).__name__} sets _evaluates_by_applying but priced a VALID move without "
            f"storing a revert payload.")

        if kind is MoveKind.INVALID:
            return Move(MoveKind.INVALID, operands)
        if kind is MoveKind.NOOP:
            return Move(MoveKind.NOOP, operands)

        assert isinstance(deltas, ObjectiveTermDelta), (
            f"{type(self).__name__}._evaluate_impl returned kind=VALID with deltas={deltas!r}.")

        move = Move(MoveKind.VALID, operands, deltas, self.improvement_from_deltas(deltas),
                    self.sln.version, already_applied=applied_yet)
        if applied_yet:
            # Order matters: the Move records the PRE-apply version, then the solution advances.
            # revert() asserts eval_version == sln.version - 1 against exactly this.
            self._applied = move
            self.sln.version += 1
        return move

    def apply(self, move: Move[Ops]):
        """
        Apply `move`, returning whether the solution now reflects it.

        Gatekeeps itself: re-applying the move that is already applied is a no-op. Callers can
        therefore drive the lifecycle uniformly -- apply/revert/commit with the move in hand --
        without tracking which operators happen to mutate during evaluate().
        """
        assert move.is_actionable, f"{type(self).__name__}.apply() called on a non-actionable move."

        # The no-op the docstring promises. This asserted instead until the split/combine
        # conversion, and the contradiction stayed hidden because PermuteRoute was the only
        # by-applying operator and the solver only ever reaches it through Operator.apply, which
        # gatekeeps first. Driving a by-applying BL directly -- as the tests do -- hit the assert.
        if move.already_applied:
            assert self._applied is move, (
                f"{type(self).__name__}.apply() got an applied move that is not the one this "
                f"operator holds; two moves are live at once.")
            return

        assert not self.is_applied, (
            f"{type(self).__name__}.apply() called while a different move is still applied.")
        assert move.eval_version == self.sln.version, (
            f"Stale move for {type(self).__name__}: attempted to apply at version {move.eval_version}, "
            f"solution is now at {self.sln.version}.")

        self._revert_info = self._apply_impl(move.operands)
        self._applied = move
        self.sln.version += 1

    def revert(self, move: Move[Ops]):
        """
        Undo `move` if it is the one currently applied; a no-op otherwise. Returns whether
        anything was actually undone.
        """
        assert move.already_applied, f"{type(self).__name__}.revert() called on a move that has not been applied."
        assert self._applied is move, f"{type(self).__name__}.revert() called on a move that mismatches last move."
        assert move.is_actionable, f"{type(self).__name__}.revert() called on a non-actionable move."
        assert move.eval_version == self.sln.version - 1, (
            f"Stale move for {type(self).__name__}: attempted to revert at version {move.eval_version}, "
            f"solution is now at {self.sln.version}.")

        self._revert_impl(move, self._revert_info)
        self._revert_info = None
        self._applied = None
        # DECREMENT, and only when we genuinely reverted. A revert restores the exact state the
        # move was evaluated against, so the version has to return to that state's number too --
        # version identifies the state, not the number of mutations performed. Incrementing here
        # would make an apply -> revert -> apply round trip look stale and trip the guard in
        # apply(), even though the solution is provably identical. That round trip is exactly
        # what snapshotting does (see SimAnnVRPSolver.take_sln_snapshot).
        self.sln.version -= 1

    def commit(self, move: Move[Ops]) -> None:
        """Finalize `move` as permanent (it can no longer be reverted).
        TODO(undo-stack): once an undo stack exists, push (self, self._revert_info, move.deltas)
        here instead of discarding -- that's the whole reason this method exists separately
        from just clearing state on the next evaluate()."""
        assert self._applied is move, (
            f"{type(self).__name__}.commit() for a move that is not the applied one.")
        self._revert_info = None
        self._applied = None

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
            return None, MoveKind.INVALID   # destination unassigned

        if (src_route.is_empty or src_route is dest_route or src_route.next_route is dest_route or
                src_route.prev_route is dest_route and dest_route.is_empty): # type: ignore - prev routes are never last routes
            # No-ops for reassign to before self, to current location, or to before previous route if prev is empty
            # (if prev is empty, the op is equivalent to moving that empty route forward one - prevented)
            return None, MoveKind.INVALID

        return src_route.cost_deltas_if_inserted_before(dest_route), MoveKind.VALID

    def _apply_impl(self, operands: ReassignRouteBeforeOps) -> tuple[Route, Route | LastRoute | None]:
        src_route, dest_route = operands
        # Possible impacts to solution cost:
        #   Activating an idle vehicle, or deactivating a single-src_route vehicle
        #   Possibly changing the initial depot, and thus travel distance from start-of-src_route to first customer (or next
        #        depot), for up to 3 routes: the one we're moving, the one originally after the one we're moving,
        #       and the one that's about to be after the one we're moving.
        revert_info = (src_route, src_route.next_route)
        src_route.link_to_vehicle_before(dest_route)
        return revert_info

    def _revert_impl(self, move, revert_info):
        # Reassigns src_route back to its original vehicle and location.
        (route, successor) = revert_info
        if successor is None:
            # This branch should never happen as a nonempty route should never be linked
            route.unlink_from_vehicle()
        else:
            route.link_to_vehicle_before(successor)


class ReassignCustomerChain(OperatorBL[ReassignCustomerChainOps]):
    # Was ReassignCustomerAt: a chain of one is the single-customer move, so this is a pure
    # widening rather than a second operator to keep in agreement.
    #
    # The trailing `reverse` operand is decided during pricing rather than chosen by the caller.
    # Both orientations fall out of ONE delta computation (they differ only in travel_distance),
    # so offering them as two candidates would recompute every shared term. Callers pass False;
    # evaluate() overwrites it from the returned decision before building the Move.
    _evaluates_in_batch = True

    def _evaluate_impl(self, operands: ReassignCustomerChainOps):
        src_route, chain, dest_route, dest_idx, _ = operands
        rng = as_chain_range(chain)
        k = len(rng)
        same_route = src_route is dest_route

        if k == 0 or rng.start < 0 or rng.stop > src_route.num_customers or dest_route.vehicle is None:
            return None, MoveKind.INVALID, False

        # dest_idx is the chain's start index AFTER removal, so a same-route move has k fewer
        # slots to land in. Different-route may append (== num_customers), never beyond.
        max_dest = dest_route.num_customers - k if same_route else dest_route.num_customers
        if not (0 <= dest_idx <= max_dest):
            return None, MoveKind.INVALID, False

        if same_route and dest_idx == rng.start:
            # The chain does not move. Reversing it where it sits is ReverseCustomerChain's job,
            # so this stays a no-op rather than becoming a second way to spell that move.
            return None, MoveKind.NOOP, False

        not_reversed, reversed_ = src_route.cost_deltas_if_customer_chain_moved(rng, dest_route, dest_idx)

        # Only travel_distance differs, so this comparison decides the whole orientation.
        reverse = reversed_.travel_distance < not_reversed.travel_distance
        return (reversed_ if reverse else not_reversed), MoveKind.VALID, reverse

    def _apply_impl(self, operands: ReassignCustomerChainOps) -> tuple[Route, range, Route, int, bool]:
        src_route, chain, dest_route, dest_idx, reverse = operands
        rng = as_chain_range(chain)
        if src_route is dest_route:
            src_route.reassign_customer_chain(rng, dest_idx, reverse)
        else:
            visits = src_route.remove_customer_chain(rng)
            dest_route.insert_customer_chain(visits, dest_idx, reverse)
        return src_route, rng, dest_route, dest_idx, reverse

    def _revert_impl(self, move, revert_info):
        src_route, rng, dest_route, dest_idx, reverse = revert_info
        moved = range(dest_idx, dest_idx + len(rng))
        # Un-reverse before moving back. Reversal is an involution, so undoing it in place at the
        # destination restores the original order, and the return trip is then a plain move.
        if reverse:
            dest_route.reverse_customer_chain(moved)
        if src_route is dest_route:
            src_route.reassign_customer_chain(moved, rng.start)
        else:
            visits = dest_route.remove_customer_chain(moved)
            src_route.insert_customer_chain(visits, rng.start)


class ReassignCustomerToNewRouteBefore(OperatorBL[ReassignCustomerToNewRouteOps]):
    def _evaluate_impl(self, operands: ReassignCustomerToNewRouteOps):
        src_route, src_index, dest_route, end_depot = operands
        if not 0 <= src_index < src_route.num_customers or dest_route.vehicle is None:
            return None, MoveKind.INVALID

        remove_delta = src_route.cost_deltas_if_customer_popped(src_index)

        # Gotta coppy customer sans linkages: Otherwise adding it to the new src_route will overwrite its linkages
        customer = copy.copy(src_route.path[src_index])
        new_route = Route([customer], end_depot)
        # New mid-solve route needs its depot-usage dict linked before pricing against it -
        # otherwise depot-activation deltas below would touch an unlinked route.
        new_route.link_depot_uses_except_customers(self.sln.depot_route_starts)

        add_delta = new_route.cost_deltas_if_inserted_before(dest_route)

        return add_delta + remove_delta, MoveKind.VALID

    def _apply_impl(self, operands: ReassignCustomerToNewRouteOps) -> tuple[Route, int, Route]:
        src_route, src_index, dest_route, end_depot = operands
        sln = self.sln

        customer = src_route.pop_customer_at(src_index)
        new_route = Route([customer], end_depot)
        new_route.link_depot_uses_except_customers(sln.depot_route_starts)
        new_route.link_to_vehicle_before(dest_route)
        sln.all_routes.add(new_route)
        return src_route, src_index, new_route

    def _revert_impl(self, move, revert_info):
        sln = self.sln

        src_route, src_index, new_route = revert_info
        new_route.unlink_from_vehicle()

        src_route.insert_customer(new_route.path[0], src_index)

        # (Obsolete bug funny comment from when all_routes was an array):
        # The new src_route was most recently appended on the end. So we pop it! Like a balloon
        sln.all_routes.remove(new_route)


class SwapCustomerChains(OperatorBL[SwapCustomerChainsOps]):
    """
    Exchange two customer chains. route1's chain lands in route2's slot and vice versa, each
    optionally reversed as it lands.

    Chains must be non-empty. That guard is load-bearing rather than cosmetic: it is what makes
    the vehicle-activation and depot-activation terms vanish, because each route keeps at least
    one customer and so neither can empty.
    """
    _evaluates_in_batch = True

    def _evaluate_impl(self, operands: SwapCustomerChainsOps):
        route1, chain1, route2, chain2, _, _ = operands
        rng1, rng2 = as_chain_range(chain1), as_chain_range(chain2)

        if len(rng1) == 0 or len(rng2) == 0:
            return None, MoveKind.INVALID, False, False
        if not (0 <= rng1.start and rng1.stop <= route1.num_customers):
            return None, MoveKind.INVALID, False, False
        if not (0 <= rng2.start and rng2.stop <= route2.num_customers):
            return None, MoveKind.INVALID, False, False
        if route1 is route2 and rng1.start < rng2.stop and rng2.start < rng1.stop:
            return None, MoveKind.INVALID, False, False   # overlapping ranges in one route

        deltas = route1.cost_deltas_for_customer_chain_swap(rng1, route2, rng2)

        # argmin over all four rather than two independent comparisons. The two reversals ARE
        # independent when the chains are disjoint, but not when they are adjacent in one route --
        # there the arc between them depends on both. argmin is correct either way.
        options = ((deltas[0], False, False), (deltas[1], True, False),
                   (deltas[2], False, True), (deltas[3], True, True))
        best, reverse1, reverse2 = min(options, key=lambda option: option[0].travel_distance)
        return best, MoveKind.VALID, reverse1, reverse2

    def _apply_impl(self, operands: SwapCustomerChainsOps) -> tuple[Route, range, Route, range, bool, bool]:
        route1, chain1, route2, chain2, reverse1, reverse2 = operands
        rng1, rng2 = as_chain_range(chain1), as_chain_range(chain2)
        k1, k2 = len(rng1), len(rng2)

        # Where each chain ENDS UP. For unequal sizes the chains do not land where they started,
        # so revert cannot recompute these -- they go in the payload.
        if route1 is not route2:
            landed1 = range(rng2.start, rng2.start + k1)
            landed2 = range(rng1.start, rng1.start + k2)
        elif rng1.start < rng2.start:
            gap = rng2.start - rng1.stop
            landed2 = range(rng1.start, rng1.start + k2)
            landed1 = range(rng1.start + k2 + gap, rng1.start + k2 + gap + k1)
        else:
            gap = rng1.start - rng2.stop
            landed1 = range(rng2.start, rng2.start + k1)
            landed2 = range(rng2.start + k1 + gap, rng2.start + k1 + gap + k2)

        route1.swap_customer_chains_with(rng1, route2, rng2, reverse1, reverse2)
        return route1, landed2, route2, landed1, reverse2, reverse1

    def _revert_impl(self, move, revert_info):
        # Swap the landed chains back, each carrying its own reverse flag again. Reversal is an
        # involution, and insert_customer_chain places at the target range's START, so the chains
        # land back on their original spans even when the sizes differ.
        route1, landed2, route2, landed1, reverse2, reverse1 = revert_info
        route1.swap_customer_chains_with(landed2, route2, landed1, reverse2, reverse1)


class ReverseCustomerChain(OperatorBL[ReverseCustomerChainOps]):
    def _evaluate_impl(self, operands: ReverseCustomerChainOps):
        route, chain = operands
        rng = as_chain_range(chain)
        if not (0 <= rng.start and rng.stop <= route.num_customers):
            return None, MoveKind.INVALID

        if len(rng) <= 1:
            return None, MoveKind.NOOP   # a chain of 0 or 1 reverses to itself

        return route.cost_deltas_if_customer_chain_reversed(rng), MoveKind.VALID

    def _apply_impl(self, operands: ReverseCustomerChainOps) -> tuple[Route, Chain]:
        route, chain = operands
        route.reverse_customer_chain(chain)
        return route, chain

    def _revert_impl(self, move, revert_info):
        # Reapplying the swap just reverses back. ezpz
        self._apply_impl(revert_info)


def invert_permutation(permutation: Sequence[int]) -> Sequence[int]:
    # This stupid fast solution was found on Stack Overflow. Poster found a ~4us runtime for 1000 entries!
    # Type-fixed in a way to reduce copies with help from Gemini
    inv = np.empty_like(permutation)
    idx = list(permutation) if isinstance(permutation, tuple) else permutation # Resolve tuple-bug - numpy treats tuples as multi-D arrays
    inv[idx] = np.arange(len(inv), dtype=inv.dtype)
    return cast(Sequence[int], inv)

class PermuteRoute(OperatorBL[PermuteRouteOps]):
    # Not yet given real delta math (planned for a later pass) - prices by applying the
    # permutation and measuring the change. _evaluates_by_applying changes only how evaluate()
    # FINISHES (already_applied, _applied, version bump); pricing still goes through
    # _evaluate_impl, so this operator can still report INVALID or NOOP like any other.
    _evaluates_by_applying = True

    def _evaluate_impl(self, operands: PermuteRouteOps):
        # Route-local O(path length) measurement, not a full-solution objective_terms() diff.
        route, _ = operands
        before = route.total_distance()
        self._revert_info = self._apply_impl(operands)
        after = route.total_distance()
        return ObjectiveTermDelta(travel_distance=after - before), MoveKind.VALID

    def _apply_impl(self, operands: PermuteRouteOps) -> tuple[Route, Sequence[int]]:
        route, permutation = operands
        route.permute(permutation)
        return route, invert_permutation(permutation)

    def _revert_impl(self, move, revert_info):
        route, inv_permutation = revert_info
        route.permute(inv_permutation)


class ChangeEndDepot(OperatorBL[ChangeEndDepotOps]):
    def _evaluate_impl(self, operands: ChangeEndDepotOps):
        route, new_end_depot = operands
        if route.is_empty:
            return None, MoveKind.INVALID

        # No-op condition (we disallow no-ops)
        if new_end_depot == route.end_depot:
            return None, MoveKind.INVALID

        return route.cost_deltas_if_end_depot_changes(new_end_depot), MoveKind.VALID

    def _apply_impl(self, operands: ChangeEndDepotOps) -> tuple[Route, Depot]:
        route, new_end_depot = operands
        old_end_depot = route.end_depot
        route.set_end_depot(new_end_depot)
        return route, old_end_depot

    def _revert_impl(self, move, revert_info):
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
            return None, MoveKind.NOOP

        assert all(route.is_empty for route in routes), "Cannot dispose of nonempty routes! You'll lose customers."

        if self.dispose_only_trivial_routes:
            # trivial routes are cost-neutral by definition
            return ObjectiveTermDelta(), MoveKind.VALID

        return self.sln.cost_deltas_for_removing_empty_routes(routes), MoveKind.VALID

    def _apply_impl(self, operands: DisposeOfEmptyRoutesOps) -> tuple[list[tuple[Route, Route | FirstRoute | None]], list[tuple[Route, int]]]:
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

    # TODO: There's duplicated data stored in the revert_info: routes to remove show up twice. We need to deduplicate.
    def _revert_impl(self, move, revert_info):
        revert_stack, removed = revert_info
        for route, prev_route in reversed(revert_stack):
            if prev_route is not None:
                route.link_to_vehicle_after(prev_route)
        self.sln.all_routes.undo_difference_update(removed)


class SplitRoute(OperatorBL[SplitRouteOps]):
    # Still predictive. Splitting CREATES a route, and the sequential decomposition of that needs
    # a priced "insert an empty route into this vehicle" primitive, which does not exist yet.
    # cost_deltas_for_split_at is cheap (SplitRandomRoute proposes in ~9us) and correct, so it
    # stays until that primitive exists. CombineRoutes below is the decomposed one.
    def _evaluate_impl(self, operands: SplitRouteOps):
        route, split_index, intermediate_end_depot = operands
        # To be splittable: src_route must have multiple customers (each customer to a different src_route).
        #   Index out of bounds: invalid. Index = 0 or split_index == path length => there is no customer to split.
        num_customers = route.num_customers

        if num_customers <= 1 or 0 == split_index or split_index >= num_customers:
            return None, MoveKind.INVALID

        return route.cost_deltas_for_split_at(split_index, intermediate_end_depot), MoveKind.VALID

    def _apply_impl(self, operands: SplitRouteOps) -> tuple[Route, Route]:
        route, split_index, intermediate_end_depot = operands
        new_route = route.split_at(split_index, intermediate_end_depot)
        self.sln.all_routes.add(new_route)
        return route, new_route

    def _revert_impl(self, move, revert_info):
        route, new_route = revert_info
        route.combine_with(new_route)
        self.sln.all_routes.remove(new_route)


class CombineRoutes(OperatorBL[CombineRoutesOps]):
    # Merges route2's customers onto the end of route1 and discards route2. Not adjacency-
    # restricted -- any two non-trivial routes (in the same or different vehicles) can combine.
    #
    # Predictive, and staying that way. _SequentialCombineRoutes below is the same operator built
    # from priced primitives; it was measured at 3.7x this one's cost on short routes and 8.5x on
    # long ones. See that class for why, and for when the trade goes the other way.
    def _evaluate_impl(self, operands: CombineRoutesOps):
        route1, route2 = operands
        # is_empty (zero customers), not just is_trivial (empty AND a depot round-trip): combine_with
        # appends route2's customers onto route1 and then relinks at the boundary index, which is
        # out of range whenever route2 has zero customers, trivial or not.
        if route1 is route2 or route1.is_empty or route2.is_empty:
            return None, MoveKind.INVALID

        return route1.cost_deltas_for_combine_with(route2), MoveKind.VALID

    def _apply_impl(self, operands: CombineRoutesOps) -> tuple[Route, int, Depot, Route | FirstRoute | None, int, Route]:
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
        return route1, split_index, own_end_depot, other_prev_route, other_slot, route2

    def _revert_impl(self, move, revert_info):
        route1, split_index, own_end_depot, other_prev_route, other_slot, route2 = revert_info
        # split_at's third argument refills THIS route object rather than constructing a new one,
        # so route2 keeps its identity across an apply -> revert cycle.
        new_route = route1.split_at(split_index, own_end_depot, route2)
        self.sln.all_routes.undo_remove(new_route, other_slot)
        if other_prev_route is not None:
            # split_at already linked new_route directly after route1; move it back to route2's
            # original slot (a no-op when route2 was route1's immediate successor).
            new_route.link_to_vehicle_after(other_prev_route)


class _SequentialCombineRoutes(OperatorBL[CombineRoutesOps]):
    """
    REFERENCE ONLY -- not in the roster, not intended for use. Leading underscore is deliberate.

    CombineRoutes rebuilt as a chain of primitives that are each already priced and already
    tested, to establish the pattern a compound operator should follow. It is correct: it passed
    the suite and a clean stress run while it was the live implementation.

    IT IS ALSO MUCH SLOWER, measured per propose->revert cycle:

        capacity  median route   predictive   sequential   factor
            25          4          137.7us      514.5us     3.7x
           400         71          112.5us     1050.0us     8.5x

    The reason is structural, not a tuning problem. A by-applying operator physically performs
    the move and then undoes it on every REJECTED proposal, which is O(chain length) twice, where
    the predictive version computes O(1) boundary arcs and touches nothing. CombineRandomRoutes
    is accepted essentially never, so it pays the full cost every time. Note the shape as well as
    the size: predictive is flat in route length, sequential is not.

    WHEN THE TRADE GOES THE OTHER WAY. Combine is the worst case for this pattern -- it has cheap
    predictive math and near-zero acceptance. Ruin-and-recreate is the best case:

      * there is no predictive alternative. You cannot price a ruin-and-recreate without
        performing it, so "slower than predicting" has no meaning;
      * greedy reinsertion mostly improves, so acceptance is high and the do-then-undo cost is
        amortized over moves that actually land;
      * the customers it removes are placed much later, by a different decision, which is exactly
        what cost_deltas_if_customer_chain_removed / ..._inserted_before were split apart for.

    WHAT TO COPY FROM IT:
      * _evaluates_by_applying = True, with _revert_info set before returning VALID;
      * each step priced against the state the previous step LEFT -- overload is nonlinear in
        load, so deltas are only additive when measured against the solution that really existed;
      * _revert_impl running the steps backwards, same shape as DisposeOfEmptyRoutesBL's revert
        stack, which keeps route identity intact because nothing is ever disposed and rebuilt;
      * _apply_impl kept as a separate near-copy without the pricing, so the snapshot round trip
        can re-apply a reverted move without computing deltas it would discard.
    """
    _evaluates_by_applying = True

    def _evaluate_impl(self, operands: CombineRoutesOps):
        route1, route2 = operands
        # is_empty (zero customers), not just is_trivial (empty AND a depot round-trip): combine_with
        # appends route2's customers onto route1 and then relinks at the boundary index, which is
        # out of range whenever route2 has zero customers, trivial or not.
        if route1 is route2 or route1.is_empty or route2.is_empty:
            return None, MoveKind.INVALID

        sln = self.sln
        chain = range(0, route2.num_customers)
        dest_idx = route1.num_customers
        own_end_depot = route1.end_depot
        inherited_end_depot = route2.end_depot
        other_prev_route = route2.prev_route

        # Four primitives that are already priced and already tested. Each reads its delta from
        # the state the previous step left, which is what makes them SUM: overload is nonlinear in
        # load, so a delta is additive only when measured against the solution that actually
        # existed at that moment. No new delta math is written here -- that is the point.
        #
        # Removal and insertion are charged SEPARATELY rather than through
        # cost_deltas_if_customer_chain_moved. The joint version has to price both sides before
        # either happens, so its depot and vehicle terms are "activates at the destination minus
        # deactivates at the source". Split, each half stands alone -- which is what a ruin step
        # needs, since it removes customers long before it decides where they land.
        chain_removal = route2.cost_deltas_if_customer_chain_removed(chain)
        visits = route2.remove_customer_chain(chain)

        insert_visit = route1.get_visit_at(dest_idx)
        assert isinstance(insert_visit, CustomerVisit|LastRouteVisit)
        chain_insert, _reversed = route1.cost_deltas_if_customer_chain_inserted_before(
            visits, insert_visit)
        route1.insert_customer_chain(visits, dest_idx, False)

        depot_change = route1.cost_deltas_if_end_depot_changes(inherited_end_depot)
        route1.set_end_depot(inherited_end_depot)

        route_removal = route2.cost_deltas_if_removed()
        route2.unlink_from_vehicle()
        other_slot = sln.all_routes.remove(route2)

        self._revert_info = (route1, chain, dest_idx, own_end_depot,
                             route2, other_prev_route, other_slot)
        return chain_removal + chain_insert + depot_change + route_removal, MoveKind.VALID

    def _apply_impl(self, operands: CombineRoutesOps) -> tuple:
        """
        The same three steps without the pricing, for callers that only want the mutation.

        Deliberately a near-copy of _evaluate_impl's body rather than shared with it. Pricing has
        to interleave -- step 2's delta is only meaningful once step 1 has run -- so factoring the
        two together would mean computing three deltas on this path and discarding them. The
        snapshot round trip re-applies moves purely to mutate, and should not pay for that.
        """
        sln = self.sln
        route1, route2 = operands
        chain = range(0, route2.num_customers)
        dest_idx = route1.num_customers
        own_end_depot = route1.end_depot
        other_prev_route = route2.prev_route

        visits = route2.remove_customer_chain(chain)
        route1.insert_customer_chain(visits, dest_idx, False)
        route1.set_end_depot(route2.end_depot)
        route2.unlink_from_vehicle()
        other_slot = sln.all_routes.remove(route2)

        return route1, chain, dest_idx, own_end_depot, route2, other_prev_route, other_slot

    def _revert_impl(self, move, revert_info):
        # The three steps run backwards, same shape as DisposeOfEmptyRoutesBL's revert stack.
        # route2 is the ORIGINAL object throughout -- only emptied and unlinked, never disposed --
        # so this is identity-correct by construction, which is what the old split_at-based revert
        # had to work to achieve and what TODO(revert-identity) was about.
        route1, chain, dest_idx, own_end_depot, route2, other_prev_route, other_slot = revert_info
        sln = self.sln

        # Step 3 undone: route2 goes back into all_routes at its original slot, and back into the
        # vehicle chain after whoever preceded it.
        sln.all_routes.undo_remove(route2, other_slot)
        route2.link_to_vehicle_after(other_prev_route)

        # Step 2 undone.
        route1.set_end_depot(own_end_depot)

        # Step 1 undone: the customers go home.
        visits = route1.remove_customer_chain(range(dest_idx, dest_idx + len(chain)))
        route2.insert_customer_chain(visits, 0, False)


# TODO(future-operator): SubPermuteRoute, using the existing (unused)
# Route.cost_deltas_for_subpermutation -- not yet decided how best to leverage this one.