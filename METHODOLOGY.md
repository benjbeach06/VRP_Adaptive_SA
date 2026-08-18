# Methodology

## Provenance

Part of this repository was written with AI assistance (Claude), and the split is specific enough to
measure. The `Pre_AI` branch marks the last commit before any was used.

| | `Pre_AI`, 2026-08-07 | today |
|---|---|---|
| solver proper — model, operators, lifecycle, annealing | **4,902 lines** | 7,513 |
| `tools/` — profiling, stress, ablation, tuning | 0 | 1,770 |
| tests | 47 | 1,116 |

The solver is mine. Its architecture — the delta arithmetic, the operator lifecycle, the
oracle-twin convention, the annealing schedule — was designed and built before an assistant touched
the project, and about two thirds of the current solver code is still that work.

Assistance went almost entirely into **instruments**: the profiling, ablation, stress and tuning
harnesses that produced every number below, plus a test suite that grew from 47 lines to roughly
2,900.

That is why provenance sits at the top of the methodology document instead of in a footnote. The two
are the same subject. Generating code and experiments quickly moves the binding constraint from
writing to verification — plausible work arrives faster than it can be reviewed — and every rule in
the next section exists because something plausible turned out to be wrong.

The results that most needed a human were the ones where the machine was confident:

- The improvement-counter defect that voided the tuning run was found by reading solver output that
  looked normal, not by any test.
- The tuned `segment_length` that measured 5.8σ was rejected because it lost on the instance I
  actually run — noticed while solving, not while analyzing.
- Several intermediate results in this document were asserted before being measured, and were
  retracted. The rule "report from bucket means, never the argmax" is one of those retractions.

What I would claim from this project is not the line count on either side of that table. It is that
the numbers in this document are ones I checked myself, and that the ones which did not survive
checking are written down here next to the ones that did.

— Benjamin Beach

---

The interesting part of this project is not the metaheuristic. It is the measurement discipline
around it. Most of what follows exists because a plausible-sounding improvement turned out, when
measured, to be wrong — including one that had already been accepted.

---

## How results get accepted here

Four rules, each learned by getting it wrong first.

**A clean run means nothing until the detector is shown to fire.** `tools/stress.py --inject-delta`
deliberately corrupts a move's price. If that does *not* produce findings, the harness is broken and
its zero-findings runs were worthless. An hour of correctness testing was once run against detectors
that had never been verified.

**Every incrementally-maintained quantity has a recompute-from-scratch twin.** Cached loads, depot
usage indices and objective terms are each checked against an oracle that recomputes them naively.
Most real bugs here surfaced as a disagreement between the fast path and the slow one.

**Report from bucket means, never the argmax.** Selecting the best of N noisy trials biases the
estimate upward. An earlier tuning report recommended a value sitting in the *worst* quintile of its
own table. The current one reports quartile means and a top-decile median, and states the noise
floor before the result.

**Compare within one run wherever possible.** Wall-clock termination means a fixed seed does not fix
the trajectory. Two operators competing inside the same solve share every condition. Two separate
solves do not, and that difference swamped several early comparisons.

**All randomness goes through one seeded generator, and the search can be frozen.** Scattered
`random` calls make a run unreproducible in ways that are invisible until a comparison disagrees
with itself. One generator makes a run replayable; `set_deterministic_weighting` additionally makes
operator weighting a pure function of recorded improvements, so weighting can be held fixed while
something else is varied.

This is the precondition for the other four rules rather than a fifth alongside them. An oracle that
disagrees intermittently cannot be debugged, and a within-run comparison means nothing if the run
cannot be repeated. It exists because a throwaway test suite was kept instead of discarded —
preserving it forced reproducibility, and determinism fell out of that. Neither was the goal.

---

## The finding that mattered most

`RandomCustomerChainReversal` shows **1.09% acceptance** and consumes **0.95 s of a 60 s run**. By
every statistic the solver reported about itself, it was negligible.

Ablation says removing it costs **1.70% of the objective at σ = 18.7** — the largest effect in the
study, larger than every other operator combined.

| finding | size | delta | σ |
|---|---|---|---|
| **drop `RandomCustomerChainReversal`** | 5000 | +157.32 (1.70%) | +18.7 |
| drop `RandomCustomerChainReversal` | 500 | +45.20 (2.16%) | +3.6 |
| drop `ReverseClosestPairTogether` | 5000 | +64.60 (0.70%) | +6.9 |
| `NEIGHBOR_ROUTE_DRAWS` 8 → 16 | 5000 | −51.24 (0.55%) | −3.7 |

*One-factor-at-a-time, paired on seed, breadth-first over seeds. 1,641 runs across 21 seed-rounds.
Bar for significance is |σ| ≥ 3, set by the number of comparisons.*

The operator is cheap and extremely high-volume, so it contributes through throughput rather than
hit rate. The metric the roster had been ranked by could not see it.

**Operator value here is judged by ablation, and never by acceptance rate.**

---

## The result that was accepted and then withdrawn

This is the most useful thing in this document, so it gets the space.

An Optuna search over the operator-selection parameters found `segment_length = 10` against a
shipped default of 100. It measured 1.54% ± 0.26%, or 5.8σ. A paired re-measurement on unseen seeds
reproduced it — 5 configurations out of 5, at 4–7σ. A third experiment isolated the effect to that
one parameter; the other two contributed under 1σ.

Three independent experiments agreed. The result was wrong anyway, for two separate reasons, found
in this order.

### First: it was real, but only where it was measured

The whole search ran at 500 customers and capacity 400 — about seven long routes. The instance
actually being solved is 200 customers at capacity 25, about forty-seven short ones. On that shape
the tuned value **lost roughly 2%**.

Sigma measures whether an effect is real. It says nothing about where the effect applies. Every
trial in the search shared one instance shape, so no amount of significance inside it could have
detected that.

### Second: the instrument was broken, by one of the parameters being searched

`OperatorStats.record_accept` decided whether a move was an improvement by testing `score > 0`. That
was correct as long as `score` carried the sign of the move's improvement.

Then an `explore_reward` floor was added, so that operators paying off through exploration could
earn weight:

```python
score = max(explore_reward, sign * abs(improvement) ** 1.5) / mean_cost
```

The floor is positive. It removed the sign. From that commit onward `score > 0` was **always true**,
and every accepted move counted as an improvement.

`explore_reward` was one of the three parameters the search was tuning. The search was therefore
moving the knob that controlled how badly its own feedback signal was corrupted.

The whole pipeline is void: the search, the validation on unseen seeds, and the isolation run. All
three ran after the floor landed. Reproducibility across three experiments did not help, because
they shared the defect rather than testing it.

### What this cost, and what it did not

`git log` separates the two eras cleanly. The ablation above is `58ae053`; the floor is `b5167e0`;
the tuning is `d237419`. The ablation ran while the counter was still correct and stands. The tuning
came after and does not.

Best-known objectives are also unaffected. A solution that was found is real no matter what the
solver believed while finding it — pricing, weighting and schedule bugs change which solutions get
found, never whether a found one is valid. Every entry in `solutions/` is re-verified against a
freshly built instance from raw geometry, independent of the solver code.

The lesson is not "test more". The suite was clean throughout, because nothing in it asserted
anything about the improvement counter. The counter was a reporting field that quietly became a
control input, and no oracle covered it.

### The rerun found nothing, which is the actual answer

With the counter fixed, the search ran again — 149 trials over 10 hours, this time on the reference
instance (200 customers, capacity 25) rather than the sanity-check shape whose results had failed to
transfer. `tools/preflight.py` gated the launch by confirming the counter was neither dead nor
saturated and that reheating fired.

| | |
|---|---|
| mean trial score | **1.0012** (1.0 = defaults) |
| median | 0.9997 |
| trials beating defaults | 76 of 149 — **51%** |
| best | 0.9889, i.e. 1.11% under defaults |
| best, in trial standard deviations | **1.8σ** |
| expected minimum of 149 pure-noise draws | **≈ 0.9833** |

**The best trial is less extreme than noise alone would produce.** Drawing 149 samples from a
distribution centered on the defaults should yield a minimum near 0.9833; the observed best was
0.9889. The apparent 1.11% gain is selection, not signal — precisely the failure the "bucket means,
never the argmax" rule exists to prevent, caught this time before anything was adopted.

A 51% win rate says the same thing more simply. Optuna concentrates sampling where it has already
seen good values, so a real gradient should push that number well above half.

This replicates an earlier result: a 704-trial search over the annealing schedule was also flat, and
hand defaults also won. **Two independent searches over different parameter sets have now failed to
beat hand-chosen values.** The honest conclusion is not that tuning was done badly — it is that this
solver is insensitive to these parameters at this instance shape, and the remaining variance is the
wall-clock noise floor rather than anything a search can reach.

The one unresolved trace: `segment_length` in the 15 best trials ran 18–79, all below the default of
100. Suggestive, but confounded — the sampler concentrates, so a cluster among the winners is partly
the sampler agreeing with itself. Untested, and recorded as untested.

---

## Other results

**Construction: 8.094 s → 0.209 s at 5,000 customers (39×).** Nearest-neighbor tables replaced
repeated linear scans. Verified by producing a **bit-identical** solution — same objective and same
route-order hash — which required the table's tie-breaking to match `argmin`'s exactly.

**Geometric guidance raises acceptance sharply.** The same move type, blind versus guided:

| move type | blind | guided |
|---|---|---|
| relocate | 0.00%, **0** accepts | 0.30%, **654** accepts |
| cross-exchange | 0.01%, **1** accept | 0.46%, **1703** accepts |

**But the objective effect is not established.** +15.56 ± 7.42, winning 4 of 5 — around 2σ, under
the bar. Acceptance rate is exactly the metric the section above showed cannot rank operators, so it
is reported here as a mechanism check and not as a result. The larger refactor it would justify
stays gated until ablation says otherwise.

---

## Known limitations

Stated because a portfolio project that lists only its strengths is not evidence of judgment.

**No external benchmark.** Every number here is the solver measured against itself. Whether it is 2%
or 20% off a commercial solver is unknown, and it is the one thing a reader should most want to
know. `Hexaly_VRP.py` builds the same instance for Hexaly and predates the rest of this work; the
comparison is blocked on a license renewal, not on the code. It is the next planned step and the
only measurement that would settle the question.

**Operator selection is untuned, and the search says it does not need to be.** The void search was
rerun against the fixed counter — 149 trials, 10 hours, on the reference instance rather than the
sanity-check one. It found nothing (see below). The shipped defaults are the hand-chosen originals.

**One instance family.** Almost every measurement comes from one generated family at two capacities.
The withdrawn result above is what that costs: a finding can be real, reproduced, and still local to
its shape.

**Wall-clock termination makes runs non-reproducible.** A fixed seed does not fix the iteration
count. That sets a noise floor near 0.5% on any single measurement and puts sub-0.5% effects out of
reach. Iteration-count termination would fix it.

**Operator scoring is unfinished.** The `explore_reward` floor exists but its value is unproven —
the search that would have set it is the void one. See `planning/operator-scoring.md`.
