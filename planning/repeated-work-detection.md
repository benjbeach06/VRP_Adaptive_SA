# Detecting repeated work with route version stamps

**Status: designed, not started. Benjamin's, 2026-08-20.** Gated -- see the bottom.

## The problem

A deterministic operator computes a pure function of its operands. Proposing it twice on an
unchanged route returns the same answer, which was already rejected. The second call is guaranteed
waste, and the deterministic operators are the expensive ones.

Selection cannot see this. Weighting measures cost per accepted move, so an operator that keeps
re-deriving rejected moves simply looks bad, slowly, after paying for every repeat.

**This is the mechanism intended to replace the hand-set penalty factor** -- mechanism 4 in
[operator-selection](operator-selection.md). That factor discounts how OFTEN a deterministic
operator is drawn. This removes the wasted call instead.

## Route version stamps

Each route knows when its last **order** change and its last **assignment** change happened.

- **Load change is the proxy for an assignment change.**
- **An assignment change also counts as an order change.** Membership changing implies the ordering
  did too.
- **Operators trigger the update on the route directly**, so only an ACCEPTED apply moves a stamp. A
  proposal that is priced and rejected leaves the route exactly as it was, and must leave the stamp
  alone too.

That last point is what makes the stamps usable as a repeat test rather than a change log.

## Full-route optimizers

Keep, per operator, the stamp last accepted for each route.

Draw a bounded number of candidate routes. **A route is a repeat when the operator's stored stamp
for it is not older than the route's current stamp** -- nothing has changed since the operator last
worked on it. If every route drawn is a repeat, report NO-OP.

```
repeat  <=>  operator.last_operated[route] >= route.stamp
```

Two defaults make that test correct with no special cases:

| value | default | meaning |
|---|---|---|
| a route's own stamp | **0** | never changed |
| an operator's last-operated stamp per route, in a `defaultdict` | **-1** | never operated on this route |

An unseen route gives `-1 >= 0`, which is false, so it stays eligible. After the operator works on
it the stored value equals the route's stamp, so the next draw is a repeat until something actually
changes the route.

Reporting NO-OP rather than proposing is what keeps this honest with the rest of the solver: the
gatekeeping convention is that a degenerate proposal reports INVALID or NOOP and never a zero-delta
VALID.

## Operators that work on a segment

These need more than a per-route stamp, because a route can be re-drawn legitimately with a
different span. Two options, and the choice is open.

**Range stamping.** Track a bounded number of segment ranges with the stamp they were accepted at. A
selection is a NO-OP if its range is contained in a stored range AND the route's last-ordered stamp
is unchanged since that range was stored. Cheaper to stamp; catches less.

**Set stamping.** Track the membership set operated on, including its boundaries. A selection is a
NO-OP if its chain set is a subset of any stored set for that route. Fewer entries needed and it
catches more cases, at the cost of holding sets rather than pairs of integers.

**A subsegment of a span already accepted is a repeat under either rule.**

Note for set stamping: the chain ORDER may have changed while the set stayed the same. Re-ordering
the same set of customers the same way more than once is still repeated work, so the set test is the
right one even though it ignores order.

## Bounded memory

Either variant allocates a fixed number of stored entries per operator and evicts the
least-recently-used one when full, like a memoization cache. An operator cannot accumulate history
without bound.

## Gate

**Do not implement any of this until partial-span operators are measured to have high NO-OP rates.**
Set re-selection is expected to be rare on large instances, in which case the whole mechanism buys
very little and costs per-route state plus a cache per operator.

The measurement comes first. `tests/_harness.py` already detects mis-reported no-ops; what is needed
here is the RATE of genuine repeats, which is a different number.

- [operator-selection](operator-selection.md) -- mechanism 4 is what this replaces.
- [route-distance-tracking](route-distance-tracking.md) -- another per-route quantity maintained
  incrementally. Same shape of problem, and the same need for an oracle twin.
- [design/operator_selection/family_selection.md](../design/operator_selection/family_selection.md)
  -- family weights depend on no-ops being reported correctly, so anything that changes what counts
  as a no-op touches allocation.

## References

- [route-distance-tracking.md](route-distance-tracking.md)
- [operator-selection.md](operator-selection.md)
- [design/operator_selection/family_selection.md](../design/operator_selection/family_selection.md)

## Links to here

- [README.md](README.md)
- [operator-selection.md](operator-selection.md)
