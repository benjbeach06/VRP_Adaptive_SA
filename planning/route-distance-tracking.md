# Track total distance on routes and vehicles

**Status: not started. Blocked on [raw-delta-accounting](raw-delta-accounting.md). Prerequisite
for [vehicle-time-limits](vehicle-time-limits.md).**

## The problem

`Route.total_distance()` walks the route and sums arcs. Nothing stores it.

The solution-level travel term *is* maintained incrementally — every mutation has a
`travel_delta_if_*` that prices it in O(1) from boundary arcs — but that delta is applied to one
global total. No route knows its own length, and no vehicle knows the sum of its routes'.

That is fine while the objective is the only consumer. It stops being fine the moment anything
needs a **per-vehicle** or **per-route** quantity, because the only way to get one today is an O(n)
walk.

## The shape

**The distance delta already exists at every mutation site; this adds the field that receives it.**
Under [raw-delta-accounting](raw-delta-accounting.md), every mutation reports a raw distance delta,
and the processor threads it through reconstruction regardless of whether anything currently reads
it. Adding per-route and per-vehicle distance is then a matter of giving the processor's accounting
record a place to put that delta — not finding and instrumenting ~44 mutation sites by hand.

The old plan was to mirror load: find every site that updates cached load and add a second update
there for distance. That is exactly the per-mutation duplication `raw-delta-accounting` removes, so
this plan no longer proposes it. Cached load itself is a candidate for the same treatment, but that
is `raw-delta-accounting`'s scope, not this one's.

An oracle twin recomputes from scratch for verification, same convention as load.

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

[raw-delta-accounting](raw-delta-accounting.md) first — this plan's shape depends on the processor
existing. Beyond that, small and self-verifying. Do it when
[vehicle-time-limits](vehicle-time-limits.md) is wanted, since that plan cannot start without it.

Sequence it **before** [inverted-view-refactor](inverted-view-refactor.md) if both are planned:
adding a cached field to routes is cheap now and would be rework after the position representation
changes.

## References

- [vehicle-time-limits.md](vehicle-time-limits.md)
- [inverted-view-refactor.md](inverted-view-refactor.md)
- [raw-delta-accounting.md](raw-delta-accounting.md) -- blocking prerequisite; the processor gives this plan the field to write distance into instead of instrumenting mutation sites by hand

## Links to here

- [budget-gated-selection.md](budget-gated-selection.md) -- budget gating would complement distance-tracking cost reduction
- [README.md](README.md)
- [repeated-work-detection.md](repeated-work-detection.md)
- [vehicle-time-limits.md](vehicle-time-limits.md)
- [raw-delta-accounting.md](raw-delta-accounting.md)
