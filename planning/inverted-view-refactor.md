# Inverted view: centralized customer location

**Status:** deferred, gated. Start after the project is published.

## Problem

There is no way to ask "which route is customer j in, and where". Operators that want a
geometrically sensible destination can only get one by scanning a candidate route.

Two things block a direct answer today:

1. Nothing below `FullSolution` holds a reference to it, so a `cID -> visit` map cannot be
   maintained from inside `CustomerVisit` without threading a solution reference down.
2. `CustomerVisit` objects are recycled as positional **slots** for intra-route mutations —
   `permute`, `reverse_customer_chain`, same-route `reassign_customer_chain` and
   `swap_customer_chains_with` all rewrite `source_customer` in place through `replace_customer*`.
   A visit's identity tracks a position, not a customer.

## Design

`FullSolution` owns one central array: `location_of[cID] -> (route, index)`.

- No visit doubly-linked list. Visits do not store an index either.
- Navigation reads `(route, index)`, takes `route.path_ext`, and moves +/-1 on the index.
- Each route's path is a **subarray view of a larger array**, with the depot sentinels as real
  slots: start depot at index -1, end depot at `len(path)`.

That last part is what makes it clean rather than merely different. With sentinels as real array
elements, `prev` and `next` need no bounds branch at all — the edge cases stop being edge cases.

This is the right end state. It gives O(1) "where is customer j", drops DLL maintenance entirely,
and removes the redundancy between list position and visit pointers, which today are two
representations of the same fact that must be kept in agreement.

## Why it is deferred

**It lands on the hottest code in the solver.** `prev_visit` / `next_visit` feed
`distance_surrounding` -> `distance_in` / `distance_out`, inside `travel_delta_if_customer_replaced`.
Profiling puts that chain at roughly 20 calls per `CustomerBestOfkSwapInRandomRoute` proposal, and
that operator alone was 57-67% of total solver wall time before the roster changed. Bytecode
executing in the operator's own frames — `[self]` in a pyinstrument tree — is already 44% of it.
Turning an attribute read into anything more expensive there is measurable.

**The payoff is not yet proven.** Geometric guidance had never been tried when this was designed.
It now has: see the acceptance figures in `../README.md`. That evidence is what the gate below is
for.

## Gate

Do not start until all three hold:

1. Neighbor-guided operators show a clear acceptance advantage over their blind twins. (Met — the
   guided relocate and cross-exchange both beat their random-destination counterparts by more than
   an order of magnitude.)
2. A before/after benchmark on `CustomerBestOfkSwapInRandomRoute` propose time is set up FIRST, so
   the regression is measured rather than discovered. `tools/profile_one_operator.py` already does
   this; note it inflates absolute times ~2.65x, so compare proportions or run it uninstrumented.
3. Full `tests/` and `tools/stress.py` pass, including `--inject-delta`, before and after.

## Smaller alternative, if the gate fails

Keep the DLL and add `visit.index`, maintained on insert / remove / permute. Redundant state, but
it gives O(1) position without touching `prev_visit` / `next_visit`, so the hot path is untouched.
The oracle harness can assert that the index and the DLL agree, which is the usual pattern here.
