# Results

Every measurement in this project, including the ones that did not survive checking. The rules used
to accept or reject them are in [METHODOLOGY.md](METHODOLOGY.md).

Unless stated otherwise, comparisons are paired on seed and the bar for significance is
**|σ| ≥ 3**, set by the number of comparisons.

**Three instance families appear below, and results never cross between them.**

| family | shape | used for |
|---|---|---|
| **reference** | 3 depots, 500 customers, capacity 400, 100×100 grid, seed 42 | every ablation and parameter search since 2026-08-20 |
| **small** | 3 depots, 200 customers, capacity 25, same grid and seed | the older best-known records; ~47 short routes against the reference's ~7 long ones |
| **CVRPLIB X** | published single-depot CVRP instances, n = 101 to 1001 | the external benchmark |

The reference and small families are the *same generator at two capacities*, and a result on one
does not transfer to the other. That is not a caution — it is a measured finding, and it cost a
5.8σ result. See [Parameter tuning](#parameter-tuning-a-withdrawal-and-a-null).

---

## External benchmark — CVRPLIB, 4.3% mean gap

The strongest external anchor the project has, and the honest headline number.

| instance | n | customers/route | best of 5 | mean of 5 | vs best-known (best) | (mean) |
|---|---|---|---|---|---|---|
| X-n101-k25 | 101 | 4.0 | 28,352 | 28,496 | +2.76% | +3.28% |
| X-n153-k22 | 153 | 7.0 | 21,786 | 22,097 | +2.67% | +4.13% |
| X-n200-k36 | 200 | 5.6 | 60,670 | 60,770 | +3.57% | +3.74% |
| X-n303-k21 | 303 | 14.4 | 23,111 | 23,282 | +6.33% | +7.11% |
| X-n401-k29 | 401 | 13.8 | 68,543 | 69,049 | +3.61% | +4.38% |
| X-n502-k39 | 502 | 12.9 | 70,581 | 70,723 | **+1.96%** | +2.16% |
| X-n701-k44 | 701 | 15.9 | 86,699 | 87,152 | +5.83% | +6.38% |
| X-n1001-k43 | 1001 | 23.3 | 78,013 | 78,208 | **+7.82%** | +8.09% |
| | | | | **mean** | **+4.32%** | **+4.91%** |

*600 s per run, 5 seeds, greedy construction. Every result feasible, vehicle count at or under the
instance's `k`. PyVRP on the same budget sits at 0.0–1.8% from best-known.*

**Provenance, stated because it is weaker than everything else in this file.** The harness came from
an external review and lives outside the repository, so these runs are **not reproducible from a
clean checkout** and **no solver commit was recorded** — only the run date, 2026-08-24, which places
them after the scoring rework and the time-based schedule but before raw-delta accounting. They are
reported because a rough external anchor beats none, and they are flagged rather than promoted to
the same standing as the paired studies below. Making them reproducible is
[planning/experiments/ablations.md](planning/experiments/ablations.md) work.

**The gap tracks route length, not instance size.** The two predictors are collinear at r = +0.94,
so the marginal correlations settle nothing on their own. Controlling for one and then the other
does separate them:

| | marginal | controlling for log n | controlling for customers/route |
|---|---|---|---|
| gap vs customers per route | +0.74 | **+0.75** | — |
| gap vs routes used | +0.19 | **−0.44** | — |
| gap vs log n | +0.56 | — | **−0.58** |

Route length survives the control; instance size changes sign under it. So more routes at a fixed
size means a *smaller* gap.

**Weak, and stated as weak.** Eight instances with one control leaves 5 degrees of freedom, where
|r| must exceed about 0.75 to clear p < 0.05. The route-length figure sits exactly on that line.
This is a direction worth testing, not a result.

**This is a single-depot special case of the model.** The solver's own problem — chained routes
across depots, open at both ends — is MDVRPI, which has its own published benchmark that needs
per-vehicle duration limits before it can be run. See
[planning/problem-model/vehicle-time-limits.md](planning/problem-model/vehicle-time-limits.md).

---

## Best known solutions

### Reference family — 500 customers, capacity 400

| solver | objective | budget  | note                                   |
|---|---|---------|----------------------------------------|
| **Hexaly** | **1840.18** | 180 s   | Next improvement was at 261 s          |
| this solver | **1875–1890** | 1–3 min | current, routinely reached             |
| this solver | 1890.87 | 180 s   | 2026-08-21, `EXACT_REORDER_MAX_SPAN = 4` |
| this solver | 1915.97 | 180 s   | 2026-08-18, K=8, pre-family-tree       |

**The gap against a converged Hexaly is 3.32%.** For reference: in 10 minutes, Hexaly achieved a best solution value of 1830.18. 

**No routes are saved for this family.** These numbers come from run logs, so unlike the entries
below they cannot be rebuilt or re-verified. Fixing that is
[planning/problem-model/warm-start.md](planning/problem-model/warm-start.md), which also gives the
loader a saved solution needs.

### Small family — 200 customers, capacity 25

| solver | objective | budget | vehicles | routes | travel | saved |
|---|---|---|---|---|---|---|
| **Hexaly** | **3355.82** | 600 s | 3 | 45 | 3265.82 | `solutions/best_3355.82.json` |
| **this solver** | **3381.54** | 180 s | 2 | 47 | 3301.54 | `solutions/best_3381.54.json` |
| this solver | 3461.10 | 60 s | 3 | — | 3371.10 | `solutions/best_3461.10.json` |
| this solver | 3462.72 | 60 s | 2 | — | 3382.72 | `solutions/best_3462.72.json` |
| this solver | 3473.64 | 60 s | 3 | — | 3382.72 | `solutions/best_3473.64.json` |

**The gap against Hexaly here is 0.77%**, and it is a same-budget comparison rather than a favorable
one. Hexaly ran 600 s but **first reached 3355.82 at 178 s**, so its remaining 420 s bought nothing.
This solver reached 3381.54 in 180 s. Solver commit `4bd2d15`, 6.0M iterations, 48 plateau reheats,
0 complete reheats, defaults except `max_time`.

**Hexaly's own lower bound says nothing about how good either number is.** It reports a 99.11%
optimality gap against a bound of 30, which is the vehicle and depot cost with the entire routing
term unbounded.

**The gap is routing, not vehicle count.** The two solutions have opposite structure: this solver
uses **two** vehicles, Hexaly uses three.

| | vehicles | depots | travel | objective |
|---|---|---|---|---|
| this solver | **2** | 3 | 3301.54 | 3381.54 |
| Hexaly | 3 | 3 | **3265.82** | 3355.82 |

Hexaly pays 10 more for the third vehicle and wins 35.72 on travel. So the two-vehicle structure is
**earning** its keep, and the whole 25.72 deficit — more than it, in fact — is routing quality.
Reading this as "we found the other shape" would be wrong.

The three earlier 60 s records show the same term nearly balanced from the other direction: the top
two sit **1.62 apart with opposite structure**, one leaving a vehicle empty and paying 11.6 in
travel, the other paying for the third vehicle and taking the 11.6 back. Neither shape is
established as better on this instance.

Each file stores the full route list plus the instance descriptor, and each is re-verified against a
freshly built instance from raw geometry — independent of the solver code. Coverage, capacity, depot
chaining, travel and objective all agree to within 5e-13. **That is the standard the reference
family does not yet meet.**

Route order is not meaningful in the Hexaly file. It reports the routes a vehicle serves but not the
sequence, so the file records that a feasible ordering exists per vehicle rather than which one.

---

## Operator ablation — the finding that mattered most

`RandomCustomerChainReversal` shows **1.09% acceptance** and consumes **0.95 s of a 60 s run**. By
every statistic the solver reported about itself, it was negligible.

| finding | size | delta | σ |
|---|---|---|---|
| **drop `RandomCustomerChainReversal`** | 5000 | +157.32 (1.70%) | +18.7 |
| drop `RandomCustomerChainReversal` | 500 | +45.20 (2.16%) | +3.6 |
| drop `ReverseClosestPairTogether` | 5000 | +64.60 (0.70%) | +6.9 |
| `NEIGHBOR_ROUTE_DRAWS` 8 → 16 | 5000 | −51.24 (0.55%) | −3.7 |
| `NEIGHBOR_ROUTE_DRAWS` 8 → 4 | 5000 | +24.98 (0.27%) | +3.1 |

*One-factor-at-a-time, paired on seed, breadth-first over seeds. 1,641 runs across 21 seed-rounds,
no failures. Commit `58ae053`.*

Removing that one operator costs more than every other operator combined. It is cheap and extremely
high-volume, so it contributes through **throughput rather than hit rate** — and acceptance rate,
the metric the roster had been ranked by, is structurally blind to that.

**Operator value here is judged by ablation, and never by acceptance rate.**

---

## The scoring could not price rarity against cost — found, then fixed

> **RESOLVED 2026-08-22.** Everything in this section describes the solver **before** the scoring
> rework (`c539a1e` … `6940351`) and before `EXACT_REORDER_MAX_SPAN` was ablated down to 4
> (`a54710e`). It is kept in full because the defect is the reason both changes exist, and because
> the diagnosis generalizes. **The current measurement is at the end of the section.**

An exact span-reordering operator was **the most expensive thing in the roster and carried its
highest weight at the same time.** Removing it made the solver better.

> **Read with the full-roster K sweep below.** Removing the operator helps AT ITS SHIPPED SPAN.
> Shortening the span helps MORE while keeping it. The scoring failure is real; "the operator is a
> liability" is not the conclusion.

| arm | mean | paired delta | σ | seeds won |
|---|---|---|---|---|
| control (full roster) | 1958.87 | — | — | — |
| **drop `ReorderShortSpanExactly`** | **1934.28** | **−24.59 (−1.26%)** | **−4.8** | **16/20** |
| drop the whole OPTIMIZED subtree | 1957.27 | −1.60 | −0.3 | 13/20 |
| `reaction_factor` 0.01 → 1 | 1978.45 | +19.58 | +4.4 | 4/20 |

*n=500 capacity 400, 180 s, NN start. 8 arms × 20 paired seeds, breadth-first, no infeasible runs.
Solver `8ddc893`, data and plot in `experiment_logs/ablations/2026-08-20_greedy_subtree_n500/`.*

**The operator was not mispriced by a little.** In an earlier profiled run it took **74% of wall
clock** while producing **7.5 improving moves per second, against 755** for
`ReverseClosestPairTogether` — a hundredfold difference in productivity, with the weighting ranking
it first. It makes rare large improvements, and `score = |improvement|^1.5 / mean_cost` rewards
magnitude superlinearly while dividing cost only linearly.

**The larger problem is at plateau.** When nothing is scoring, every weight converges toward
uniform -- the EMA carries proposed operators together, and unproposed ones are pulled back toward
the roster's geometric mean. Uniform weight means equal draw probability **regardless of cost**, so
an operator costing a hundred times more consumes a hundred times the clock for the same number of
attempts.

That is exactly backwards. A plateau is escaped by making many attempts, so throughput matters more
there than anywhere else in a run — and it is precisely where the weighting stops distinguishing
cheap from expensive.

Mean plateau reheats per arm show it directly:

| carrying the operator | | without it | |
|---|---|---|---|
| control | 2.0 | drop the OPTIMIZED subtree | 7.7 |
| K=7 | 3.8 | `farthest-only` | 6.6 |
| K=8 | 1.9 | | |
| K=9 | 0.7 | | |
| K=10 | **0.0** | | |

**K=10 never reached a plateau at all in twenty runs.** It did not get stuck; it ran out of time
first. The arms without the operator plateaued three to four times as often, which is the throughput
the objective difference is made of.

**So this is a scoring result, not an operator result.** Per METHODOLOGY, an operator whose removal
helps indicts the mechanism that kept paying for it — and its per-call cost is far under the 10 ms
where budget gating, rather than scoring, would be the honest explanation. Deleting the operator
would hide the defect rather than fix it.

Dropping the whole optimized subtree is a **wash at −0.3σ**, so the farthest-insertion operators are
earning their place. Only the exact one is negative.

### Span size, on the FULL roster — the operator earns its place at K=4

Only `max_span` varies. Every arm carries all 24 operators, farthest-insertion included.

| arm | mean | sd | paired delta | σ | won | plateau reheats |
|---|---|---|---|---|---|---|
| control, K=8 | 1932.36 | 21.09 | — | — | — | 12 |
| **K=4** | 1902.65 | 12.12 | **−29.70** | −4.7 | 14/15 | 34 |
| **K=5** | 1902.13 | 15.68 | **−30.23** | −4.0 | 13/15 | 31 |
| K=6 | 1914.25 | 28.01 | −18.11 | −2.0 | 11/15 | 25 |
| K=7 | 1922.27 | 23.29 | −10.08 | −1.7 | 9/15 | 19 |
| K=8, replicate of control | 1930.30 | 19.25 | −2.05 | −0.3 | 7/15 | 12 |

*n=500 capacity 400, 600 s, NN start. 15 paired seeds, 90 runs, no infeasible results. Solver
`953db60`, data and plot in `experiment_logs/ablations/2026-08-21_full_roster_k/`.*

**The replicate is the point of the design.** It is the control's own configuration run as a separate
arm, so its −0.3σ over 15 seeds is the noise floor measured directly rather than assumed. The K=4 and
K=5 results sit six times outside it.

**Dropping the operator gained 24.59. Keeping it at K=4 gains 29.70.** So the earlier result was
about the span, not the operator. K=4 and K=5 are indistinguishable from each other and both clear
the 3σ bar; K=6 and K=7 sit inside the noise.

**The reheat column is the mechanism.** Plateau reheats run 12, 19, 25, 31, 34 as K falls — the cheap
arms plateau nearly three times as often in the same wall clock. That is throughput converting
directly into objective, and it matches the exact-only sweep where K=10 never plateaued once in
twenty runs. The K=4 standard deviation also falls to 12.12 against the control's 21.09: less
variance, not only a better mean.

**What the scoring got wrong here.** The weighting had K=8 and never demoted it, across every run
in both sweeps. A mechanism that priced improvement against cost correctly would have found this
without an ablation. `K` is still not a thing the solver can learn — that is
[planning/family-generation.md](planning/operator-selection/family-generation.md) — but the pricing that would let it
is now built:
[design/operator_selection/dynamic_penalty.md](design/operator_selection/dynamic_penalty.md).

**Untested: K below 4.** The trend has not turned. K=3 is the shortest meaningful span.

### Where the operator sits now

Same operator, current solver, one 60 s run on the reference instance:

| | before (profiled, pre-rework) | now |
|---|---|---|
| share of wall clock | **74%** | **2.6%** (1.57 s of 60 s) |
| improving moves per second | **7.5** | **20.0** |
| mean call time | — | 41.5 µs |
| calls | — | 37,901 |
| no-op returns | — | **36,333 of 37,901 (95.9%)** |

*Single run, so the figures are a state check rather than a paired comparison. Mean improvement per
improving call is 0.93, and the operator can only improve — a worse arrangement is never proposed.*

**Three shipped changes produced this and one run cannot apportion them.**

1. `EXACT_REORDER_MAX_SPAN` 8 → 4. Exact reordering enumerates the span, so this is the largest
   single factor by a wide margin.
2. The scoring rework split `adj_weight` into `weight × penalty`. Weight is an EMA of score per
   proposal and decays; penalty is `min(cost)/cost`, recomputed each segment from measured cost and
   **never decayed**. Benefit is forgotten, cost is not, so the plateau failure described above
   cannot recur in the same form.
3. No-op detection. 95.9% of calls now report NO-OP instead of re-deriving an arrangement already on
   the table.

**What this does not establish.** Point 2 is the mechanism these numbers are consistent with, not a
measurement of it. Isolating the penalty's contribution is an ablation, and it is listed in
[planning/experiments/ablations.md](planning/experiments/ablations.md) rather than claimed here.

### Span size, on an exact-only roster

| K | paired delta vs control | σ | seeds won |
|---|---|---|---|
| 7 | +13.28 | +2.3 | 7/20 |
| 8 | +22.36 | +3.7 | 5/20 |
| 9 | +35.79 | +5.1 | 2/20 |
| 10 | +58.29 | +10.2 | 0/20 |

Monotone: larger K is strictly worse, and K=10 lost every seed.

**This does not settle what K should be.** These arms removed the farthest-insertion operators, so
they compare K values against each other on a roster nobody ships. The earlier hand sweep that
favoured K=9 used the full roster, and the two are not comparable. Every arm also ran under the
scoring being replaced, and K's value is precisely a question of how rarity is priced against cost.
A full-roster sweep varying only `max_span` is queued in `planning/ablations.md`.

---

## Construction — 39× faster, bit-identical

| customers | before | after |
|---|---|---|
| 5,000 | 8.094 s | **0.209 s** |

Nearest-neighbor tables replaced repeated linear scans in `make_initial_solution`.

Verified by producing a **bit-identical solution** — same objective *and* same route-order hash.
That required the table's tie-breaking to match `argmin`'s exactly, which is why `nearest_indices`
sorts with `np.lexsort((candidates, distances))` rather than taking `argpartition`'s arbitrary
order. A speedup that changes which solution is built is not a speedup, it is a different algorithm.

---

## Geometric guidance — mechanism confirmed, objective not

The same move type, blind destination versus geometrically chosen, in one 60 s run at 500 customers
so both saw identical conditions:

| move type | blind | guided |
|---|---|---|
| relocate | 0.00%, **0** accepts | 0.30%, **654** accepts |
| cross-exchange | 0.01%, **1** accept | 0.46%, **1703** accepts |

Decisive as a mechanism check — random destination selection was doing essentially nothing.

**The objective effect is not established.** +15.56 ± 7.42, winning 4 of 5 — roughly 2σ, under the
bar. Acceptance rate is exactly the metric shown above to be unable to rank operators, so this is
reported as evidence the mechanism works, not as evidence it is worth its cost. The
inverted-view refactor it would justify stays gated until ablation says otherwise.

---

## Parameter tuning: a withdrawal and a null

The most useful section here, so it gets the space.

### The result that was accepted, then withdrawn

An Optuna search over the operator-selection parameters found `segment_length = 10` against a
shipped default of 100. It measured 1.54% ± 0.26%, or 5.8σ. A paired re-measurement on unseen seeds
reproduced it — 5 configurations of 5, at 4–7σ. A third experiment isolated the effect to that one
parameter; the other two contributed under 1σ.

Three independent experiments agreed. It was wrong anyway, for two separate reasons.

**First: real, but only where it was measured.** The search ran at 500 customers and capacity 400 —
about seven long routes. The instance being solved by hand at the time was the small family, 200
customers at capacity 25, about forty-seven short ones. On that shape the tuned value **lost roughly
2%**. (The reference instance has since become the 500/400 shape, which does not rescue the result:
it was never validated at both.)

Sigma measures whether an effect is real. It says nothing about where it applies. Every trial shared
one instance shape, so no amount of significance inside the search could have detected that.

**Second: the instrument was broken by one of the parameters being searched.**
`OperatorStats.record_accept` decided whether a move improved by testing `score > 0`, which was
correct while `score` carried the sign of the improvement. Then a floor was added so that operators
paying off through exploration could earn weight:

```python
score = max(explore_reward, sign * abs(improvement) ** 1.5) / mean_cost
```

The floor is positive, so it removed the sign. From that commit on, `score > 0` was **always true**
and every accepted move counted as an improvement.

That counter is not a reporting field. `update_weights` reads it as `improving_moves`, and
`improving_moves == 0` is what advances the plateau counter toward a reheat — so **plateau reheating
silently stopped firing.** Meanwhile `segment_length`, one of the searched parameters, sets
`max_plateau_size`. The search was tuning the reheat trigger against a reheat mechanism that could
not fire, using a signal corrupted by a third searched parameter.

The whole pipeline is void: search, validation, isolation run. Reproducibility across three
experiments did not help, because they shared the defect rather than testing it.

**What it cost and what it did not.** `git log` separates the eras: ablation `58ae053` predates the
floor `b5167e0`; the tuning `d237419` follows it. The ablation stands. Best-known objectives are
unaffected — a found solution is real regardless of what the solver believed while finding it, and
every entry in `solutions/` is re-verified from raw geometry.

The suite stayed green throughout, because nothing in it asserted anything about that counter. It
was a reporting field that quietly became a control input, and no oracle covered it.

### The rerun found nothing, which is the answer

With the counter fixed, the search ran again — **149 trials, 10 hours**, on the reference instance
this time rather than the sanity-check shape whose results had failed to transfer. `preflight.py`
gated the launch: counter neither dead nor saturated (improved/accepts 0.085, not 1.000), reheating
firing (13 in 60 s, not 0).

| | score | vs defaults |
|---|---|---|
| best | 0.9889 | **−1.11%** |
| median | 0.9997 | −0.03% |
| mean | 1.0012 | +0.12% |
| worst | 1.0231 | **+2.31%** |

| | |
|---|---|
| trials beating defaults | 76 of 149 — **51%** |
| best, in trial standard deviations | **1.8σ** (sd = 0.0062) |
| expected minimum of 149 pure-noise draws | **≈ 0.9833** |

**The best trial is less extreme than noise alone would produce.** 149 draws from a distribution
centered on the defaults should yield a minimum near 0.9833; the observed best was 0.9889. The
apparent 1.11% gain is selection, not signal.

Two more readings agree. A **51% win rate is a coin flip**, and Optuna concentrates sampling where
it has already seen good values, so a real gradient should push that well above half. And the spread
is **asymmetric** — you can lose 2.31% but only gain 1.11% — which places the defaults near the top
of the achievable distribution rather than in the middle of it.

This replicates an earlier result: a 704-trial search over the annealing schedule was also flat, and
hand defaults also won a paired 240 s validation. **Two independent searches over different
parameter sets have now failed to beat hand-chosen values.** The conclusion is not that tuning was
done badly — it is that this solver is insensitive to these parameters at this instance shape, and
the remaining variance is the noise floor rather than anything a search can reach.

One unresolved trace, recorded as untested: `segment_length` in the 15 best trials ran 18–79, all
below the default of 100. Suggestive, but confounded — the sampler concentrates, so a cluster among
the winners is partly the sampler agreeing with itself.

---

## Known limitations

Stated because a portfolio project that lists only its strengths is not evidence of judgment.

**The solver's own problem has a published benchmark, and it cannot run it yet.** Chained routes
across depots, open at both ends, is MDVRPI — Crevier, Cordeau and Laporte, *EJOR* 176(2), 2007 —
and that benchmark caps each rotation's duration. This model has no notion of time, so the
comparison is unavailable until
[vehicle-time-limits](planning/problem-model/vehicle-time-limits.md) lands. Run on the
**relaxation** with the duration cap dropped, which is a strictly easier problem, an external review
measured 5.9% above published values on 8 of 10 instances while overshooting the cap by up to 83%.
That is not a score; it is the reason the feature is next.

**Against Hexaly the gap is 0.8–1.6%, with a massive gap in throughput.** Hexaly reaches 1861.41 on the
reference instance and converges — tripling its budget to 180 s gained 0.1, improving to around 1846 in 10 minutes.
This solver reaches
1875–1890 in one to three minutes, buying 1.33% in
the second half of a run. Hexaly runs **~20-50x more iterations per second**. So the honest reading is
"under 2% behind a converged commercial solver, at 2-5% of the throughput", with this solver's
own convergence still unmeasured. How close 1846 is to optimal remains unknown.

**The internal experiments still rest on one generated family.** Every ablation and both parameter
searches ran on the reference and small families, which are one generator at two capacities. The
CVRPLIB table at the top of this file is the counterweight, and it is weaker evidence — not
reproducible from a clean checkout, and no solver commit recorded. The withdrawn result below is
what a single family costs: a finding can be real, reproduced, and still local to its shape.

**The neighborhood is deep intra-route and thin inter-route.** Five chain-swap variants, chain
reversal, three farthest-insertion reorders and an exact short-span optimizer act inside a route.
Moving customers *between* routes has fewer mechanisms and no large-neighborhood operator at all.
[ruin-and-recreate](planning/search-methods/ruin-and-recreate.md) is the named gap, and its
primitives have landed.

**Runs are not reproducible, and the fix is not simply a fixed iteration count.** A seed does not
fix the trajectory, for two independent reasons:

1. **Wall-clock termination.** Run length varies with machine speed and load.
2. **Operator weighting is TIMING-BASED.** `mean_valid_call_time` divides into every score, so CPU load
   changes which operators get selected. This one alters the trajectory even at a fixed iteration
   count.

Iteration-count termination removes only the first, and **it must not be used to tune this
solver.** Under a fixed iteration budget an expensive operator is free, so a configuration that
shifts weight toward expensive operators wins the test and loses in production. That is bias, not
noise, and it lands on exactly the parameters that control operator cost.

Removing the second source means `set_deterministic_weighting`, which forces mean cost to 1 -- and
then the run is reproducible but is no longer the solver anybody ships.

**So reproducibility and production fidelity are in tension, and validity wins.** A test has to
measure what a user gets: solution quality at a fixed TIME limit. That is why the searches average
many short runs instead of quieting the objective, and it leaves exactly one way to lower the noise
floor -- more runs. The floor is near 0.5% on a single run, 0.62% per trial in the search above.
See `planning/joint-parameter-search.md`.

**The defaults are partly tuned, and no later work has beaten them.** The first schedule search did
change them: `max_plateau_size` 10k -> 2k, a re-evaluated initial temperature, a slower anneal, and
the impetus for the objective-anchored reheat redesign. Nothing since -- later searches, added
operators, or bugfixes -- has decisively beaten that set.

Proving one does is a **power** problem, not a design problem. Separating configurations that differ
by ~1% needs many more runs per configuration, and mean-sigma falls as sqrt(n), so the budget goes
from hours to days. Out of scope at this stage.

**The exploration floor is bounded above, not shown to help.** Accepted uphill moves used to score
zero, so an operator that paid off through exploration could never earn weight. The `explore_reward`
floor fixes that, and dividing by `mean_cost` separates cheap explorers from expensive ones rather
than merely rewarding exploration.

A 120-run paired ablation found `1e-2` **costs 2.77%**, while `1e-5` and `1e-8` are indistinguishable
from no floor at all. So too large a value demonstrably hurts, and no value demonstrably helps. That
experiment could only resolve effects above ~3%, so it does not rule out a smaller benefit. See
`planning/ablations.md`.

## References

- [METHODOLOGY.md](METHODOLOGY.md) -- the rules used to accept or reject every measurement here
- [planning/operator-selection/family-generation.md](planning/operator-selection/family-generation.md) -- K is not yet learnable by the solver; this is the open plan for that
- [design/operator_selection/dynamic_penalty.md](design/operator_selection/dynamic_penalty.md) -- the pricing mechanism now built to let the solver learn K itself
- [planning/experiments/ablations.md](planning/experiments/ablations.md) -- where the two unrun measurements this file names are queued: making the CVRPLIB benchmark reproducible, and isolating the cost penalty's contribution
- [planning/problem-model/warm-start.md](planning/problem-model/warm-start.md) -- the loader that would let the reference family's best-known solutions be saved and re-verified like the small family's
- [planning/search-methods/ruin-and-recreate.md](planning/search-methods/ruin-and-recreate.md) -- the named fix for the thin inter-route neighborhood listed under Known limitations
- [planning/problem-model/vehicle-time-limits.md](planning/problem-model/vehicle-time-limits.md) -- the feature that unlocks the MDVRPI benchmark, which is the published instance set for this solver's actual problem

## Links to here

- [design/README.md](design/README.md) -- referenced in design folder index
- [planning/README.md](planning/README.md)
- [planning/problem-model/asymmetric-distances.md](planning/problem-model/asymmetric-distances.md)
- [planning/core-refactors/inverted-view-refactor.md](planning/core-refactors/inverted-view-refactor.md)
- [planning/experiments/joint-parameter-search.md](planning/experiments/joint-parameter-search.md)
- [experiment_logs/README.md](experiment_logs/README.md) -- cites this file's reasoning to explain a withdrawn re-tune result
- [METHODOLOGY.md](METHODOLOGY.md) -- states the rules these measurements are verified and accepted under
