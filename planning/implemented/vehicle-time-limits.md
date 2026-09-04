# Per-vehicle time limits

**Status: IMPLEMENTED. A vehicle accrues duration from distance, customers and routes run, and
that duration is priced in four bands. Off by default.
[route-distance-tracking](route-distance-tracking.md), the blocking prerequisite, landed first.**

The largest step this model took toward resembling real delivery routing. Capacity used to be the
only per-vehicle constraint, and in practice a working day runs out before a truck fills up.

## The duration

Each vehicle accrues duration from three sources:

```
  travel_time_per_distance  x  total distance travelled
+ service_time_per_customer x  customers served
+ load_time_per_route       x  routes run          (depot loading stages)
```

Each input is a separate constant, so any of them can be switched off by setting it to zero. All
three are zero by default, and that is what turns the whole objective off.

The three inputs are per-vehicle aggregates that the accounting pipeline already maintained:

| input | source |
|---|---|
| total distance | `Vehicle.current_travel` |
| customers served | `Vehicle.num_customers` |
| routes run | `Vehicle.num_routes_with_customers` |

**"Routes run" is the ACTIVE route count, not the length of the vehicle's route list.** An empty
route in that list is a modelling artifact between cleanups, and no truck was loaded for it.

All three are sink-written caches, so each still holds its pre-mutation value when an operator
prices by mutating. That is what makes the duration base safe to read during pricing.

## Price it, do not forbid it

Duration is never rejected. It is cut into bands and each band carries a price:

| quantity | band | price |
|---|---|---|
| `vehicle_regular_hours` | up to `overtime_threshold` | `vehicle_hourly_rate` |
| `vehicle_overtime_hours` | above `overtime_threshold`, uncapped | `vehicle_overtime_rate` |
| `vehicle_excess_hours` | above `time_limit` | `vehicle_excess_hour_rate` |
| `vehicles_over_time_limit` | one per vehicle above `time_limit` | `vehicle_time_limit_penalty` |

**The overtime and excess bands overlap past `time_limit` on purpose.** An hour beyond the legal
bound is counted in both, so its marginal price is the sum of the two rates. That keeps the
objective SLOPED past the limit. A capped overtime band would make every duration past the limit
cost the same once the flat penalty had fired, and the search would have no gradient to walk a
violating vehicle back down.

The flat per-vehicle penalty sits beside the linear excess rate for the same reason
`vehicle_overload_penalty` sits beside `unit_overload_penalty`: the magnitude term prices how far
over a vehicle is, and the activation term prices how many vehicles are over at all.

A hard constraint would wall off exactly the moves that make multi-vehicle rebalancing work, and
the solver's whole design assumes it can pass through infeasibility.

## Configuring it

`FullSolution.set_vehicle_duration_objectives` takes every constant. Each call is a full reset, not
a patch, so one call always describes the whole duration objective.

An argument left unspecified resolves by KIND. A threshold becomes `NO_TIME_LIMIT` and a price
becomes zero; both read as "this band is off", where a literal zero threshold would mean the
opposite. Two prices resolve differently when `time_limit` is set, because a stated legal bound
with no stated consequence is a bound the search would ignore:

- `vehicle_time_limit_penalty` becomes 1000 per vehicle over the limit;
- `vehicle_excess_hour_rate` becomes 10x the overtime rate, or 10x the hourly rate when no
  overtime rate was given.

An `overtime_threshold` above a finite `time_limit` is refused. Overtime starts before the legal
bound, never after it. An unset overtime threshold is not refused: it means there is no overtime
band, and every hour up to the limit is regular pay.

## What it costs the operators

Capacity is per route: moving a customer changes the load of at most two routes, and both are local
to the move. Duration is per vehicle, so the affected quantity is an aggregate over a vehicle's
entire route list.

- Any move that relocates a customer between vehicles changes two vehicles' durations.
- `ChangeRandomEndDepot` changes distance, and therefore duration, without moving any customer.
- `SplitRandomRoute` and `CombineRandomRoutes` change the active route count, which is its own
  input, so they carry a duration delta even when distance and customers hold still.

Every one of these is O(1), because the processor differences the three per-vehicle aggregates it
already builds. **Neither the raw record nor the accounting record gained a field.** The duration
is derived from three existing caches on every read rather than cached itself, which keeps every
cache in this codebase structural instead of tied to objective coefficients.

The processor skips the whole block when all three inputs are zero. That is exact, not a shortcut:
with no duration accruing, every band is zero and there is nothing to predict.

## Verification

- **A recompute twin**, `recompute_vehicle_duration`, walks the routes instead of reading the three
  caches, and shares no cache with the live form.
- **The randomised operator sweep runs a second time with the objective on and its thresholds
  BINDING**, so the four terms are graded predicted-against-measured for every operator in the
  roster. Binding is the point: with the limit above every vehicle's real duration, the excess and
  over-limit terms stay zero however wrong the arithmetic is.
- **A tight-limit check that the terms actually fire.** A penalty term that is silently never
  triggered looks identical to a solver that satisfies the constraint easily, and the second
  reading is much more flattering than it deserves. The limit is set below what the solution
  already does, and the cost is required to move.

Fault injection confirmed each detector fires: breaking any one of the three duration inputs, or
counting all routes instead of active ones, fails a test.

The session that built it, and what it taught us, is
[retros/2026-09-04_vehicle_duration_objective.md](../../retros/2026-09-04_vehicle_duration_objective.md).

## References

- [route-distance-tracking.md](route-distance-tracking.md)
- [retros/2026-09-04_vehicle_duration_objective.md](../../retros/2026-09-04_vehicle_duration_objective.md) -- the session that built this, and what it taught us

## Links to here

- [design/operator_selection/share_floors.md](../../design/operator_selection/share_floors.md)
- [planning/README.md](../README.md)
- [planning/problem-model/asymmetric-distances.md](../problem-model/asymmetric-distances.md)
- [route-distance-tracking.md](route-distance-tracking.md)
- [raw-delta-accounting.md](raw-delta-accounting.md)
- [RESULTS.md](../../RESULTS.md) -- states that the MDVRPI benchmark cannot be run until this lands
- [retros/2026-09-04_vehicle_duration_objective.md](../../retros/2026-09-04_vehicle_duration_objective.md) -- the retro for the period this landed in
