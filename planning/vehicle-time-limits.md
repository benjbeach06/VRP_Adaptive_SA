# Per-vehicle time limits

**Status: not started. Blocked on
[route-distance-tracking](route-distance-tracking.md).**

The single largest step this model could take toward resembling real delivery routing. Capacity is
currently the only per-vehicle constraint, and in practice a working day runs out before a truck
fills up.

## The constraint

Each vehicle accumulates time from three sources, and the total is capped:

```
  travel_time_per_distance  x  total distance travelled
+ service_time_per_customer x  customers served
+ load_time_per_route       x  routes run          (depot loading stages)
<= vehicle time limit
```

Each term is a separate constant so any of them can be switched off by setting it to zero, matching
how the objective terms already work.

The three inputs are all per-vehicle aggregates:

| term | source |
|---|---|
| total distance | **[route-distance-tracking](route-distance-tracking.md)** — does not exist yet |
| customers served | sum of `num_customers` over the vehicle's routes |
| routes run | length of the vehicle's route list |

Only the first is missing, which is why that plan is the blocker and why it is worth doing first
rather than folding the two together.

## Price it, do not forbid it

Follow capacity. Overload is not rejected — it carries `unit_overload_penalty` per unit and
`vehicle_overload_penalty` per overloaded vehicle, high enough that any feasible solution beats any
infeasible one, low enough that the search can cross an infeasible region to reach a better feasible
one.

Time overage gets the same two-part treatment and the same reasoning. A hard constraint here would
wall off exactly the moves that make multi-vehicle rebalancing work, and the solver's whole design
assumes it can pass through infeasibility.

## What it costs the operators

This is the part to think through before starting, because it is where the work actually is.

Capacity is **per route**: moving a customer changes the load of at most two routes, and both are
local to the move. Time is **per vehicle**, so the affected quantity is an aggregate over a
vehicle's entire route list.

Consequences:

- Any move that relocates a customer between vehicles changes two vehicles' time totals.
- `ChangeRandomEndDepot` changes distance, and therefore time, without moving any customer.
- `SplitRandomRoute` and `CombineRandomRoutes` change the **route count**, which is its own time
  term — so they now have a time delta even when distance and customers are unchanged. That is a
  new interaction and it is easy to miss.

Every one of these is O(1) given maintained per-vehicle totals. None of them is O(1) without.

## Verification

Oracle twin for per-vehicle time, recomputed from the three raw inputs. Then the thing most likely
to be wrong: **a fault-injection check that time overage actually changes the objective.** A new
penalty term that is silently never triggered looks identical to a solver that satisfies the
constraint easily, and the second reading is much more flattering than it deserves.

Set a limit deliberately too tight, confirm the penalty fires and the search responds. Only then
trust a run where it does not fire.

## Gate

`route-distance-tracking` first. Beyond that, this is the highest-value functional addition
available — it is what separates a capacitated VRP from something a dispatcher would recognize.

Worth doing **before** publication if there is time, and it pairs naturally with
[warm-start](warm-start.md) since a realistic instance is the one worth saving and reloading.
