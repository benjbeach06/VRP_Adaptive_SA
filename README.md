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
| **Roster** | 20 operators, ablated individually across 1,641 runs |
| **Operator selection** | a 5.8σ tuning result that **did not generalize** — see below |
| **Best known** | 3461.10 on the reference 200-customer instance at a 60 s budget |

### The finding that mattered most

`RandomCustomerChainReversal` shows **1.09% acceptance** and consumes **0.95 s of a 60 s run**. By
every statistic the solver reported, it was negligible.

Ablation says removing it costs **1.70% of the objective at σ = 18.7** — the largest effect in the
entire study, larger than every other operator combined.

It is cheap and extremely high-volume, so it contributes through throughput rather than hit rate.
The metric the roster had been ranked by could not see it. That result is why operator value here
is now judged by ablation, and never by acceptance rate.

### The result that did not survive

An Optuna search over the operator-selection parameters found `segment_length = 10` against a
shipped default of 100. It measured **1.54% ± 0.26%**, or 5.8σ. A separate paired re-measurement on
unseen seeds reproduced it, 5 configurations out of 5, at 4–7σ. A third experiment isolated it to
that one parameter — the other two contributed under 1σ.

Three independent experiments agreed. It was not adopted.

The whole search ran at 500 customers and vehicle capacity 400, which is about seven long routes.
The instance actually being solved is 200 customers at capacity 25 — about forty-seven short ones.
On that shape the tuned value **loses roughly 2%**. It is not a better default. It is the right
value for one route-count regime and the wrong value for another, and the search had no way to say
so, because every trial in it shared the same shape.

Sigma measures whether an effect is real. It says nothing about where the effect applies. Tune on
the shape you actually solve.

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
could never earn weight. A floor now exists. Its value is *unproven* rather than untuned: a search
across seven orders of magnitude could not constrain it, the surviving configurations disagreed by
three orders of magnitude, and isolating it left under 1σ. Either the floor does not matter or the
experiment could not see it, and those two have not been told apart.

**One instance shape.** Almost every measurement here comes from one generated family at two
capacities. The tuning failure above is what that costs: a result can be real, reproduced, and
still local to its shape.

---

## What comes next

`planning/` holds the roadmap: one file per item, each stating the problem, the measurement
motivating it, and the gate that would justify starting. Most are deliberately **not** started, and
each records why.

The largest is a centralized customer-location index replacing the visit linked list, which would
make "where is customer *j*" O(1) and unlock ruin-and-recreate. It is gated on evidence that
geometric guidance is worth its cost — evidence that is now partly in, and recorded in
`planning/README.md` alongside the result that does *not* support it.
