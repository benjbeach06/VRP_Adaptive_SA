# Warm start from a saved solution

**Status:** small and isolated. Good first task for a new contributor.

## Problem

`solutions/*.json` records a solution completely — every route's start depot, ordered customer IDs,
end depot and vehicle, plus the instance descriptor. Nothing loads one back. A run always begins
from the greedy construction in `make_initial_solution`, so a recorded best cannot be resumed,
improved, or used as a baseline.

## Design

A third constructor beside `make_initial_solution` and `make_dumb_initial_solution`. See
`TODO(warm-start)` on `SimAnnVRPSolver.make_initial_solution` for the same sketch in place.

Walk the routes in file order:

1. `Route([CustomerVisit(customers[cID]) for cID in path], ...)`
2. `set_end_depot(...)`
3. `sln.add_route_to_vehicle(route, vehicle)`

Then set `best_objective` and `curr_objective` from `sln.solution_cost()`.

**File order matters and does the hard work for free.** Within one vehicle the routes are
consecutive and chain depot to depot — each route's end depot is the next one's start depot — so
appending in order satisfies the chaining invariant without any special handling.

## The one real hazard

**Check the saved instance descriptor against the live instance first.** The file carries
`numpy_seed`, `num_customers`, the depot list, the vehicle list and all three cost coefficients. A
solution loaded onto a different instance is silently wrong: the routes will link, the invariants
will pass, and every objective will be meaningless.

## Verification

`solutions/best_3461.10.json` — and every other file in `solutions/` — was checked against a
freshly built seed-42 instance with geometry
recomputed from scratch: 200/200 customers covered exactly once, zero overload, vehicle depot
chaining intact, travel and objective agreeing to 5e-13. A loader should reproduce that objective
exactly on load, before any solving happens. That is the test.

## Gate

None.

## References

*(none yet)*

## Links to here

- [planning/README.md](../README.md)
- [vehicle-time-limits.md](vehicle-time-limits.md)
- [RESULTS.md](../../RESULTS.md) -- points here because the reference family's best-known objectives have no saved routes
