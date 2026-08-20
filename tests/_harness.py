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
    seed_solver_rng,
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
    """Each vehicle's route chain must be well-formed and depot-consistent."""
    problems = []
    for vehicle in sln.vehicles:
        seen = set()
        current = vehicle.first_route.next_route
        previous = vehicle.first_route
        while isinstance(current, Route):
            if id(current) in seen:
                problems.append(f"vehicle {vehicle.vID}: cycle in route chain at {current}")
                break
            seen.add(id(current))
            if current.prev_route is not previous:
                problems.append(f"vehicle {vehicle.vID}: {current}.prev_route is not its predecessor")
            if current.start_depot is not previous.end_depot:
                problems.append(f"vehicle {vehicle.vID}: {current} start depot != predecessor end depot")
            if current.vehicle is not vehicle:
                problems.append(f"vehicle {vehicle.vID}: {current}.vehicle points elsewhere")
            previous, current = current, current.next_route
        if vehicle.last_route.start_depot is not previous.end_depot:
            problems.append(f"vehicle {vehicle.vID}: LastRoute.start_depot != final route's end depot")
    return problems


def load_problems(sln: FullSolution) -> list[str]:
    return [f"{route}: cached load {route.current_load} != recomputed {route.recompute_current_load()}"
            for route in sln.all_routes
            if abs(route.recompute_current_load() - route.current_load) > 1e-9]


def all_problems(sln: FullSolution) -> list[str]:
    return (visit_link_problems(sln) + depot_usage_problems(sln)
            + chain_problems(sln) + load_problems(sln))


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
