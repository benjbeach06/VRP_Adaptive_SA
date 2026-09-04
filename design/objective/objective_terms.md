# The objective

The objective is a weighted sum of nine quantities. Each quantity measures the solution. Each
weight prices it.

## Quantity and price are separate

`ObjectiveTermDelta` holds the nine quantities. `FullSolution` holds the nine weights. Nothing
stores a priced value.

The split is what lets a move be evaluated once and priced many times. An operator prices a move
relative to the current weights, whereas the solver can recompute them from scratch based on the given weights. 
These weights are technically free to change during a run, but doing so would corrupt the solver's "current objective" value. 

## Core objective

| quantity | what it counts | weight |
|---|---|---|
| `depots_activated` | depots that at least one active route starts at | `cost_per_depot` |
| `travel_distance` | total arc length over all routes | `unit_travel_cost` |
| `vehicles_activated` | vehicles that serve at least one customer | `cost_per_vehicle` |
| `vehicle_regular_hours` | duration up to `overtime_threshold` | `vehicle_hourly_rate` |
| `vehicle_overtime_hours` | duration above `overtime_threshold` | `vehicle_overtime_rate` |

The core objective is designed with delivery routes in mind.

**travel_distance** can be used to bundle gas and direct vehicle use costs, like gas and vehicle wear.

**depots_activated** can be use to account for any fixed costs associated with using a particular depot during 
a given time period. Eventually, it could also assist in cases where the problem to solve is depot placement: solving 
various representative routing problems with a set of candidate depot locations could assist in pinning down 
the most useful locations for building new depots in a new area, for example. However, to 
make this work, an optional constraint would need to be implemented to prevent an active vehicle from ending at an inactive depot.

**vehicles_activated** covers core costs for using a vehicle. This has several potential use cases:
1) At fleet planning time, one can again solve representative
routing problems to get a sense of how many vehicles are needed. 
2) Including any true fixed costs for using a vehicle, to discourage using vehicles unnecessarily  
3) If used with high objective, it can be used to probe for the minimum number of vehicles needed with a given set 
of duration and loading constraints.

**_Paying the driver_**: **vehicle_regular_hours** and **vehicle_overtime_hours** are intended to directly count regular and overtime salaries,
based on an hourly wage.  


## Feasibility: Violation penalties

| quantity | what it counts | weight |
|---|---|---|
| `total_route_overload` | load above capacity, summed over routes | `unit_overload_penalty` |
| `vehicles_overloaded` | vehicles with at least one overloaded route | `vehicle_overload_penalty` |
| `vehicle_excess_hours` | duration above `time_limit` | `vehicle_excess_hour_rate` |
| `vehicles_over_time_limit` | vehicles above `time_limit` | `vehicle_time_limit_penalty` |

**total_route_overload** and **vehicles_overloaded** enforce vehicle load limits as soft constraints - intended as severe penalties.

**vehicle_excess_hours** and **vehicles_over_time_limit** penalize delivery shifts exceeding legal or contractual duration limits.

Generally, we include both steep activation and steep continuous penalties for feasibility constraints, serving two distinct purposes.

1) Activation penalties are the enforcement: "Don't violate the constraint". Without this, the solver may decide a small violation is worth the penalty.
2) Continuous penalties are the nudge: "Reduce violation". Without this, the solver can get stuck in flat infeasible regions: multiple, or even sometimes many, operations
can be needed to restore feasibility of a constraint. In this case, the solver can get stuck in massive infeasible regions with no indication of how to escape.

Note: an `overtime_threshold` above a `time_limit` is refused. Overtime starts before the legal
bound, never after it. An unset overtime threshold is accepted: it means there is no overtime band,
and every hour up to the limit is regular pay.

## Activity is customers, not assignment

A **route** is active when it serves customers. An empty route assigned to a vehicle is not active, and it activates neither the
vehicle nor its depot.

A **vehicle** is active when it serves at least one customer, i.e. has an active route.

A **depot** is active if some active route starts there, i.e. some vehicle is loaded there.
Occupying a parking space at the end of the day does not count as a depot activation.

## Vehicle duration

A vehicle accrues duration from three sources:

```
  travel_time_per_distance  x  distance travelled
+ service_time_per_customer x  customers served
+ load_time_per_route       x  active routes       (depot loading stages)
```

Each input has its own constant, so any one can be switched off by zeroing it. All three are zero
by default, which **disables** computation for the whole duration objective. Conversely,
if any input is nonzero, the true duration is computed and reported - even in the absence of associated
costs and bounds.

### Duration is derived, not cached

All three inputs are already maintained per vehicle: distance, customer count, and active route
count. Duration is computed from them on every read.

A cached duration was rejected. It would be the only cache in this solver that depends on an
objective weight, so changing a weight would silently invalidate every stored value. Every other
cache here is structural, and stays true whatever the objective costs.

The same three caches are what make the duration terms cost nothing to add. The processor already
builds a per-vehicle delta for each of them, so a duration delta is arithmetic over deltas that
exist. Neither the raw record nor the accounting record gained a field. See
[design/raw_delta_accounting/](../raw_delta_accounting/README.md) for how those deltas are produced
and applied.

### Duration pricing

Two thresholds cut a vehicle's duration into priced bands. `overtime_threshold` ends regular pay and 
begins overtime pay. `time_limit` is the legal or contractual bound on a shift.

The overtime band has no upper end. Past `time_limit`, an hour is counted as overtime **and** as
excess, so its price is the sum of the two rates. The overlap ensures that working time is still priced  
even if exceeding the time limit carries no special penalty.

The duration-based price is then

```
  vehicle_regular_hours     x  vehicle_hourly_rate 
+ vehicle_overtime_hours    x  vehicle_overtime_rate
+ vehicle_excess_hours      x  vehicle_excess_hour_rate (where excess hours count as overtime too)
+ vehicles_over_time_limit  x  vehicle_time_limit_penalty
```

### Configuration

`FullSolution.set_vehicle_duration_objectives` sets _every_ duration-related constant at once. Unspecified terms are 
set to their default values.

`FullSolution.set_objectives` sets the rest of the objective terms - also all at once, with 
unspecified terms set to default values.

For true objective terms **An unset threshold is infinite, and an unset price is
zero.** Both mean the related terms are not considered. However, penalty violations are 
given very large prices by default if their corresponding constraints are activated.

When `time_limit` is set, the defaults are 

- `vehicle_time_limit_penalty` = 1000 per vehicle over the limit;
- `vehicle_excess_hour_rate` = 10x the overtime rate, or 10x the hourly rate when no overtime
  rate was given.

The default vehicle overloading penalties are

- `unit_overload_penalty` = 1000 per vehicle load over capacity 
- `vehicle_overload_penalty` = 100000 per vehicle overloaded 


## Terms as deltas

`ObjectiveTermDelta` is used two ways. `FullSolution.objective_terms()` returns the nine absolute
totals, measured from the structure. A `Move` carries the nine deltas its mutation causes.

The two share one type so a prediction can be differenced against a measurement term by term. That
locates a wrong term instead of reporting a wrong total.

Every delta is produced by the accounting processor from one raw record. See
[design/raw_delta_accounting/](../raw_delta_accounting/README.md).

## References

- [design/raw_delta_accounting/README.md](../raw_delta_accounting/README.md) -- produces every one of these nine terms as a delta, and maintains the three per-vehicle caches the duration terms read

## Links to here

- [design/README.md](../README.md) -- the design index; lists this doc as the objective area
- [retros/2026-09-04_vehicle_duration_objective.md](../../retros/2026-09-04_vehicle_duration_objective.md) -- the session that produced this doc, and the design calls made in it
