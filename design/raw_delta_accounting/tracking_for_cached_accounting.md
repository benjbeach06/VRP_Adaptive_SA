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

- each route's load, from its customers' demands, and its distance, by walking its visit chain,
- the routes starting at each depot, from the structure,
- per vehicle: the distance as the sum over its routes, the customer count from the per-route path
  lengths, and the counts of routes with customers and of overloaded routes by counting the
  vehicle's routes.

**Ordering is required, not stylistic.** Routes come before vehicles, because the per-vehicle
distance sums the per-route figure and the overloaded-route count reads the per-route load. Every
write is an absolute value recomputed from the structure, so the method is idempotent.

The build owns the call. It runs at the end of each initial-solution builder, before the first
objective evaluation, so no caller has to remember it.

**One cache is seeded earlier, and only one.** A route sets its own distance in its constructor,
after linking its visits, because that is the honest starting value for a cache nothing else
recomputes. It costs one walk for a route built with a path and nothing for an empty one, which is
the hot construction. No other cache is written there: a fresh route has no vehicle and no
solution, so there is nothing else to be right about.

## References

*(none yet)*

## Links to here

- [README.md](README.md) -- the folder hub; this doc is tracking and the one-time build, last in reading order
- [design/README.md](../README.md) -- parent index to the design folder
