# Family generation: one operator per parameter value

**Status: not started. Unlocked by family selection, which is now built.**

**GATED ON THE SCORING REWORK.** Generation multiplies the number of operators whose weights must be
priced correctly, so wrong pricing does more damage with generation than without. Same argument this
plan already makes about family selection: generation without it is harmful. See
[operator-selection](operator-selection.md).

## The problem it solves

`ReorderShortSpanExactly` draws its span length uniformly from [3, 8]. Those spans do not cost the
same -- 6 permutations against 40,320 -- and they do not pay off the same either. One operator, one
weight, one `mean_valid_call_time` **averaged over a 6000x cost range.** The scoring cannot tell "span 4 is
excellent value" from "span 8 is waste", so it prices the blend and acts on neither.

**Generate the family instead:** one fixed-span operator per size. Each prices independently, on its
own measured cost and its own measured payoff. The family aggregates them.

## The worked case: K in `ReorderShortSpanExactly`

**Benjamin's, 2026-08-20.** Both the cost and the power of exact reordering are factorial in K, and
the choice of K makes a large empirical difference to performance. That combination is what makes it
the right first target: a parameter whose value matters a lot, over a range the solver cannot afford
to explore blindly.

**Generate one operator per K.** Each carries its own weight and its own measured cost, so the
solver learns which K is worth its time on the instance in front of it rather than being handed one
number chosen offline.

**Start with small K and expand as the run goes.** A generated set should not open with every K
active. Small K is cheap and always affordable; large K is where the factorial cost lives and should
have to earn admission.

Two ways to do that, and the choice is open:

- **Dynamic generation.** Add the next K up once the current largest is paying off. The set grows
  only as far as the instance justifies.
- **A fixed generated set behind strict activation gating.** All K values exist from the start, but
  the expensive ones stay inactive until a gate opens them. That is the activation-gate stub in
  [operator-selection](operator-selection.md), section C, and this is its first real consumer.

The second is easier to reason about, because the family tree is static and only the gate moves.

## The measurement that made this urgent

The ablation above found `ReorderShortSpanExactly` costing 24.59 at -4.8 sigma on the reference
instance, with the exact-only arms worsening monotonically in K. One operator, one weight, one
`mean_valid_call_time` spread across a factorial cost range -- exactly the blend this plan exists to break
apart.

**It does not say the operator should go.** It says a single operator cannot represent a parameter
whose cost and power both scale factorially. Generation is the fix; the ablation is the evidence
that the current shape does not work.

Numbers in [operator-selection](operator-selection.md).

## It generalizes to any numeric parameter

Span length is one instance. `k` in the BestOfk operators, chain length, `NEIGHBOR_ROUTE_DRAWS` --
each is a constant chosen once and searched offline, and each could instead be a generated family
whose members compete.

**That is online parameter learning**, and it attacks the problem
[joint-parameter-search](../experiments/joint-parameter-search.md) says is unaffordable. Offline tuning of these
values needs runs measured in days, per instance shape, and does not transfer. A generated family
learns the value DURING the solve, on the instance actually being solved.

## Why it needed family selection first

**Generation without family selection is harmful.** Splitting one operator into six multiplies that
operator's share of a flat draw by six -- the roster-composition bias, made worse deliberately.

Two properties of the built tree make generation safe:

- **MAX gives exact size-independence.** A family of six span sizes cannot out-earn a family of one
  by having more members, because only the best member counts.
- **Descent is O(depth x branching), not O(roster).** Six new members cost one extra comparison
  inside one family and nothing to any other family. Flat selection would have charged the whole
  roster on every proposal.

Both are in [design/operator_selection/family_selection.md](../../design/operator_selection/family_selection.md).

## DYNAMIC generation: a family that owns its own roster

**Benjamin's, 2026-08-20.** The sections above describe a FIXED generated set -- one operator per
parameter value, decided once. The stronger form is a family that **controls its own operator
lifecycle**: it adds sub-operators, deletes them, and to a limited extent combines them, while the
solve runs.

That changes what a family is. Today a family is a node with fixed children. Here it is a policy that
decides what its children should be.

### Birth: what a new sub-operator is worth before it has done anything

**A newly generated sub-operator starts at the geometric mean of its siblings.** Not at the family
max, which would let it capture the family's share before earning it, and not at zero, which would
stop it ever being drawn enough to prove itself.

**The first sub-operator in a family starts at 1**, like every other operator does today. Each family
seeds a few options at the start rather than beginning with one.

### Death: staleness is a usefulness score

A stale sub-operator is one that is **not doing anything productive** -- generically, the solver
hates it. Sub-operators that do almost nothing for long periods die to make room for new ones.

**FIRST-TRY CANDIDATE: reuse the selection penalty.** The scoring rework already computes
`improvement_score = improvement_rate / cost`, EMA'd and normalized against siblings. That IS a
usefulness score. Staleness becomes **penalty under a threshold for longer than a minimum age** --
two knobs instead of a weighted blend of six, and the death rule then agrees with the selection rule
by construction rather than by hand.

**For an optimized operator, acceptance and improvement are the same metric.** If it only ever
returns something at least as good as the incumbent, every accepted move is an improvement, so the
two rates carry no independent information. That collapses the metric list further for exactly the
operators this plan generates.

**The fuller rule is TBD**, if the first try is not enough. It would combine several metrics into one
usefulness score:

- relative weight against its siblings
- **age in seconds** -- do not discard too fast
- improvement rate
- no-op rate
- acceptance rate
- computational cost

Age is the one that has to be there. Every other metric is noisy early, so a young sub-operator that
looks bad may simply not have been drawn enough.

### Growth: directed, not random

Replacement is **not** a random draw. A new sub-operator is generated to fill an identified gap.

| observation | response |
|---|---|
| MIP gap is very high for some `(k, budget)` | generate one with a **bigger budget**, if the cost gate allows it |
| a sub-operator solves to optimality in a fraction of its budget | add one with **higher k**, randomized within a projected affordable range |

**Growth is limited, proportionally.** A step from k=4 to k=6 is reasonable; 100 to 110 is
reasonable; 100 to 150 is not. The rule wants to be careful about this rather than permissive.

### Worked example: `Reorder_Chain_With_MIP`

Solve the chain ordering as a **mixed-integer program** instead of brute-forcing it. Each
sub-operator is characterised by a pair **(k, time_budget)**, and **both vary per sub-operator**.

- **`k`** is the chain length. Selection uses it to draw a valid chain of exactly that length.
- **`time_budget`** is the time limit handed to the **MIP solver** for that call.
- **Each sub-operator covers a BUCKET of about 20 k-values**, not a single k, drawing a length within
  its range. A MIP sees k=40 and k=41 as near-identical, so separating them wastes competition on a
  distinction the solver cannot measure. Buckets also resolve better under random draws. **Bucket
  width of 20 is a starting figure -- TBD.**
- The cost gate must include **the overhead of building the MIP model**, not only solve time.

**Build the model once per bucket and keep it.** Between calls, reset it and swap the distance-matrix
coefficients rather than reconstructing the structure. Model construction in Python is likely the
binding cost at these sizes, not the solve.

**The cost is not a new risk category.** The existing brute-force reorderer already costs about 1 ms
at k=9. A MIP at a comparable cost covers k=8 to 40 -- the same price for four times the chain
length, and with an explicit time budget bounding it. Starting seeds are chosen ahead of time to be
plausibly useful rather than generated blindly.

**Bad sizes die by starvation.** A bucket that is not worth its cost loses weight, stops being drawn,
goes stale, and is cut. That is how the family learns which sizes are worth having on this instance,
and it is the same mechanism doing the work rather than a separate size-selection rule.

**Warm-start the MIP with the current chain order.** Two consequences, both load-bearing:

- The MIP always holds a feasible incumbent, so a time-limited solve returns something usable rather
  than nothing. The time budget becomes a quality knob rather than a failure mode.
- **It can never return an ordering worse than the current one.** So acceptance equals improvement
  for this operator -- the same property `exact_span_order` gets from seeding its bound with the
  incumbent.

**Why it is worth the dependency: a MIP reorders chains of length 20 to 30 with extreme efficiency**,
far past where brute force with pruning stops being affordable. It can also serve other optimal-move
sets beyond reordering.

**Do not pin one solver -- but do not start generic either.** Begin with one backend and expand
toward genericity only as far as it earns. The operators should be ABSENT when no backend is
installed, never broken.

The shape, if it is ever built out:

| stage | what exists |
|---|---|
| **1** | Two paths: one CHEAP direct backend, plus Pyomo as the catch-all for anything else. |
| **2** | Curated model-building code per supported solver, routing to Pyomo only when the chosen solver has no curated path. |

**The solver is selected by environment, and only the active path is built.** Same import-time branch
pattern as [determinism-import-branch](../core-refactors/determinism-import-branch.md) -- decide once at import, pay
nothing per call.

Model selection and model building would likely earn their own classes and their own folder rather
than living inside the operator.

**Measure the per-call floor before committing to any backend.** Pyomo's cost is in model
construction and the solver-interface round trip, and it does not shrink with problem size. If that
floor is 5 ms, MIP operators compete at 5 ms against a brute-force reorderer at 1 ms and the cost
argument in this section stops holding. A short mutate-and-resolve timing loop settles it. Persistent
solver interfaces avoid most of the round trip; file-based ones do not.

**Honest status on this part: it is a long roadmap and may never be walked.** Stage 1 alone is worth
having. Stage 2 is written down because the shape is clear, not because it is scheduled.

**Where the family sits: `INTRA_ROUTE -> REORDER -> OPTIMIZED`**, beside the brute-force reorderer,
inside the 25% intra-route floor. That placement is deliberate. The two solve the same problem by
different means, so they should compete for the same budget, and under MAX one good bucket lifts the
whole MIP family's standing within that floor.

**TODO: flesh this out.** There is a lot of room to learn which operators are worth having and which
are affordable. This entry records the shape, not the answer.

### Worked example: the existing exact reorderer

`exact_span_order` is n!-with-pruning. Under dynamic generation each sub-operator has a **fixed** k,
and the selection code uses that k to draw a valid chain rather than drawing a length at random.

- **Start with small chains only.** Small k is cheap and always affordable.
- **Admitting a larger k is budget-gated**, using an alpha / (1-alpha) average-cost memory built from
  the cheaper sub-operators already running. The family extrapolates what the next k up will cost
  from what the current ones did cost.

**Both examples get cheaper over time at fixed k.** Pruning tightens as the incumbent improves, so a
k that was unaffordable early can become affordable later. A MIP may behave the same way. **The gate
must therefore be re-evaluated during the run, not decided once at the start.**

### The constraint this whole design is under

**Careful rules are more knobs, and knobs are what generation exists to remove.** An operator set
built on an external solver needs a more robust rule set than a hand-written operator does,
especially when it is generated dynamically -- so the rules will not be simple.

**The final design must still be very static-knob-limited.** The target shape is a small number of
structural parameters -- something like one "acceptable growth" value -- rather than a knob per
sub-operator or per decision. If the rule set grows a knob per behaviour, it has reproduced the
problem it was built to solve.

### Open

- **Bucket width.** 20 is a starting figure with a rationale, not a measured one.
- **Whether "combine" is needed at all** once buckets exist.
- **The usefulness score itself** -- which metrics, weighted how.
- **The growth rule** -- what "proportional and limited" is, exactly.
- **The MIP dependency.** Accepted in principle. Which solver, and whether it can be optional, is
  not decided. The project has none today and `scipy` is not installed.

## What it costs

Nothing is free. The tree removed the allocation penalty; two costs remain.

**Within-family dilution.** Six members share one family's budget, so each is drawn about a sixth as
often as a single operator would be. The family keeps its share; each member gets less of it.

**Learning cost.** Every member needs proposals before its weight means anything. Six members need
roughly six times the samples before the family knows which is best, and until then the family spends
real budget on members that will turn out useless. On a short run that may never converge -- the same
power problem as [joint-parameter-search](../experiments/joint-parameter-search.md), moved inside the solve.

## The open question

Members differing by orders of magnitude in cost still have to be comparable to each other WITHIN a
family, and that comparison runs through `mean_cost` in the score. Whether the existing per-operator
cost division is enough, or whether generated members need their own normalization, is unmeasured.

That is the same question [operator-selection](operator-selection.md) asks about the roster as a
whole, appearing again one level down.

## Gate

Family selection is built, so the blocker is gone. Do not start until [ablations](../experiments/ablations.md) has
priced `EXACT_REORDER_MAX_SPAN` -- generating six span sizes before knowing whether span size matters
is expensive guessing.

## Related

[operator-selection](operator-selection.md) is the selection hub.

## References

- [planning/experiments/joint-parameter-search.md](../experiments/joint-parameter-search.md)
- [planning/experiments/ablations.md](../experiments/ablations.md)
- [design/operator_selection/family_selection.md](../../design/operator_selection/family_selection.md)
- [planning/core-refactors/determinism-import-branch.md](../core-refactors/determinism-import-branch.md)
- [operator-selection.md](operator-selection.md)

## Links to here

- [budget-gated-selection.md](budget-gated-selection.md) -- proposes budget gating as an alternative approach to dynamic family creation
- [design/operator_selection/family_selection.md](../../design/operator_selection/family_selection.md) -- tree structure for dynamic family creation
- [design/span_reorder/reorder_operators.md](../../design/span_reorder/reorder_operators.md)
- [planning/README.md](../README.md)
- [RESULTS.md](../../RESULTS.md) -- cites the K-sweep finding that motivates making K a learnable, dynamic quantity
