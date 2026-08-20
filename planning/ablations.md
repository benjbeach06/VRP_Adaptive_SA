# Outstanding ablations

Measurements that would settle a question already asked somewhere else. Kept together because they
share a cost -- each one needs paired runs across seeds, and batching them is cheaper than running
them one at a time.

**TODO: gather the rest.** Ablations are currently recorded wherever the question was raised, which
means nobody can see the total bill. Sweep `planning/` and `design/` and bring them here, leaving a
link behind at each origin. Known scattered ones include `EXACT_REORDER_MAX_SPAN`, family-level
ablation, and DEPOT_END against CHAIN.

## Does the `explore_reward` floor buy anything?

`explore_reward` floors an accepted move's score at a small positive value, so an operator that pays
off through exploration can still earn weight. It is implemented, and the mechanism is sound.

**What is unproven is whether the escapes it buys matter.** Low `ms/accept` is not proof of worth --
cheap uphill moves are easy to generate and most are noise. One run recorded 267 escapes attributable
to the floor. Whether those 267 changed the final objective is an ablation question, and the scoring
statistics cannot express it.

Bounds are known: `1e-2` costs 2.77%, while `1e-5` and `1e-8` are indistinguishable from no floor at
all. So the ablation is not "what value" but "does any value beat none."

**Do the statistics first.** `TODO(rescore)` on `update_stats_for_accept` records that SCORE and COST
answer different questions with different denominators, and the statistics cannot express the split
since the solver moved to "apply only when accepting." Tuning the formula against numbers that
measure the wrong thing is what invalidated the operator-selection tuning run once already.

**Build an oracle for the improvement counter first.** That counter is a control input -- it gates
plateau reheating -- and no test asserts anything about it, which is exactly why the suite stayed
green when a positive score floor silently broke it. `tools/preflight.py` checks it before a long
run; that is a gate, not an oracle.

The formula this ablates is quoted in [operator-selection](operator-selection.md).

## Does family-level selection improve the objective?

The case for the family tree is structural -- roster composition should not be allocation policy --
and it was built on that argument, not on a measurement. Whether it improves the final objective is
untested.

Paired on seed against flat selection, holding the roster fixed. **Holding the roster fixed is the
whole difficulty:** the first hierarchical run also gained a new operator, so it measured two changes
at once and settles nothing.

Design in [design/operator_selection/family_selection.md](../design/operator_selection/family_selection.md).

## Does a weight spike lift a whole family harmfully?

MAX aggregation means one member's weight becomes its family's weight, so a spiking operator lifts
every sibling's share. That is intended -- the family routes its budget to the star -- but the
geometric mean it replaced damped this, and nothing damps it now.

Measurable against real weight traces: whether a transient spike does harm before it decays.

## Should DEPOT_END fold into CHAIN?

`SwapRouteHeadsAtSharedDepot` and `SwapRouteTailsAtSharedDepot` sit under
`INTER_ROUTE -> SWAP -> DEPOT_END`, beside `CHAIN`. They are chain swaps with a fixed anchor, and they
differ from each other only by `_at_end`, so the node may be a generated pair rather than a subfamily.

If DEPOT_END and CHAIN track each other under ablation, the level is not earning its place.

## What is `EXACT_REORDER_MAX_SPAN` worth?

Set to 8 by hand. A short sweep found 6 worse and 9 about best on the large instance, from few runs.
Gated twice -- on operator pricing changing, and on family-level selection, since K is a within-family
parameter whose value depends on how often the family is drawn at all.

Both instance shapes belong in it: K=8 rebuilds a whole route at capacity 25 and about an eighth of
one at capacity 400.

Design in [design/span_reorder/reorder_operators.md](../design/span_reorder/reorder_operators.md).
