# Estimate priority, effort and benefit on every planning file

**Status: not started, DELIBERATELY.** The rule is agreed. The metrics are not designed yet.

## The rule

Every file in `planning/` should carry a rough estimate of:

- **Priority** -- how much it matters relative to the others
- **Effort** -- what it costs to do
- **Expected benefit** -- what it buys, and how confident that is

Today the index carries a one-line reason and a status. Neither orders the list. With more than a
dozen plans, "which of these should I do next" is not answerable from the folder.

## Why it is deferred rather than done

**Designing the metrics well takes time, and the choices are high-impact.** A scale that is easy to
fill in will get filled in badly, and a plan ordering built on bad numbers is worse than no ordering
-- it looks authoritative.

Questions to settle first, none of them obvious:

- Is priority absolute, or only a rank against the other open plans?
- Is effort measured in hours, or in a coarse scale that will not pretend to precision?
- How is benefit stated when it is UNMEASURED? Most of these plans are gated precisely because
  their benefit is unproven, so a benefit number risks inventing evidence.
- How does a gate interact with priority? `ruin-and-recreate` may be the highest-value item and
  still not be next.
- Do the estimates get revisited, and when? A stale estimate is the failure mode.

## Gate

Do this when there is time to design the scale properly. It is ironic that a rule about estimating
effort is itself deferred for lack of it, and that is the honest reason.

Apply it to every existing plan in one pass once the scale exists, so the numbers are comparable.

## References

*(none yet)*

## Links to here

- [README.md](README.md)
