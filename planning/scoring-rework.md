# Scoring rework

**Status: designed, not started. Agreed in substance**, Benjamin's design, 2026-08-20 and 08-21.

**Lands AFTER [hierarchical-magnetism](hierarchical-magnetism.md)**, which supplies the sibling-local
machinery this plan reuses and is the only piece that changes live behaviour on its own.

Fold into `design/operator_selection/` once implemented.

**Impetus:** the n=500 ablation. Dropping `ReorderShortSpanExactly` gained 24.59 at -4.8 sigma, and
the defect is worst at plateau where every weight converges toward uniform and draw probability stops
depending on cost. Numbers in `RESULTS.md`, "The scoring cannot price rarity against cost".

---

## 1. The hand-set penalty goes away

`exploit_selection_penalty_factor` becomes **1 for every operator**. The term stays in the code so a
flat penalty on optimizers can be reimposed later as a broad category -- **not per operator**.

**TODO attached:** find a way to reduce repeated work. That is what the factor was really proxying
for. See `planning/repeated-work-detection.md`.

## 2. One new memory-gated statistic per operator

The improvement estimate, EMA'd. `reaction_factor` governs operator weight;
`statistic_reaction_factor` governs this one, default -1 meaning "same as the operator one".

**Acceptance rate is EXCLUDED**, Benjamin 2026-08-22. Nothing reads it, and the temperature-blend
idea that would have used it is dropped for this pass. Building it now is work for a consumer that
does not exist.

**Renamed from `improvement_rate` to `improvement_estimate`.** It is not a measured frequency. It is a
SHRUNK ESTIMATE of one, and calling it a rate invites the objection that its meaning drifts.

### The update rule

```
proposed      ->  est = (1 - alpha) * est + alpha * stat_rate
not proposed  ->  est = max(est, (est / sibling_geom_mean) ** Bayes_magnet * sibling_geom_mean)
both          ->  floored at a small global constant (1e-6 order)
```

**The magnet, not skip-catch-up.** Skip-catch-up pulls an untested operator toward `stat = 0`, which
assumes absence of evidence is evidence of failure. The magnet pulls it toward the population, which
assumes it is typical. The second is the better prior, and it also collapses the SPREAD rather than
the LEVEL -- so when resolvability dies everything clusters quickly and evenly, instead of decaying
to a floor at rates that depend on where each operator started.

**This is empirical-Bayes shrinkage.** Benjamin derived it from resolvability and limited memory,
not from the statistics. Two honest caveats: the theory supplies a shrinkage FACTOR as a function of
variance and sample count, which we do not have -- 0.997 was hand-tuned on one or two instances in
summer 2025. And the `max(...)` makes it one-directional, pulling only up; pure shrinkage is
symmetric. The asymmetry is a deliberate "do not let an untested operator die" rule.

### Segment length must grow with the machinery

**Benjamin, 2026-08-22.** Every statistic here is estimated once per segment, from that segment's
proposals. As machinery and operators accumulate, each operator gets a smaller share of the same
budget, so each update resolves less. Segment length has to grow to compensate.

**When it does, every update parameter should shift from a per-operator-update meaning to a
PER-ITERATION meaning.** Otherwise changing `segment_length` silently changes what
`reaction_factor`, `statistic_reaction_factor` and `Bayes_magnet` mean, and the knobs stop being
independent. `tools/tune.py` already does this for `reaction_factor`, deriving it as
`1 - retention ** segment_length`. The rest should follow the same shape.

### `Bayes_magnet` is a parameter

Exposed for ablation and tuning. Wants to sit close to 1. **Its value sets latch-and-release timing:**
after uniform starvation one improvement lifts an operator above the cluster; how long that lift
survives if the improvement was luck is set by this constant and by how often the operator is drawn.
Too slow wastes budget on a one-off, too fast and it never gets the draws to prove itself.

Replace the constant with a derived factor later if a proper derivation appears.

### Shrinkage is SIBLING-LOCAL. The PENALTY is not.

**Magnetism is local; normalization is global.** These are different jobs and must not be conflated.

- **Magnetism is about statistical relevance.** "Typical" only means something among operators doing
  the same job at different settings. Siblings are the reference class.
- **The penalty must stay globally driven.** Under star selection a family's weight is its best
  member's ADJUSTED weight, and that carries all the way to the root. If `max_improvement_score` were
  per-family, weights would mean different things in different families and full-family selection
  would skew. Too risky. `max_improvement_score` is global.

The mechanics of local magnetism -- sibling reference class, only-child rule, subtree propagation --
are now their own planning item, `planning/hierarchical-magnetism.md`, **which lands FIRST.** It
touches live code and deserves its own ablation arm.

This plan reuses that machinery for the shrunk improvement estimate and replaces the hard-coded
`0.997` with `Bayes_magnet`.

### Why this gives the plateau behaviour

When nothing is productive, every estimate clusters, so
`penalty = (est/cost) / max(est/cost)` collapses to **`min_cost / cost`** -- ranking by cost alone,
which is what a plateau wants. The floor value cancels, appearing in numerator and denominator, so it
is numerical hygiene rather than policy.

**CHANGES LIVE BEHAVIOUR.** Everything else here is new. The weight magnet is running today on every
unproposed operator each segment, so this wants its own ablation arm or a stated expectation before
the run.

## 3. Dynamic penalty replaces the hand-set one

```
improvement_score = improvement_estimate / cost        # floored at 1e-20, math safety only
op.penalty        = improvement_score / max_improvement_score       # in (0, 1]
```

Computed **after** operator weight updates, applied to `adj_weights` **before** family flooring --
the same slot the old factor occupies today.

## 4. The score cancels the penalty

On accept:

```
gain  = improvement ** improvement_exponent / cost ** cost_exponent if improvement > 0 else 0
score = max(explore_reward / cost, gain) / penalty
```

where `cost = max(mean_cost, 1e-9)`.

**`sign` and `abs` both drop out.** A disimproving move used to produce a negative second term, which
the `max` discarded anyway because `explore_reward / cost` is strictly positive. Collapsing that
branch to 0 changes no result and removes two operations from the hot path -- plus the reader no
longer has to check whether a negative score can propagate.

Note also that `record_accept` clamps with `max(0, score)`, which the positive floor already makes
unreachable. Dead once this lands.

**`cost_exponent` is gated to the EXPLOITATION term only.** Exploration is a different mode, so its
reward divides by plain cost, exponent 1, always. The proper exploitation exponent is probably also
1, but that is unevaluated -- which is exactly why it is a parameter and why it applies to only one
of the two terms.

`cost_exponent` is a **new solver parameter, default 1**.

**`/ penalty` divides the WHOLE `max(...)`, confirmed.** Both terms then cancel against
`adj_weight = weight * penalty`. Applying it to the exploitation term alone would deliver the
exploration contribution penalty-SCALED -- suppressed hardest for the operator with the worst
improvement estimate, which is exactly the operator `explore_reward` exists to keep alive.

**Why it works.** `adj_weight = weight * penalty`, `weight = EMA(score)`, and `score` carries
`1/penalty`. While an operator is earning, the two cancel and `adj_weight` is the explicit
cost-benefit score. When it stops earning, its weight drifts toward uniform and `adj_weight` is
driven by `penalty` alone.

**So at plateau, selection ranks purely by improvement-per-second**, with improvement-MAGNITUDE noise
gone. Random operators self-gate on a low improvement estimate; optimized operators self-gate on high cost.
One mechanism, both directions. This is the direct answer to the ablation finding.

## 5. Cost accounting excludes no-ops and invalids

`mean_time = valid_time / num_valid`. Invalid-call time is not tracked anywhere, so this is about
stopping cheap degenerate returns from diluting the denominator.

No-ops and invalids **still count as proposals** for acceptance and improvement rates. They must not
touch cost scoring anywhere.

**RESOLVED: plain `cost`.** `cost_exponent` exists for a separate mode with a separate purpose, and
the rest of the math points at an exponent of 1 anyway.

## 6. `explore_reward` stays

Rewards exploration at high temperature. Niche but real. Its effect appears in acceptance-rate
statistics and in ablation, never in improvement statistics.

---

## OPEN — settle before writing code

1. RESOLVED: **over PROPOSALS.** That is the point -- a random operator is cheap but has a low
   improvement rate.
2. RESOLVED: **raw `cost` only.** `cost_exponent` is a separate rule for a separate mode.
2b. RESOLVED: **`max_improvement_score` stays GLOBAL.** A star's adjusted weight carries to the root,
   so per-family normalization would make weights mean different things across families and skew
   full-family selection. Only magnetism is local.
2c. **Latch-and-release timing needs a look before committing.** Measurable from weight traces
   alone -- log the estimate per operator across a run with reheats and see how long a spike
   survives. No ablation needed.
3. **The cancellation is exact only while `penalty` is constant.** `weight` is an EMA over many
   segments, each score divided by the penalty in force at that time, then multiplied by today's
   penalty. A moving penalty leaves a residue. Probably small and self-correcting -- worth knowing
   rather than discovering in a trace.
4. **`max_improvement_score` is global**, so one operator's spike rescales every other operator's
   penalty at once.
5. **`adj_weights` feeds the family MAX**, so the new penalty propagates up the tree.
6. **`geom_mean_weight` is computed over STORED weights, which are inflated by `1/penalty`.** So an
   operator with a small penalty inflates the mean that pulls unproposed operators up. A place where
   the uncancelled form leaks. Probably minor.
7. **Initial cost, RESOLVED:** `1e-12 if num_valid_proposals == 0 else mean_proposal_cost if
   num_valid == 0 else mean_valid_proposal_cost`, with `mean_valid_proposal_cost >=
   mean_proposal_cost` enforced. Everything samples early; an operator that has never been valid is
   priced at its invalid/no-op cost; expensive invalids are penalized but not catastrophically.
8. **The penalty is blind to exploration**, and that is accepted for now. Acceptance rate is NOT
   tracked at all -- see section 2. The temperature-blend idea, acceptance rate high with a low
   improvement estimate, is DROPPED for this pass rather than built on speculation.
9. **AFTER this redesign: should magnetism be symmetric, on formal shrinkage rules?** A proper
   Bayesian treatment could handle the distribution directly at every level. It may not transfer,
   since exploration and plateau phases plausibly want different shapes and formal shrinkage assumes
   a meaning for the score that ours may not match. Current expectation: keep the resolvability
   argument on the low end, weaker pull on the high end. Recorded in
   `planning/hierarchical-magnetism.md`.

## Queued behind this

- **Full-roster K ablation**, varying only `max_span`, after the rework lands. The existing K arms
  used an exact-only roster and ran under the scoring being replaced.
- Benjamin's WIP: exact reorder may be replaced by MIP above some size, or compete with it as a
  sister family. Both become dynamic generators -- Exact spawns K values, MIP spawns
  (K, time_limit) pairs. Each K may itself become a generating subfamily.
