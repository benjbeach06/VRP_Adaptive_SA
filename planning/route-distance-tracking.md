# Track total distance on routes and vehicles

**Status: not started. Prerequisite for [vehicle-time-limits](vehicle-time-limits.md).**

## The problem

`Route.total_distance()` walks the route and sums arcs. Nothing stores it.

The solution-level travel term *is* maintained incrementally — every mutation has a
`travel_delta_if_*` that prices it in O(1) from boundary arcs — but that delta is applied to one
global total. No route knows its own length, and no vehicle knows the sum of its routes'.

That is fine while the objective is the only consumer. It stops being fine the moment anything
needs a **per-vehicle** or **per-route** quantity, because the only way to get one today is an O(n)
walk.

## The shape

**Mirror how load is handled.** Cached load already works this way: routes carry it, mutations
update it, and an oracle recomputes it from scratch for verification. Distance gets the same
treatment, from the same call sites, with the same reporting.

That is the point of doing it this way rather than inventing a mechanism. The mutation sites that
must update distance are exactly the ones that already update load, so the work is finding those
sites and adding a second update — not designing a new maintenance scheme.

| | today | after |
|---|---|---|
| `Route.total_distance()` | O(route length) walk | cached field, O(1) read |
| vehicle total distance | no such thing | sum maintained across the vehicle's routes |
| verification | none needed, nothing cached | oracle twin, same convention as load |

## Verification

Non-negotiable, and cheap because the answer already exists: the maintained value must equal
`total_distance()`'s recompute at every check, and the sum over routes must equal the solution's
travel term. `stress.py` already checks cached load against its oracle; distance goes in beside it.

A mutation that forgets to update distance is exactly the bug class this convention exists to
catch, and there are enough mutation sites that at least one will be missed on the first pass.

## Why it is worth doing beyond its prerequisite role

- **Reporting.** Per-vehicle and per-route distance are the first numbers anyone asks for when
  reading a solution, and today they cost a full walk to produce.
- **Balance-aware operators.** `SplitRandomRoute` currently splits at the longest arc. A
  balanced-length split needs cheap per-route distance to be affordable at proposal time.
- **It is the honest version of what the objective already believes.** The travel term is
  maintained incrementally at the top level; pushing the same discipline down one level makes the
  representation consistent rather than adding a new idea.

## Gate

None on its own — it is small, isolated, and self-verifying. Do it when
[vehicle-time-limits](vehicle-time-limits.md) is wanted, since that plan cannot start without it.

Sequence it **before** [inverted-view-refactor](inverted-view-refactor.md) if both are planned:
adding a cached field to routes is cheap now and would be rework after the position representation
changes.
