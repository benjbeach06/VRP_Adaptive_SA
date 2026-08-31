# Tracking for cached accounting

No mutation maintains a derived cache. The processor resolves each change and the sink writes it.
Two things keep the caches correct around that: a pair of bits that track whether a move and its accounting have been applied,
and a one-time build after a solution is constructed.

## The two application-tracking bits

Structure and accounting are applied as separate events. `Move` carries `already_applied` and
`accounting_applied`.

A predictive operator sets both in one step. It priced the move without touching the solution, so
apply performs the mutation and writes the accounting together.

An operator that prices by mutating leaves its move applied but unaccounted when `evaluate`
returns. `Operator` writes the accounting on the next `apply`. Revert unwinds the accounting first,
then the mutation.

**While a move is applied but not accounted, accounting oracles cannot run.** The derived caches
are legitimately behind the structure in that window.

## Initialization

A solution assembled route by route carries no accounting, because nothing maintained it during the
build. `FullSolution.initialize_accounting` computes every cache directly from the finished
structure:

- each route's load, from its customers' demands,
- the routes starting at each depot, from the structure,
- per vehicle: the customer count from the per-route path lengths, and the counts of routes with
  customers and of overloaded routes by counting the vehicle's routes.

Load comes first, because the overloaded-route count reads it. Every write is an absolute value, so
the method is idempotent.

The build owns the call. It runs at the end of each initial-solution builder, before the first
objective evaluation, so no caller has to remember it. A route writes nothing when it is
constructed: it has no vehicle and no solution yet.

## References

*(none yet)*

## Links to here

- [README.md](README.md) -- the folder hub; this doc is tracking and the one-time build, last in reading order
- [design/README.md](../README.md) -- parent index to the design folder
