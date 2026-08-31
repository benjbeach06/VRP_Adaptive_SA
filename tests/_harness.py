"""
Shared helpers for the VRP solver test suite.

PROVENANCE
----------
This test suite was written and maintained independently by Claude (Anthropic) while providing
development assistance on this project. It is not hand-written by the repository author. It
exists because the solver keeps a large amount of incrementally-maintained cached state -- depot
usage counters, per-route loads, a doubly-linked visit list, and a per-vehicle route chain --
where almost every cached quantity has a recompute-from-scratch counterpart. That property makes
oracle-style checking unusually cheap and unusually effective, and every bug these tests encode
was originally found by comparing a cached value against its recomputed twin.

Design input from the repository author (implementation here is Claude's):
  * Route all randomness through one explicit generator (np.random.default_rng) rather than the
    process-wide `random` module. This is what actually made solves reproducible -- before it,
    identical seeds diverged both within a process and across processes.
  * Every test must fix its own generator seed, so the suite is valid under arbitrary test
    ordering and when only a subset is run. Implemented as SeededTestCase.setUp below.

Run everything from the repository root:

    python -m unittest discover -s tests

The exhaustive operator matrices are reduced by default so the suite stays fast. For the full
sweep (tens of thousands of cases, minutes rather than seconds):

    VRP_FULL_MATRIX=1 python -m unittest discover -s tests
"""

import contextlib
import io
import os
import random
import sys
import unittest
from pathlib import Path

# Tests live in a subdirectory; make the project importable regardless of how they're invoked.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np

from SimAnn_VRP_Core_Model import (  # noqa: E402
    Customer, CustomerVisit, Depot, FullSolution, ObjectiveTermDelta, Route, Vehicle,
    VIRTUAL_DEPOT, seed_solver_rng,
)
from SimAnn_VRP_Operators import Operator  # noqa: E402

FULL_MATRIX = os.environ.get("VRP_FULL_MATRIX") == "1"


class DirectOperator(Operator):
    """
    Drives an OperatorBL through the real Operator lifecycle on caller-supplied operands.

    Operator already provides evaluate/apply/commit/revert; it is abstract only on operand
    SELECTION, which tests never want. This fills that one hole.

    Going through the wrapper is the point, not a convenience. Move.already_applied is maintained
    by Operator, not by OperatorBL, so a test that drives the BL object directly has to redo that
    bookkeeping by hand -- and OperatorBL.revert() asserts on the flag it never sets. Reproducing
    the wrapper's bookkeeping in a caller is the same mistake that produced real solver bugs, so
    the suite should not model it.
    """

    def __init__(self, sln, base_operator, explore_reward=0.0):
        # Keeps the (sln, base_operator) call shape every test already uses, and defaults
        # explore_reward to 0.0 so the accept score has NO floor. That is what a contract test
        # wants: an uphill accept scores exactly what the improvement says, with nothing added.
        # Tests that care about the floor pass it explicitly.
        super().__init__(sln, explore_reward, base_operator)

    def _operand_selection_impl(self):
        raise NotImplementedError("DirectOperator is driven with caller-supplied operands.")

DEFAULT_DEPOT_LAYOUT = [((10, 10), 35), ((50, 50), 35), ((90, 10), 35)]


#region Instance construction
def make_depots(layout=None) -> list[Depot]:
    layout = layout or DEFAULT_DEPOT_LAYOUT
    return [Depot(i, loc, limit, 1) for i, (loc, limit) in enumerate(layout)]


def make_solution(depots: list[Depot], customers: list[Customer], vehicle_capacities: list,
                  initial_depot_of=lambda i, depots: depots[i % len(depots)]) -> FullSolution:
    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)
    for i, cap in enumerate(vehicle_capacities):
        sln.add_vehicle(Vehicle(initial_depot=initial_depot_of(i, depots), i=i, capacity=cap))
    sln.set_objectives(cost_per_depot=20, cost_per_vehicle=10, unit_travel_cost=1)
    return sln


DEFAULT_TEST_SEED = 20260809


def seed_everything(seed: int) -> None:
    """
    Pin every stream a solve can draw from: the solver's own generator plus the stdlib and numpy
    globals (still used for instance generation, and by anything not yet migrated).
    """
    random.seed(seed)
    np.random.seed(seed)
    seed_solver_rng(seed)


class SeededTestCase(unittest.TestCase):
    """
    Base for every test in this suite.

    Reseeds before EACH test so cases are independent of execution order, of how many ran before
    them, and of whether the full suite or a single test is being run. Without this a test that
    draws randomly inherits whatever state its predecessors left, so a failure seen in a full run
    cannot be reproduced in isolation -- the exact property that makes a flaky suite useless.
    """

    SEED = DEFAULT_TEST_SEED

    def setUp(self):
        super().setUp()
        seed_everything(self.SEED)


def random_instance(seed: int, n_customers: int, n_vehicles: int, capacity: int = 25):
    """Deterministic pseudo-random instance; also reseeds every stream (see seed_everything)."""
    seed_everything(seed)
    depots = make_depots()
    customers = [Customer(i, tuple(np.random.randint(0, 100, size=2)),
                          int(np.random.randint(1, 11))) for i in range(n_customers)]
    return make_solution(depots, customers, [capacity] * n_vehicles)


def route_of(customers: list[Customer], indices, end_depot: Depot) -> Route:
    """A route over the given customer indices, wrapping each in a fresh CustomerVisit."""
    return Route([CustomerVisit(customers[i]) for i in indices], end_depot)
#endregion


#region Oracles -- recompute from scratch and compare against the cached/incremental value
def visit_link_problems(sln: FullSolution) -> list[str]:
    """
    The visit doubly-linked list must agree with each route's path list.

    This is the check that would have caught the combine_with tail-relink bug at its source: a
    merged route kept last_visit.prev_visit pointing at the PRE-merge last customer, which stayed
    invisible until it surfaced as a wrong delta in an unrelated operator.
    """
    problems = []
    for route in sln.all_routes:
        first, last, path = route.first_visit, route.last_visit, route.path
        if not path:
            if first.next_visit is not last:
                problems.append(f"{route}: empty route's first_visit doesn't chain to last_visit")
            continue
        if first.next_visit is not path[0]:
            problems.append(f"{route}: first_visit.next_visit is not path[0]")
        if path[0].prev_visit is not first:
            problems.append(f"{route}: path[0].prev_visit is not first_visit")
        if last.prev_visit is not path[-1]:
            problems.append(f"{route}: last_visit.prev_visit is not path[-1]")
        if path[-1].next_visit is not last:
            problems.append(f"{route}: path[-1].next_visit is not last_visit")
        for i in range(1, len(path)):
            if path[i].prev_visit is not path[i - 1]:
                problems.append(f"{route}: path[{i}].prev_visit broken")
            if path[i - 1].next_visit is not path[i]:
                problems.append(f"{route}: path[{i - 1}].next_visit broken")
    return problems


def depot_usage_problems(sln: FullSolution) -> list[str]:
    """Incrementally-maintained depot_route_starts must equal a fresh count over active routes."""
    truth = sln.depot_usage_breakdown()
    def members(route_set):
        # Sorted MEMBERSHIP, never order: RouteSet removal is swap-with-last, so a remove/add
        # round trip restores membership but not position. Comparing order here would report
        # every such revert as a failure.
        return sorted(str(route) for route in route_set)

    return [f"depot {depot}: tracked {members(sln.depot_route_starts[depot])} "
            f"!= recomputed {members(truth[depot])}"
            for depot in sln.depots if members(truth[depot]) != members(sln.depot_route_starts[depot])]


def chain_problems(sln: FullSolution) -> list[str]:
    """Each vehicle's route chain must be well-formed, depot-consistent, and agree with
    vehicle.routes.

    The MEMBERSHIP comparison was added 2026-08-28. The chain and the RouteSet are two separate
    structures maintained by the same two mutators, link_to_vehicle_*/unlink_from_vehicle, and
    nothing had ever checked one against the other, so they could drift in silence.

    That drift would be nastier than a wrong number. vehicle.routes is what rand_choice draws
    operands from; the chain is what the objective is computed over. A disagreement makes the
    solver propose moves against routes the objective cannot see, or ignore routes it is paying
    for -- neither of which shows up as a cost mismatch.
    """
    problems = []
    for vehicle in sln.vehicles:
        seen, chained, cycled = set(), [], False
        current = vehicle.first_route.next_route
        previous = vehicle.first_route
        while isinstance(current, Route):
            if id(current) in seen:
                problems.append(f"vehicle {vehicle.vID}: cycle in route chain at {current}")
                cycled = True
                break
            seen.add(id(current))
            chained.append(current)
            if current.prev_route is not previous:
                problems.append(f"vehicle {vehicle.vID}: {current}.prev_route is not its predecessor")
            if current.start_depot is not previous.end_depot:
                problems.append(f"vehicle {vehicle.vID}: {current} start depot != predecessor end depot")
            if current.vehicle is not vehicle:
                problems.append(f"vehicle {vehicle.vID}: {current}.vehicle points elsewhere")
            previous, current = current, current.next_route
        if vehicle.last_route.start_depot is not previous.end_depot:
            problems.append(f"vehicle {vehicle.vID}: LastRoute.start_depot != final route's end depot")

        if not cycled and {id(route) for route in chained} != {id(route) for route in vehicle.routes}:
            # Compared by IDENTITY, reported by str: two distinct routes can stringify alike, so
            # str is safe to read but not to decide on. Membership only, never order -- RouteSet
            # removal is swap-with-last, so a remove/add round trip restores membership but not
            # position (same reason depot_usage_problems sorts).
            problems.append(
                f"vehicle {vehicle.vID}: route chain {sorted(str(route) for route in chained)} "
                f"!= vehicle.routes {sorted(str(route) for route in vehicle.routes)}")
    return problems


def load_problems(sln: FullSolution) -> list[str]:
    return [f"{route}: cached load {route.current_load} != recomputed {route.recompute_current_load()}"
            for route in sln.all_routes
            if abs(route.recompute_current_load() - route.current_load) > 1e-9]


def vehicle_counter_problems(sln: FullSolution) -> list[str]:
    """Each vehicle's incrementally-maintained counters must equal a fresh walk of its route chain.

    These had NO oracle until 2026-08-28, and the gap was invisible by construction:
    objective_terms() READS num_customers and num_routes_overloaded, and the per-term contract
    assertion compares move.deltas against a diff of two objective_terms() calls. A corrupt counter
    therefore makes the prediction and the measurement wrong by the SAME amount, and the assertion
    passes. Two of the five objective terms -- vehicles_activated and vehicles_overloaded -- rest
    on exactly these counters.

    Ground truth is the CHAIN, deliberately, not vehicle.routes. The chain is what fingerprint and
    chain_problems already treat as authoritative structure, whereas vehicle.routes is maintained
    by link_to_vehicle_*/unlink_from_vehicle -- the same two mutators that maintain these counters.
    Checking a counter against a set updated in the same breath would let a shared bug through.

    Nothing here checks that vehicle.routes agrees with the chain. That is a separate gap, still
    open; chain_problems walks the chain but never compares membership.
    """
    problems = []
    for vehicle in sln.vehicles:
        chain, seen = [], set()
        current = vehicle.first_route.next_route
        while isinstance(current, Route):
            if id(current) in seen:
                # chain_problems reports the cycle itself. Bail rather than spin, and skip this
                # vehicle's counters -- a truth built from a broken chain says nothing.
                chain = None
                break
            seen.add(id(current))
            chain.append(current)
            current = current.next_route

        if chain is None:
            continue

        for name, tracked, truth in (
            ("num_customers", vehicle.num_customers,
             sum(route.num_customers for route in chain)),
            ("num_routes_with_customers", vehicle.num_routes_with_customers,
             sum(1 for route in chain if route.has_customers)),
            ("num_routes_overloaded", vehicle.num_routes_overloaded,
             sum(1 for route in chain if route.is_overloaded)),
        ):
            if tracked != truth:
                problems.append(
                    f"vehicle {vehicle.vID}: {name} tracked {tracked} != recomputed {truth}")
    return problems


#region Raw-record oracle
# The state a RouteDelta describes, for a route that is not on the solution at all -- either not
# yet created, or disposed. Matches RouteDelta's two sentinels: a VirtualDepot for "no start
# depot", None for "no vehicle". NOT None for both -- a route object that exists but is unassigned
# genuinely reads back a VirtualDepot, which is what Route.__init__ installs and what
# unlink_from_vehicle restores, so None here would fail every created- or disposed-route entry.
ABSENT_ROUTE_STATE = (0, 0, VIRTUAL_DEPOT, None)


def route_states(sln: FullSolution) -> dict[Route, tuple]:
    """Every route's RAW structural state, keyed by identity, in the record's field order."""
    return {route: _live_route_state(route) for route in sln.all_routes}


def _live_route_state(route: Route) -> tuple:
    """Read a route's current state directly, so disposal is readable too.

    A disposed route is gone from all_routes but the object still exists, and reads back as
    unassigned -- which is exactly the transition the record should be claiming.

    LOAD IS RECOMPUTED FROM THE PATH, NOT READ OFF route.current_load. Since step 3 that field is
    a SINK-WRITTEN CACHE: a bare mutation does not touch it, so comparing it before and after a
    mutation reports "load did not change" every single time. Grading the record against it would
    make the completeness check for load_changes vacuous -- and that check is the only thing
    standing between a forgotten load entry and a silently wrong total_route_overload.

    START DEPOT IS used_start_depot, NOT THE RAW FIELD, for a different reason: the record reports
    the depot a route COUNTS AGAINST, which is virtual whenever the route is inactive. An empty
    route still carries a real geometric start depot and relinking still moves it, so grading
    against the raw field reports a change the record is right to omit. That produced false
    "start_depot_changes has no entry" findings on every empty route.

    num_customers and vehicle need no treatment. num_customers is len(path), vehicle is structure,
    and both move with the mutation itself.
    """
    return (route.recompute_current_load(), route.num_customers,
            route.used_start_depot, route.vehicle)


# The four field maps on a RawDeltaRecord, paired with that field's slot in the state tuples
# route_states() and _live_route_state() build. One list, so the two oracles below cannot drift
# out of step over which fields exist or what order they are in.
RECORD_FIELDS = (("load", "load_changes", 0),
                 ("num_customers", "customer_deltas", 1),
                 ("start_depot", "start_depot_changes", 2),
                 ("vehicle", "vehicle_changes", 3))


def raw_record_claim_problems(before_states: dict, record) -> list[str]:
    """Every transition the record CLAIMS must match what actually happened.

    THE CORRECTNESS HALF. It checks only what a map actually says, per field, and is silent about
    a field a route is absent from -- an absent field makes no claim, so there is nothing here to
    verify. That is deliberate, and it is why this half cannot collude with the shape: it never
    resolves a default, so it never re-derives the same answer the processor did.

    What it therefore cannot catch is a MISSING entry, which reads back as "held still" and prices
    the move as if that part never happened. raw_record_completeness_problems is the half that
    catches those, and under the per-field record it is load-bearing rather than a convenience.
    """
    problems = []
    for field_name, map_name, slot in RECORD_FIELDS:
        for route, (initial, final) in getattr(record, map_name).items():
            was = before_states.get(route, ABSENT_ROUTE_STATE)[slot]
            now = _live_route_state(route)[slot]
            if initial != was:
                problems.append(f"{route}: record claims {field_name} started at {initial!r}, "
                                f"but it was {was!r}")
            if final != now:
                problems.append(f"{route}: record claims {field_name} ended at {final!r}, "
                                f"but it is {now!r}")
    return problems


def raw_record_completeness_problems(before_states: dict, sln: FullSolution, record) -> list[str]:
    """Every field a route ACTUALLY moved must have an entry in that field's map.

    PER FIELD, not per route. Under the per-field record a route legitimately appears in one map
    and not another, so "this route has an entry somewhere" proves nothing -- a route that moved
    vehicle AND load, but is listed only under vehicle, is priced with the wrong load and has an
    entry the whole time.

    This is the check the record shape rests on. Absence means unchanged, and the consumer reads
    the live value off the route accordingly; if absence can also mean "the aggregator forgot",
    then every derived term silently prices a partial mutation.
    """
    problems = []
    touched = set(before_states) | set(sln.all_routes)
    for _, map_name, _ in RECORD_FIELDS:
        touched |= set(getattr(record, map_name))

    for route in touched:
        was = before_states.get(route, ABSENT_ROUTE_STATE)
        now = _live_route_state(route)
        for field_name, map_name, slot in RECORD_FIELDS:
            if was[slot] != now[slot] and route not in getattr(record, map_name):
                problems.append(f"{route}: changed {field_name} from {was[slot]!r} to "
                                f"{now[slot]!r} but {map_name} has no entry")
    return problems


def raw_record_distance_problems(before_terms, after_terms, record) -> list[str]:
    """The record's travel_distance must match the distance the solution actually moved.

    THE THIRD HALF, and the only one that reads a field outside `routes`. The other two check
    structural transitions; distance is a plain sum on the record itself, so neither of them can
    see it at all. Without this, an aggregator that populates ONLY distance -- every intra-route
    one does, by design -- is covered by no oracle whatsoever.

    Scoped the same way completeness is, and for the same reason: an aggregator that has not been
    converted yet reports 0, which is indistinguishable from a converted one reporting the wrong
    value. So this is not wired into assert_operator_contract until all 24 populate distance. Until
    then it is called directly, over the aggregators known to be converted.

    Deliberately NOT phrased as "0 or correct". That version would be unconditional today and would
    strengthen on its own, but it permanently excuses a converted aggregator that wrongly reports
    zero -- the conditional-oracle trap that made the missing counter oracles worthless.
    """
    claimed = record.travel_distance
    measured = after_terms.travel_distance - before_terms.travel_distance
    # places=9 matches the per-term contract assertion; both sides sum floats in different orders.
    if round(claimed - measured, 9) != 0:
        return [f"record claims travel_distance {claimed} but the solution moved {measured}"]
    return []
#endregion


def all_problems(sln: FullSolution) -> list[str]:
    return (visit_link_problems(sln) + depot_usage_problems(sln)
            + chain_problems(sln) + load_problems(sln)
            + vehicle_counter_problems(sln))


def fingerprint(sln: FullSolution):
    """
    Structural + cost identity of a solution, for exact revert round-trip checks.

    Includes all_routes ORDER, not just membership. That matters because the solver picks
    operands positionally (rand_choice indexes into the RouteSet), so an operator whose revert
    restores the right routes in a different order is value-correct but still diverts the entire
    search -- a defect invisible to any cost- or membership-based comparison.
    """
    chains = []
    for vehicle in sln.vehicles:
        sequence, current = [], vehicle.first_route.next_route
        while isinstance(current, Route):
            sequence.append(str(current))
            current = current.next_route
        chains.append(" , ".join(sequence))
    return (round(sln.solution_cost(), 9),
            " || ".join(chains),
            # Sorted membership per depot, not RouteSet order -- see depot_usage_problems.
            tuple(sorted((str(depot), tuple(sorted(str(r) for r in sln.depot_route_starts[depot])))
                         for depot in sln.depots)),
            # Content per position, not id(): CombineRoutes' revert legitimately rebuilds the
            # absorbed route as a NEW object (see TODO(revert-identity) on Route.split_at), so
            # object identity would fail there for a reason that isn't an ordering bug.
            tuple(str(route) for route in sln.all_routes))


def term_deltas(before: ObjectiveTermDelta, after: ObjectiveTermDelta) -> ObjectiveTermDelta:
    """Field-by-field after - before. Written out rather than splatted so each term keeps its
    declared type (a generator splat widens every field to the union of all of them)."""
    return ObjectiveTermDelta(
        travel_distance=after.travel_distance - before.travel_distance,
        vehicles_activated=after.vehicles_activated - before.vehicles_activated,
        depots_activated=after.depots_activated - before.depots_activated,
        total_route_overload=after.total_route_overload - before.total_route_overload,
        vehicles_overloaded=after.vehicles_overloaded - before.vehicles_overloaded,
    )
#endregion


#region Solver driving
class FakeClock:
    """
    A monotonic clock advancing a fixed tick per call.

    The solver terminates on wall-clock time, so any added instrumentation changes the iteration
    count and therefore the entire random walk -- meaning a bug reproducible in a clean run can
    vanish under measurement. Substituting this makes a run depend only on the seed.
    """

    def __init__(self, tick: float):
        self.now = 0.0
        self.tick = tick

    def __call__(self) -> float:
        self.now += self.tick
        return self.now


@contextlib.contextmanager
def deterministic_clock(solver, iterations: int):
    """Run a solve for a fixed number of iterations instead of a fixed wall-clock duration."""
    import SimAnn_VRP_Solver as solver_module
    real_time = solver_module.time.time
    solver_module.time.time = FakeClock(solver.max_time / iterations)
    try:
        yield
    finally:
        solver_module.time.time = real_time


@contextlib.contextmanager
def fixed_operator_sequence(solver, seed: int = 20260822):
    """
    Pin the operator sequence, so scoring can be tested without selection moving underneath it.

    Benjamin's idea. Normally a scoring change shifts weights, which shifts selection, which shifts
    the trajectory -- so any objective difference is unattributable. With the sequence pinned, the
    only thing that can move is the scoring.

    **Operators are drawn by sorted CLASS NAME, not by roster position.** Position changes when the
    roster is reordered or an operator is added, which would silently break the cross-version
    comparison this exists to support. A name-indexed sequence survives anything but a rename.

    The RNG is private to this helper, so it does not disturb the solver's own stream.
    """
    import random as _random

    ordered = sorted(solver.operators, key=lambda op: type(op).__name__)
    rng = _random.Random(seed)
    had_own = "choose_operator" in solver.__dict__
    previous = solver.__dict__.get("choose_operator")

    solver.choose_operator = lambda: ordered[rng.randrange(len(ordered))]
    try:
        yield
    finally:
        if had_own:
            solver.choose_operator = previous
        else:
            del solver.choose_operator


def run_solver(sln: FullSolution, max_time: float, debug_level: int = 3, iterations=None,
               deterministic_weighting: bool = False):
    """
    Build a solver, run it with stdout captured, and return (solver, captured_output).

    deterministic_weighting drops wall-clock timing out of operator weighting. Production
    weighting scores an operator by improvement per unit time, which couples the trajectory to
    machine speed -- correct for a stochastic solver, but it means identical seeds diverge. Set
    this only for tests that assert reproducibility.
    """
    from SimAnn_VRP_Solver import SimAnnVRPSolver
    solver = SimAnnVRPSolver(sln)
    solver.max_time = max_time
    if deterministic_weighting:
        solver.set_deterministic_weighting()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        solver.make_initial_solution()
        if iterations is None:
            solver.solve(debug_level=debug_level)
        else:
            with deterministic_clock(solver, iterations):
                solver.solve(debug_level=debug_level)
    return solver, buffer.getvalue()


def debug_findings(output: str) -> list[str]:
    return [line for line in output.splitlines() if "[debug]" in line]
#endregion


def vehicle_state(sln: FullSolution) -> str:
    """
    Every vehicle's route chain, ordered by vID. The state a move is supposed to change.

    Deliberately NOT fingerprint(): this carries no cost term. Comparing cost would be circular
    here, since the question being asked is whether a ZERO-COST move changed anything at all.
    """
    parts = []
    for vehicle in sorted(sln.vehicles, key=lambda v: v.vID):
        sequence, current = [], vehicle.first_route.next_route
        while isinstance(current, Route):
            sequence.append(str(current))
            current = current.next_route
        parts.append(f"v{vehicle.vID}: " + " , ".join(sequence))
    return " || ".join(parts)


@contextlib.contextmanager
def catch_mis_reported_noops(sln: FullSolution, tolerance: float = 1e-9):
    """
    Collect operators whose ZERO-DELTA moves leave the solution unchanged.

    A move worth nothing that also DOES nothing should have reported NOOP or INVALID. Reporting it
    VALID hands the operator undeserved weight, and under family-level selection that error would
    spread to every sibling (design/operator_selection/family_selection.md).

    Snapshots before propose() and compares after apply, which covers both operator kinds: an
    _evaluates_by_applying operator mutates during propose, a predictive one during apply. The
    span brackets whichever it is.

    Yields the findings list; it fills as the solve runs.
    """
    from SimAnn_VRP_Operators import Operator

    findings: list[tuple[str, str]] = []
    before: dict[int, str] = {}
    original_propose = Operator.propose
    original_apply = Operator.apply_for_acceptance

    def propose(self):
        before[id(self)] = vehicle_state(sln)
        return original_propose(self)

    def apply_for_acceptance(self, move):
        result = original_apply(self, move)
        if move.is_actionable and abs(move.improvement) < tolerance:
            if vehicle_state(sln) == before.get(id(self)):
                findings.append((type(self).__name__, str(move.kind)))
        return result

    Operator.propose = propose
    Operator.apply_for_acceptance = apply_for_acceptance
    try:
        yield findings
    finally:
        Operator.propose = original_propose
        Operator.apply_for_acceptance = original_apply
