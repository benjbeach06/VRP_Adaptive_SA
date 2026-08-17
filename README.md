# Multi-depot VRP solver

A simulated-annealing solver for the multi-depot, multi-vehicle capacitated vehicle routing
problem, written from scratch in Python. Routes may start and end at different depots, vehicles
run several routes in sequence, and the objective prices travel, vehicle use, depot use and
capacity overload together.

The interesting part is not the metaheuristic — it is the **measurement discipline around it**.
Most of what follows exists because a plausible-sounding improvement turned out, when measured, to
be wrong.

---

## Results

| | |
|---|---|
| **Construction** | 8.094 s → **0.209 s** at 5,000 customers (39×), producing a **bit-identical** solution |
| **Operator selection** | `segment_length` was 10× too coarse: **1.54% ± 0.26%** (5.8σ), reproduced on unseen seeds by 5/5 configurations at 4–7σ |
| **Roster** | 20 operators, ablated individually across 1,641 runs |
| **Best known** | 3473.64 on the reference 200-customer instance at a 60 s budget |

### The finding that mattered most

`RandomCustomerChainReversal` shows **1.09% acceptance** and consumes **0.95 s of a 60 s run**. By
every statistic the solver reported, it was negligible.

Ablation says removing it costs **1.70% of the objective at σ = 18.7** — the largest effect in the
entire study, larger than every other operator combined.

It is cheap and extremely high-volume, so it contributes through throughput rather than hit rate.
The metric the roster had been ranked by could not see it. That result is why operator value here
is now judged by ablation, and never by acceptance rate.

---

## How results are accepted

Four rules, each learned by getting it wrong first.

**A clean run means nothing until the detector is shown to fire.** `tools/stress.py --inject-delta`
deliberately corrupts a move's price; if that does *not* produce findings, the harness is broken and
its zero-findings runs were worthless. An hour of correctness testing was once run against detectors
that had never been verified.

**Every incrementally-maintained quantity has a recompute-from-scratch twin.** Cached loads, depot
usage indices and objective terms are each checked against an oracle that recomputes them naively.
Most real bugs here surfaced as a disagreement between the fast path and the slow one.

**Report from bucket means, never the argmax.** Selecting the best of N noisy trials biases the
estimate upward. An earlier tuning report recommended a value sitting in the *worst* quintile of its
own table; the current one reports quartile means and a top-decile median, and states the noise
floor first.

**Compare within one run wherever possible.** Wall-clock termination means a fixed seed does not fix
the trajectory. Two operators competing inside the same solve share every condition; two separate
solves do not, and the difference swamped several early comparisons.

---

## Architecture

**`SimAnn_VRP_Core_Model.py`** — the data model and all delta arithmetic. Routes are doubly-linked
visit chains owned by vehicles. Every mutation has a matching `cost_deltas_if_*` function that
prices it in O(1) from boundary arcs, so the search never recomputes a full objective.

**`SimAnn_VRP_BLOperators.py`** — the move lifecycle: `evaluate` → `apply` → `commit` | `revert`.
A `Move` carries its own applied/not-applied state, so callers never infer it out of band. Two
`ClassVar` flags cover the awkward cases: operators that must mutate in order to price, and
operators that decide part of their own operands while pricing.

**`SimAnn_VRP_Operators.py`** — 20 operators over that lifecycle, plus operand selection. Selection
is where most of the performance lives: the same move type accepts 0.00% of proposals with a random
destination and 0.46% with a geometrically chosen one.

**`SimAnn_VRP_Solver.py`** — annealing schedule, adaptive operator weighting, plateau-triggered
reheating anchored to the current objective so the temperature self-calibrates.

### Tooling

| tool | purpose |
|---|---|
| `tools/stress.py` | randomized correctness stress with per-operator coverage and fault injection |
| `tools/profile_operators.py` | per-operator cost across instance sizes, with an injected-cost self-check |
| `tools/ablate_operators.py` | one-factor-at-a-time ablation, paired on seed, breadth-first over seeds |
| `tools/tune.py` / `tools/validate.py` | Optuna search, then paired re-measurement on unseen seeds |

---

## Running it

```bash
python SimAnn_VRP.py
```

Verification:

```bash
VRP_FULL_MATRIX=1 python -m unittest discover -s tests
```

```bash
python tools/stress.py --budget-seconds 45
```

---

## Known limitations

Stated because a portfolio project that lists only its strengths is not evidence of judgment.

**No external benchmark yet.** Every number here is the solver measured against itself. Whether it
is 2% or 20% off a commercial solver is unknown; a Hexaly comparison is the next planned step and
is the only measurement that would settle it.

**Wall-clock termination makes runs non-reproducible.** A fixed seed does not fix the iteration
count, which sets a noise floor of roughly 0.5% on any single measurement and puts sub-0.5% effects
out of reach. Iteration-count termination would fix it.

**Operator scoring is unfinished.** Accepted uphill moves — the entire escape mechanism in
simulated annealing — were scored at zero until recently, so an operator whose value is exploration
could never earn weight. The floor now added is not yet tuned, and the proposal/accept timing split
it depends on is still open.

---

## What comes next

`planning/` holds the roadmap: one file per item, each stating the problem, the measurement
motivating it, and the gate that would justify starting. Most are deliberately **not** started, and
each records why.

The largest is a centralized customer-location index replacing the visit linked list, which would
make "where is customer *j*" O(1) and unlock ruin-and-recreate. It is gated on evidence that
geometric guidance is worth its cost — evidence that is now partly in, and recorded in
`planning/README.md` alongside the result that does *not* support it.
