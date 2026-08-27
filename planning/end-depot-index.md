# End-depot index for tail swaps

**Status:** measured and small. Worth doing when large instances matter.

## Problem

`SwapRouteTailsAtSharedDepot` needs routes that END at a given depot. `routes_sharing_depot` answers
that with an O(routes) scan over `sln.all_routes`.

Its twin `SwapRouteHeadsAtSharedDepot` needs routes that START at a depot, and gets it from
`sln.depot_route_starts`, an O(1) index maintained by the depot accounting.

## The measurement

Cost per proposal, five seeds per cell, cold and warm states agreeing within a few percent:

| operator | n=10 | n=100 | n=1000 | n=5000 | log-log slope |
|---|---|---|---|---|---|
| **SwapRouteTailsAtSharedDepot** | 15.0 | 17.6 | 35.4 | **118.2** | 0.32 |
| SwapRouteHeadsAtSharedDepot | 13.7 | 15.3 | 16.2 | 17.9 | 0.04 |

This is **the only operator in the roster whose cost depends on instance size.** Every other one is
flat.

Fitting the two largest points gives `14.8 us + 0.082 us per route`. That model then predicts the
two held-out points: 4 routes -> 15.1 (measured 15.0), 26 routes -> 16.9 (measured 17.6). At n=5000
the scan is 103 of its 118 us.

The indexed twin being flat across a 314x increase in route count is the control that makes the
number readable.

## Why it is not done

Start depots have a natural home. `depot_route_starts` is maintained because
`FullSolution.depots_used()` counts depots that at least one active route STARTS at — depot use is
loading the vehicle, not occupying a parking space. An end-depot index would have no such consumer,
so it is pure carrying cost: another structure to keep correct across every mutator, justified only
by one operator's selection speed.

There is also a real maintenance subtlety. A route's end depot is the next route's start depot, so
changing one end depot touches two entries, and route removal hands a departing route's start depot
to its successor.

## Gate

Instance sizes where 118 us per proposal matters. At n=500 with capacity 400 there are about 7
routes and this operator costs 13.6 us — cheaper than at capacity 25, because there are fewer routes
to scan. The problem only appears with many short routes.

## References

*(none yet)*

## Links to here

- [README.md](README.md)
