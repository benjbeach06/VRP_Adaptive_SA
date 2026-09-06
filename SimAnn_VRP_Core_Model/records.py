"""
The accounting data structures: what a mutation reports, and what the sink writes.

Three immutable NamedTuples, and the arithmetic that composes and inverts them:

  ObjectiveTermDelta -- priced objective movement, one field per objective term
  RawDeltaRecord     -- RAW structural change only, straight out of the core model
  AccountingRecord   -- RESOLVED cache updates, ready for FullSolution to apply

The processor that turns the second into the first and the third is SimAnn_VRP_Accounting, and it
is deliberately outside this package: the core model reports raw transitions and resolves nothing.
See design/raw_delta_accounting/.

Route and Vehicle appear here only in annotations, which is what lets this module sit BELOW them.
The record builders read `route.num_customers`, `route.current_load`, `route.start_depot` and
`route.vehicle` structurally, and never construct or isinstance-test either class.
"""
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, NamedTuple

from .basics import Num
from .nodes import VIRTUAL_DEPOT, Depot

if TYPE_CHECKING:
    from .routes import Route
    from .vehicle import Vehicle

class ObjectiveTermDelta(NamedTuple):
    travel_distance: Num = 0
    vehicles_activated: int = 0
    depots_activated: int = 0
    total_route_overload: Num = 0
    vehicles_overloaded: int = 0
    # Vehicle-duration quantities, priced by FullSolution. See design/objective/objective_terms.md.
    vehicle_regular_hours: Num = 0
    vehicle_overtime_hours: Num = 0
    vehicle_excess_hours: Num = 0
    vehicles_over_time_limit: int = 0

    def __pos__(self) -> ObjectiveTermDelta:
        return ObjectiveTermDelta(self.travel_distance, self.vehicles_activated, self.depots_activated, self.total_route_overload, self.vehicles_overloaded,
                                  self.vehicle_regular_hours, self.vehicle_overtime_hours, self.vehicle_excess_hours, self.vehicles_over_time_limit)

    def __neg__(self) -> ObjectiveTermDelta:
        return ObjectiveTermDelta(-self.travel_distance, -self.vehicles_activated, -self.depots_activated, -self.total_route_overload, -self.vehicles_overloaded,
                                  -self.vehicle_regular_hours, -self.vehicle_overtime_hours, -self.vehicle_excess_hours, -self.vehicles_over_time_limit)

    def __add__(self, other: Any) -> Any:
        if isinstance(other, ObjectiveTermDelta):
            return ObjectiveTermDelta(self.travel_distance + other.travel_distance, self.vehicles_activated + other.vehicles_activated,
                                      self.depots_activated + other.depots_activated, self.total_route_overload + other.total_route_overload, self.vehicles_overloaded + other.vehicles_overloaded,
                                      self.vehicle_regular_hours + other.vehicle_regular_hours, self.vehicle_overtime_hours + other.vehicle_overtime_hours,
                                      self.vehicle_excess_hours + other.vehicle_excess_hours, self.vehicles_over_time_limit + other.vehicles_over_time_limit)

        if isinstance(other, tuple):
            return tuple.__add__(self, other)

        return NotImplemented

    def __sub__(self, other: ObjectiveTermDelta) -> ObjectiveTermDelta:
        return self + (-other)

    def get_cost_delta(self, travel_unit_cost: Num = 0.0, vehicle_cost: Num = 0.0, depot_cost: Num = 0.0, route_overload_penalty: Num = 0.0, vehicle_overload_penalty: Num = 0.0,
                       vehicle_hourly_rate: Num = 0.0, vehicle_overtime_rate: Num = 0.0, vehicle_excess_hour_rate: Num = 0.0, vehicle_time_limit_penalty: Num = 0.0) -> Num:
        """
            Returns the change in cost implied by the deltas stored here, given objective coefficients.
        """
        return travel_unit_cost * self.travel_distance + vehicle_cost * self.vehicles_activated +\
            depot_cost * self.depots_activated + route_overload_penalty * self.total_route_overload +\
            vehicle_overload_penalty * self.vehicles_overloaded +\
            vehicle_hourly_rate * self.vehicle_regular_hours + vehicle_overtime_rate * self.vehicle_overtime_hours +\
            vehicle_excess_hour_rate * self.vehicle_excess_hours + vehicle_time_limit_penalty * self.vehicles_over_time_limit

    def get_cost_improvement(self, travel_unit_cost: Num = 0.0, vehicle_cost: Num = 0.0, depot_cost: Num = 0.0, overload_penalty: Num = 0.0, vehicle_overload_penalty: Num = 0.0,
                             vehicle_hourly_rate: Num = 0.0, vehicle_overtime_rate: Num = 0.0, vehicle_excess_hour_rate: Num = 0.0, vehicle_time_limit_penalty: Num = 0.0,
                             minimizing: bool = True) -> Num:
        """
           Returns the improvement value (positive = better) based on cost deltas and weights.
           If minimizing: improvement = -cost_delta (i.e., cost reduction is good).
           If maximizing: improvement = +cost_delta (i.e., increase is good).
        """
        sign = -1 if minimizing else 1
        return sign * self.get_cost_delta(travel_unit_cost, vehicle_cost, depot_cost, overload_penalty, vehicle_overload_penalty,
                                          vehicle_hourly_rate, vehicle_overtime_rate, vehicle_excess_hour_rate, vehicle_time_limit_penalty)

# The default for a field no mutation touched. IMMUTABLE, and shared by every record that omits
# that field -- which is the only way a NamedTuple can default a mapping at all. A plain {} default
# would be ONE dict shared across every record ever built, and the first aggregator to write into
# it would corrupt every other record silently.
#
# Sharing is safe because a record is read-only after construction, and it is the cheaper option
# besides: an omitted field now allocates NOTHING, where the explicit four-dict form allocated four
# dicts per proposal whether or not a mutation touched them.
NO_CHANGES: Mapping[Any, Any] = MappingProxyType({})

class RawDeltaRecord(NamedTuple):
    """
    Everything the core model reports about one mutation: raw structural change, and nothing else.

    No activation, no overload, no objective terms. Resolving those belongs to the processor, which
    is the only place a step function is evaluated. See
    planning/core-refactors/raw-delta-accounting.md.

    ONE MAP PER FIELD, AND A ROUTE APPEARS ONLY IN THE MAPS IT ACTUALLY MOVED IN. A route that
    changes nothing but its start depot appears in `start_depot_changes` and nowhere else.
    Nothing writes a (x, x) entry to say "this held still" -- absence says it, for free.

    ABSENT MEANS UNCHANGED, and the consumer reads the current value off the key. That is what
    makes the omission safe: the base a step function needs is on the Route object already, and it
    is still valid precisely because the field did not move. Plain dicts, so `route in map` is the
    whole membership test; `.get(route, NOMOVE)` gives a typed read where a uniform shape is easier
    than a branch. (STALE COMMENT)

    THE COST OF THE SHAPE: an entry that is missing but SHOULD be there is silent. It reads back as
    "held still" and prices the move as if that part never happened, with nothing malformed to trip
    over. raw_record_completeness_problems is what stands between that and a wrong objective, which
    makes it load-bearing rather than a convenience.

    Routes key by object IDENTITY, which is safe: identity survives an apply -> revert cycle
    because split_at refills the original object rather than constructing a fresh one, and RouteSet
    already keys a dict on Route for the same reason.

    The dicts must not be mutated after construction.
    """
    # TRAVEL IS PER ROUTE, AND IT IS A PLAIN DELTA, not a transition. Distance has no step
    # function of its own, so the sink can add and the inverse can negate -- the same treatment
    # the vehicle counters get, one level down. The bulk figure the objective wants is DERIVED
    # from this map (see travel_distance below), so there is one source rather than two.
    travel_changes: Mapping[Route, Num] = NO_CHANGES
    load_changes: Mapping[Route, tuple[Num, Num]] = NO_CHANGES
    customer_deltas: Mapping[Route, tuple[int, int]] = NO_CHANGES
    start_depot_changes: Mapping[Route, tuple[Depot, Depot]] = NO_CHANGES
    vehicle_changes: Mapping[Route, tuple[Vehicle | None, Vehicle | None]] = NO_CHANGES

    @property
    def travel_distance(self) -> Num:
        """The solution-level travel delta: the per-route deltas, summed.

        Derived rather than stored. A stored total beside a per-route map is two derivations of
        one quantity, which is the structure this pipeline exists to remove.
        """
        return sum(self.travel_changes.values())

    @staticmethod
    def empty() -> RawDeltaRecord:
        """A record reporting no change at all."""
        return RawDeltaRecord()

    @staticmethod
    def for_travel(route: Route, travel_delta: Num) -> RawDeltaRecord:
        """
        Distance moved on ONE route and nothing else -- every intra-route mutation has this shape.
        Convenience method for TESTING ONLY. It's just an unnecessary indirection for production code.
        """
        return RawDeltaRecord(travel_changes={route: travel_delta})

    @staticmethod
    def for_customers_changing(*changes: tuple[Route, Num, Num, int]) -> RawDeltaRecord:
        """
        The most common shape: routes gain or lose customers, and nothing else about them moves.

        Each change is (route, travel_delta, load_delta, count_delta), and writes ONE entry into
        each of the three numeric maps. Start depot and vehicle hold, so those maps stay empty --
        a route keeps its depot and its vehicle when its customer list changes.

        TRAVEL IS PER ROUTE HERE TOO. A cross-route move's priced travel is not one route's change:
        the source loses the moved chain's interior arcs and the destination gains them, and the
        two are only jointly equal to the link-delta total. Each caller therefore hands in the
        share that belongs to each route.

        An entry whose two ends are equal is dropped rather than written, so a same-route move that
        cancels leaves no trace and needs no special branch at the call site.
        """
        travels: dict[Route, Num] | Mapping[Any, Any] = {}
        loads: dict[Route, tuple[Num, Num]] | Mapping[Any, Any] = {}
        counts: dict[Route, tuple[int, int]] | Mapping[Any, Any] = {}
        depot_starts: dict[Route, tuple[Depot, Depot]] | Mapping[Any, Any] = {}

        for route, travel_delta, load_delta, count_delta in changes:
            if travel_delta:
                assert isinstance(travels, dict)
                travels[route] = travels.get(route, 0) + travel_delta
            old_num_customers = route.num_customers
            new_num_customers = old_num_customers + count_delta
            if load_delta:
                assert isinstance(loads, dict)
                loads[route] = (route.current_load, route.current_load + load_delta)
            if count_delta:
                assert isinstance(counts, dict)
                counts[route] = (old_num_customers, new_num_customers)

            is_assigned = route.vehicle is not None

            old_is_active = is_assigned and old_num_customers > 0
            new_is_active = is_assigned and new_num_customers > 0
            active_delta = new_is_active - old_is_active
            if active_delta != 0:
                old_start_depot = route.start_depot if old_is_active else VIRTUAL_DEPOT
                new_start_depot = route.start_depot if new_is_active else VIRTUAL_DEPOT

                assert isinstance(depot_starts, dict)
                depot_starts[route] = (old_start_depot, new_start_depot)



        # `or _NO_CHANGES` rather than the dict itself: a mutation that moves count but not load
        # (a customer swap) should leave the load map costing nothing.
        return RawDeltaRecord(travel_changes=travels or NO_CHANGES,
                              load_changes=loads or NO_CHANGES,
                              customer_deltas=counts or NO_CHANGES,
                              start_depot_changes=depot_starts or NO_CHANGES)

    def then(self, later: RawDeltaRecord) -> RawDeltaRecord:
        """
        Compose two records applied in order: self first, then `later`.

        Travel is a per-route delta, so the two maps ADD. Each transition map chains independently
        on its key, and an entry DROPS when the two ends MATCH.

        `later` must have been measured against the state `self` left -- that is what makes the
        chain valid. Asserted on the fields where a mismatch means a genuine composition bug rather
        than float drift; load is exempt for exactly that reason, and a wrong load surfaces in the
        overload term anyway.

        Iteration is self's keys first, then keys only `later` touched. Deterministic, so two equal
        compositions build identical dicts.
        """
        return RawDeltaRecord(
            travel_changes=_summed(self.travel_changes, later.travel_changes),
            load_changes=_chained(self.load_changes, later.load_changes,
                                        "load", check_gap=False, numeric=True),
            customer_deltas=_chained(self.customer_deltas,
                                           later.customer_deltas, "customer count"),
            # == not `is` for depots: Depot inherits object.__eq__, so == IS identity for every real
            # depot, and additionally correct for VirtualDepot, which makes all virtuals equal. A
            # record priced before unlink_from_vehicle cannot hold the fresh VirtualDepot that call
            # will construct, so `is` would report a gap that is not one.
            start_depot_changes=_chained(self.start_depot_changes,
                                         later.start_depot_changes, "start depot"),
            vehicle_changes=_chained(self.vehicle_changes,
                                           later.vehicle_changes, "vehicle"))


def _chained[K, V](first: Mapping[K, tuple[V, V]], second: Mapping[K, tuple[V, V]], field: str,
                   check_gap: bool = True, numeric: bool = False) -> Mapping[K, tuple[V, V]]:
    """One field's map across two records applied in order. See RawDeltaRecord.then()."""
    merged: dict[K, tuple[V, V]] = {}
    for key in (*first, *(k for k in second if k not in first)):
        if key not in first:
            initial, final = second[key]
        elif key not in second:
            initial, final = first[key]
        elif numeric:
            # COMPOSE BY DELTA, NOT BY ENDPOINT, and it is correct either way.
            #
            # A sink-written base does not move when the structure does, so an operator that
            # prices two sub-steps against ONE route reads the SAME pre-move base both times.
            # Keeping the second record's final then silently discards the first step's delta:
            # two removals of 10 and 11 from a load of 75 composed to (75, 64) where the truth is
            # (75, 54), and the sink wrote 64. Nothing in the roster takes two sub-steps on one
            # route today, so this was latent; ruin-and-recreate reaches it immediately.
            #
            # If the second base was stale, its two ends differ by exactly that step's true delta,
            # so adding that delta to the first record's final is right. If the second base was
            # live, second[0] == first[1] and this collapses to second[1] -- also right. So it
            # needs no knowledge of which case it is in, which is why the gap check can stay off.
            initial = first[key][0]
            final = first[key][1] + (second[key][1] - second[key][0])  # type: ignore[operator]
        else:
            assert not check_gap or first[key][1] == second[key][0], (
                f"composition gap for {key} on {field}: the first record leaves "
                f"{first[key][1]!r}, the second starts from {second[key][0]!r}. The second record "
                f"was not measured against the state the first one left.")
            initial, final = first[key][0], second[key][1]

        if initial != final:
            merged[key] = (initial, final)
    # A composition that cancels everything in this field costs nothing to carry.
    return merged or NO_CHANGES


def _summed[K](first: Mapping[K, Num], second: Mapping[K, Num]) -> Mapping[K, Num]:
    """One DELTA map across two records applied in order. Deltas add; a zero entry drops.

    Iteration is first's keys, then keys only `second` touched, so two equal compositions build
    identical dicts.
    """
    if first is NO_CHANGES:
        return second
    if second is NO_CHANGES:
        return first

    merged: dict[K, Num] = {}
    for key in (*first, *(k for k in second if k not in first)):
        total = first.get(key, 0) + second.get(key, 0)
        if total:
            merged[key] = total
    return merged or NO_CHANGES


# Branch-free helper for inverting delta dict
INVERT_STRATEGIES_DELTA_DICT = {
    True: lambda _: NO_CHANGES,
    False: lambda d: {k: -v for k, v in d.items()}
}
def invert_delta_dict(dct: dict[Any, Num] | Mapping[Any, Any]) -> dict[Any, Num] | Mapping[Any, Any]:
    assert isinstance(dct, dict) or dct is NO_CHANGES
    return INVERT_STRATEGIES_DELTA_DICT[dct is NO_CHANGES](dct)


# Branch-free helper for inverting delta dict
INVERT_STRATEGIES_CHANGE_DICT = {
    True: lambda _: NO_CHANGES,
    False: lambda d: {k: (vf, vi) for k, (vi, vf) in d.items()}
}
def invert_change_dict(dct: dict[Any, tuple[Any, Any]] | Mapping[Any, Any]) -> dict[Any, tuple[Any, Any]] | Mapping[Any, Any]:
    assert isinstance(dct, dict) or dct is NO_CHANGES
    return INVERT_STRATEGIES_CHANGE_DICT[dct is NO_CHANGES](dct)

class AccountingRecord(NamedTuple):
    """
    Resolved cache updates, ready to write. Applying one DECIDES NOTHING.

    Every step function was already evaluated by the processor. If applying this record ever needs
    a threshold comparison or a zero-crossing test, the processing has leaked into the sink -- see
    planning/core-refactors/raw-delta-accounting.md.
    """
    # VEHICLE accounting records: routes_overloaded, routes_with_customers, num_customers.
    vehicle_delta_routes_overloaded: dict[Vehicle, int] | Mapping[Any, Any] = NO_CHANGES
    vehicle_delta_active_routes: dict[Vehicle, int] | Mapping[Any, Any] = NO_CHANGES
    vehicle_delta_num_customers: dict[Vehicle, int] | Mapping[Any, Any] = NO_CHANGES

    # Travel distance travelled by each vehicle. A plain delta, like the counters above: distance
    # has no threshold of its own, so the sink adds and the inverse negates.
    vehicle_delta_travel: dict[Vehicle, Num] | Mapping[Any, Any] = NO_CHANGES

    # ROUTE accounting records: Just raw loads. Counts are accounted via path length.
    route_loads: dict[Route, tuple[Num, Num]] | Mapping[Any, Any] = NO_CHANGES

    # Travel distance on each route, straight through from the raw record.
    route_delta_travel: dict[Route, Num] | Mapping[Any, Any] = NO_CHANGES

    # DEPOT accounting records: just raw depot changes, since depot_starts must be fully updated.
    start_depot_changes: dict[Route, tuple[Depot, Depot]] | Mapping[Any, Any] = NO_CHANGES

    @property
    def is_empty(self) -> bool:
        return (self.vehicle_delta_routes_overloaded == NO_CHANGES and
                self.vehicle_delta_active_routes == NO_CHANGES and
                self.vehicle_delta_num_customers == NO_CHANGES and
                self.vehicle_delta_travel == NO_CHANGES and
                self.route_loads == NO_CHANGES and
                self.route_delta_travel == NO_CHANGES and
                self.start_depot_changes == NO_CHANGES)

    @property
    def inverse(self) -> AccountingRecord:
        # Unpack the record
        vehicle_delta_routes_overloaded, vehicle_delta_active_routes, vehicle_delta_num_customers, \
            vehicle_delta_travel, route_loads, route_delta_travel, start_depot_changes = self

        # Invert each record
        vehicle_delta_routes_overloaded = invert_delta_dict(vehicle_delta_routes_overloaded)
        vehicle_delta_active_routes = invert_delta_dict(vehicle_delta_active_routes)
        vehicle_delta_num_customers = invert_delta_dict(vehicle_delta_num_customers)
        vehicle_delta_travel = invert_delta_dict(vehicle_delta_travel)

        route_loads = invert_change_dict(route_loads)
        route_delta_travel = invert_delta_dict(route_delta_travel)
        start_depot_changes = invert_change_dict(start_depot_changes)

        return AccountingRecord(vehicle_delta_routes_overloaded = vehicle_delta_routes_overloaded,
                                vehicle_delta_active_routes = vehicle_delta_active_routes,
                                vehicle_delta_num_customers = vehicle_delta_num_customers,
                                vehicle_delta_travel = vehicle_delta_travel,
                                route_loads = route_loads,
                                route_delta_travel = route_delta_travel,
                                start_depot_changes = start_depot_changes)
