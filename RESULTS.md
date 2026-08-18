# Results

Every measurement in this project, including the ones that did not survive checking. The rules used
to accept or reject them are in [METHODOLOGY.md](METHODOLOGY.md).

Unless stated otherwise: comparisons are paired on seed, the bar for significance is **|σ| ≥ 3**
(set by the number of comparisons), and the reference instance is 200 customers at vehicle capacity
25 on a 100×100 grid, seed 42.

---

## Best known solutions

| objective | budget | vehicles | travel | saved |
|---|---|---|---|---|
| **3461.10** | 60 s | 3 | 3371.10 | `solutions/best_3461.10.json` |
| 3462.72 | 60 s | 2 | 3382.72 | `solutions/best_3462.72.json` |
| 3473.64 | 60 s | 3 | 3382.72 | `solutions/best_3473.64.json` |

The top two sit **1.62 apart with opposite structure.** One leaves a vehicle empty and pays 11.6 in
travel; the other pays for the third vehicle and takes that 11.6 back. The vehicle-use term and the
routing it forces are close to balanced here, so neither shape is established as better.

Each file stores the full route list plus the instance descriptor, and each is re-verified against a
freshly built instance from raw geometry — independent of the solver code. Coverage, capacity, depot
chaining, travel and objective all agree to within 5e-13.

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
about seven long routes. The instance actually being solved is 200 customers at capacity 25, about
forty-seven short ones. On that shape the tuned value **lost roughly 2%**.

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

**No external benchmark.** Every number here is the solver measured against itself. Whether it is 2%
or 20% off a commercial solver is unknown, and it is the thing a reader should most want to know.
`Hexaly_VRP.py` builds the same instance for Hexaly and predates the rest of this work, so the
comparison is blocked on a license renewal rather than on code. It is the next planned step and the
only measurement that would settle the question.

**One instance family.** Almost every measurement comes from one generated family at two capacities.
The withdrawn result above is what that costs: a finding can be real, reproduced, and still local to
its shape.

**Wall-clock termination makes runs non-reproducible.** A fixed seed does not fix the iteration
count. That sets a noise floor near 0.5% on a single run — 0.62% per trial in the search above — and
puts smaller effects out of reach. Iteration-count termination would fix it, and is the gate on any
wider search (`planning/joint-parameter-search.md`).

**Operator selection is untuned, and the search says it does not need to be.** Shipped defaults are
the hand-chosen originals.

**Operator scoring is unfinished.** The `explore_reward` floor exists but its value is unproven —
the only search that addressed it is the void one. See `planning/operator-scoring.md`.
