# Track total distance on routes and vehicles

**Status: not started, now unblocked. [raw-delta-accounting](../implemented/raw-delta-accounting.md)
landed (steps 0-3, 5), so the processor this plan's shape depends on exists. Prerequisite for
[vehicle-time-limits](../problem-model/vehicle-time-limits.md). Carries deferred step 4 of
raw-delta-accounting, end-depot usage tracking.**

## The problem

`Route.total_distance()` walks the route and sums arcs. Nothing stores it.

The solution-level travel term *is* maintained incrementally — every mutation has a
`travel_delta_if_*` that prices it in O(1) from boundary arcs — but that delta is applied to one
global total. No route knows its own length, and no vehicle knows the sum of its routes'.

That is fine while the objective is the only consumer. It stops being fine the moment anything
needs a **per-vehicle** or **per-route** quantity, because the only way to get one today is an O(n)
walk.

## The shape

**The accounting record cannot carry this, and the reason is arithmetic rather than layering.** An
earlier version of this plan said the processor would thread a per-route distance delta through
reconstruction, so this plan would only add the field that receives it. That was wrong, and the
next section says why.

The distance accounting happens at MUTATION time. That is the one place in the solver where a
derived quantity is not owned by the processor, and it is a deliberate exception rather than an
oversight.

The older plan before that was to mirror load: find every site that updates cached load and add a
second update beside it. That per-mutation duplication is what `raw-delta-accounting` exists to
remove, and it is not proposed here either.

An oracle twin recomputes from scratch for verification, same convention as load.

| | today | after |
|---|---|---|
| `Route.total_distance()` | O(route length) walk | cached field, O(1) read |
| vehicle total distance | no such thing | sum maintained across the vehicle's routes |
| verification | none needed, nothing cached | oracle twin, same convention as load |

## Why link counting cannot attribute distance to a route

Measured 2026-08-29, and the reason this plan owns mutation-time accounting instead of inheriting
the processor's.

### The link-delta form is correct only as a total

`travel_delta_if_customer_chain_removed` is three distance calls:

    + d(before, after) - d(before, first) - d(last, after)

The chain's INTERIOR arcs never appear. The matching insertion is the mirror:

    + d(prev_insert, first) + d(last, insert) - d(prev_insert, insert)

The interior cancels between the two halves, because a moved chain carries its own arcs with it.
That is what makes chain moves and swaps O(1) in the chain length, and they are among the cheapest
operators in the roster precisely because of it.

The cost is that NEITHER HALF IS A ROUTE'S REAL DISTANCE CHANGE. The source route genuinely loses
the interior arcs and the destination genuinely gains them. The two are only jointly correct.
Attributing per route means computing the interior, which is O(k) -- turning the cheapest pricing
path in the solver into a linear one.

### So the sink cannot own it

The raw record is built during PRICING, and at pricing time only the O(1) link deltas exist. There
is no per-route attribution inside it for `FullSolution.apply_accounting` to write. Giving it one
would mean paying the O(k) cost exactly where it must not be paid.

### The mutators can, because they are already linear

`remove_customer_chain` slices the path, sums demand over the removed visits, then splices --
three linear passes before it touches anything else. Accumulating distance there is asymptotically
free, where doing it during pricing is not.

### The shape

  * the raw record keeps travel as ONE BULK NUMBER, priced from link deltas, unchanged;
  * per-route distance is a CUMSUM ALONG THE PATH, maintained at mutation time. A route stores no
    total -- it reads the last element of its cumsum;
  * per-vehicle distance is maintained too, not derived on demand, so vehicle-level objective terms
    (travel time, and [vehicle-time-limits](../problem-model/vehicle-time-limits.md)) have their
    aggregates ready;
  * this is an ACCEPTED DUAL TRUTH: the priced total and the maintained cumsum are two derivations
    of one quantity. Every dual truth in this codebase so far drifted silently because nothing
    compared the two, so the per-route oracle ships in the same change, not after it.

### The unresolved part: rework during multi-step pricing

A cumsum gives any sub-chain in O(1) as `prefix[j] - prefix[i]`, which is what makes the interior
problem go away. The cost moves to the write side: a change at position p shifts every prefix after
p, so a naive update is O(n) in route length.

Tolerable for a single mutation. NOT tolerable for the sequential operators, which price as remove,
price, insert, price -- each step rewriting the same route tail again.

Complexity and efficiency are at war here, and the tension is open. The sketch is to cache a
deferred offset during multi-step pricing -- "the tail of route r after position p carries offset
o" -- so the tail is rewritten once at the end rather than once per step. That is a second hard
idea with its own invariants and its own failure modes. Designing it is part of THIS plan, and its
size is the reason this plan is separate from
[raw-delta-accounting](../implemented/raw-delta-accounting.md).

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

[raw-delta-accounting](../implemented/raw-delta-accounting.md) has landed, so the processor this
plan's shape depends on exists. Beyond that, small and self-verifying. Do it when
[vehicle-time-limits](../problem-model/vehicle-time-limits.md) is wanted, since that plan cannot start without it.

Sequence it **before** [inverted-view-refactor](inverted-view-refactor.md) if both are planned:
adding a cached field to routes is cheap now and would be rework after the position representation
changes.

## References

- [planning/problem-model/vehicle-time-limits.md](../problem-model/vehicle-time-limits.md)
- [inverted-view-refactor.md](inverted-view-refactor.md)
- [planning/implemented/raw-delta-accounting.md](../implemented/raw-delta-accounting.md) -- blocking prerequisite; the processor gives this plan the field to write distance into instead of instrumenting mutation sites by hand

## Links to here

- [planning/operator-selection/budget-gated-selection.md](../operator-selection/budget-gated-selection.md) -- budget gating would complement distance-tracking cost reduction
- [planning/README.md](../README.md)
- [planning/operator-selection/repeated-work-detection.md](../operator-selection/repeated-work-detection.md)
- [planning/problem-model/vehicle-time-limits.md](../problem-model/vehicle-time-limits.md)
- [planning/implemented/raw-delta-accounting.md](../implemented/raw-delta-accounting.md) -- the landed prerequisite; the processor exists, so this plan only adds the field distance is written into
- [design/raw_delta_accounting/README.md](../../design/raw_delta_accounting/README.md) -- the shipped pipeline this plan builds on; its processor supplies the raw distance delta at every site
- [retros/2026-08-29_raw_delta_accounting_implementation.md](../../retros/2026-08-29_raw_delta_accounting_implementation.md) -- the retro for the prerequisite that landed
