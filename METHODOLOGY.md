# Methodology

How work in this repository gets verified and accepted. The measurements themselves are in
[RESULTS.md](RESULTS.md).

## Provenance

Part of this repository was written with AI assistance (Claude), and the split is specific enough to
measure. The `Pre_AI` branch marks the last commit before any was used.

| | `Pre_AI`, 2026-08-07 | today |
|---|----------------------|---|
| solver proper — model, operators, lifecycle, annealing | **4,902 lines**      | 7,513 |
| `tools/` — profiling, stress, ablation, tuning | 0                    | 1,770 |
| tests | 0                    | 1,116 |

The solver is mine. Its architecture — the delta arithmetic, the operator lifecycle, the
oracle-twin convention, the annealing schedule — was designed and built before an assistant touched
the project, and about two thirds of the current solver code is still that work.

Assistance went almost entirely into **instruments**: the profiling, ablation, stress and tuning
harnesses that produced the numbers in `RESULTS.md`, plus a test suite that grew from 47 lines to
roughly 2,900.

That is why provenance sits at the top of the methodology document instead of in a footnote. The two
are the same subject. Generating code and experiments quickly moves the binding constraint from
writing to verification — plausible work arrives faster than it can be reviewed — and every rule
below exists because something plausible turned out to be wrong.

The results that most needed a human were the ones where the machine was confident:

- The improvement-counter defect that voided a ten-hour pipeline was found by reading solver output
  that looked normal, not by any test.
- A tuned parameter that measured 5.8σ was rejected because it lost on the instance I actually run —
  noticed while solving, not while analyzing.
- Several intermediate results were asserted before being measured, and were retracted. The rule
  "report from bucket means, never the argmax" is one of those retractions.

What I would claim from this project is not the line count on either side of that table. It is that
the numbers in `RESULTS.md` are ones I checked myself, and that the ones which did not survive
checking are written down there next to the ones that did.

— Benjamin Beach

---

## How results get accepted here

Four rules, each learned by getting it wrong first, and one precondition underneath them.

**A clean run means nothing until the detector is shown to fire.** `tools/stress.py --inject-delta`
deliberately corrupts a move's price. If that does *not* produce findings, the harness is broken and
its zero-findings runs were worthless. An hour of correctness testing was once run against detectors
that had never been verified.

**Every incrementally-maintained quantity has a recompute-from-scratch twin.** Cached loads, depot
usage indices and objective terms are each checked against an oracle that recomputes them naively.
Most real bugs here surfaced as a disagreement between the fast path and the slow one.

**Report from bucket means, never the argmax.** Selecting the best of N noisy trials biases the
estimate. An earlier tuning report recommended a value sitting in the *worst* quintile of its own
table. Reports now give quartile means, a top-decile median, and the noise floor before the result —
and for a search, the expected minimum under pure noise, so the winner can be compared against what
chance alone would have produced.

**Compare within one run wherever possible.** Wall-clock termination means a fixed seed does not fix
the trajectory. Two operators competing inside the same solve share every condition. Two separate
solves do not, and that difference swamped several early comparisons.

**Underneath all four: all randomness goes through one seeded generator, and the search can be
frozen.** Scattered `random` calls make a run unreproducible in ways that are invisible until a
comparison disagrees with itself. One generator makes a run replayable; `set_deterministic_weighting`
additionally makes operator weighting a pure function of recorded improvements, so weighting can be
held fixed while something else is varied.

This is a precondition rather than a fifth rule. An oracle that disagrees intermittently cannot be
debugged, and a within-run comparison means nothing if the run cannot be repeated. It exists because
a throwaway test suite was kept instead of discarded — preserving it forced reproducibility, and
determinism fell out of that. Neither was the goal.

---

## What "sigma" means in these tables

**Per seed, paired.** Each seed contributes ONE delta -- the arm's objective minus the control's
objective on that same seed. Sigma is `mean(deltas) / (stdev(deltas) / sqrt(n_seeds))`, so `n` is the
seed count, never the run count.

Pairing is what makes 15 seeds enough. Both arms saw the same instance and the same solver seed, so
the per-seed component of variance cancels. In the K sweep the arm standard deviations were 12 to 28
while the standard errors on the paired deltas were 6 to 9.

Three things to keep in mind when reading it:

- **It is a t-statistic, not a z-score.** At 15 seeds there are 14 degrees of freedom and the tails
  are heavier than normal. "4.7 sigma" is more decisive-sounding than the sample supports if read as
  Gaussian.
- **The control is shared across every arm**, so the comparisons are correlated -- a lucky control
  draw shifts them all the same way. Adding a REPLICATE ARM, identical to the control, measures that
  directly. In the K sweep it came back at -0.3 sigma, which is what licensed reading the others.
- **Multiple comparisons apply.** Five arms against one control is why the bar is 3 sigma rather
  than 2.

---

## Record the PATH, not only the endpoint

**Every ablation records time against objective, per seed.** A final objective supports a table and
nothing else. The path supports convergence curves, tells you WHEN an arm pulled ahead, and shows
whether a losing arm was slow or stuck -- which the endpoint cannot distinguish.

The K sweep is the example. Its data holds one number per run, so the only graph it supports is a
distribution of paired deltas. The plateau-reheat counts hinted that the cheap arms simply ran more
iterations, but nothing in the file can confirm it.

**No solver change was needed.** The solver already reports elapsed time, best objective and
iteration count once per second at every debug level. `tools/ablate_param.py` was redirecting that
to a discarded buffer. It now parses it into a `path` field, one entry per report interval.

## Every ablation gets a folder and a plot

```
experiment_logs/ablations/<date>_<slug>/
    README.md      question, arms, instance, budget, solver commit, verdict
    results.json   raw data
    run.log        the tool's progress output
    deltas.png     paired delta per seed, and the spread
```

**The plot is not optional.** `tools/plot_ablation.py <folder>` produces it in one fixed format, so
two ablations can be compared by eye without re-deriving a chart. A table reports the mean; the plot
shows whether an arm won everywhere by a little or on a few seeds by a lot, which the mean hides.

**Include a replicate arm where the budget allows.** An arm identical to the control measures the
noise floor directly instead of assuming it. On the K sweep it came back at -0.3 sigma, and that is
what licensed reading the others.

The section in `RESULTS.md` describing an ablation links to its folder.

---

## What an ablation result MEANS

Acceptance decides whether a number is real. This decides what it is evidence of, and the obvious
reading is usually wrong.

**A correctly built selection system makes adding an operator safe.** Weighting exists so that a
weak operator costs little. So no operator addition should substantially disimprove the solver, and
when one does, **the mechanism is the suspect, not the operator.**

| ablation result | what it signals |
|---|---|
| **No measurable change** | The operator is POSSIBLY UNNECESSARY. Corroborate with acceptance and proposal rates -- low on both strengthens it. |
| **Removing it HELPS** | The scoring is flawed. The system kept paying for something it should have demoted and could not. |
| Removing it helps, AND per-call cost is 10 ms or more | The one genuine exception. A single call can consume the budget before any feedback loop reacts, which is a budget-gating problem rather than a scoring one. **1 ms is not extreme** -- the roster already holds operators there and the scoring is expected to handle them. |

So "removing operator X improves the objective" is not an argument for deleting X. It is an argument
that the pricing failed, and the operator is the symptom that made it visible.

---

## Before a long unattended run

A multi-hour job reports plausible numbers whether or not the instruments it steers by are working,
so three things happen before launch. This routine exists because skipping it cost a ten-hour
pipeline; the full account is in [RESULTS.md](RESULTS.md#parameter-tuning-a-withdrawal-and-a-null).

**The plan states what the measurement depends on, and what its result will license.** Two lines.
Naming the dependency puts it beside whatever is being changed, where a collision becomes visible.
Naming the scope makes it obvious whether a second instance shape is needed before a result can
become a default.

**Recent edits are reviewed against their purpose** — and the question is not "does this change do
what it says." It is **"what reads the value I changed, and what does it assume about it?"** The
defect that voided the tuning run was a correct edit whose consumer, one call away, assumed a
property the edit removed.

**The solver modules are committed.** A measurement is only citeable if its solver version is. An
uncommitted solver module means the recorded commit does not describe the code that ran, and no
later reader can recover what did. Docs and tooling may be dirty; the four solver modules may not.

**`tools/preflight.py` runs.** It performs one short solve at the target shape and asserts that the
statistics the job steers by are neither dead nor saturated. Two minutes against a ten-hour job is
0.3% overhead.

Every hit from the review becomes a permanent assertion in the preflight, so the suite is built out
of real failures rather than guessed ones.

---

## What the rules have caught

Stated here because a rule with no scalp is a slogan. Both cases are written up with their numbers
in [RESULTS.md](RESULTS.md).

**Acceptance rate cannot rank operators.** The roster's most valuable operator accepts 1.09% of its
proposals and looked negligible by every statistic the solver reported about itself. Ablation put it
at the largest effect in the study. Operator value here is judged by ablation, never by acceptance
rate.

**A statistic that becomes a control input needs an oracle.** An improvement counter was a reporting
field until the solver began reading it to detect plateaus. When a later change silently saturated
it, the test suite stayed green — because nothing in it asserted anything about that counter. The
lesson is not "test more"; it is that the category of things needing oracles had grown and nobody
noticed.

**The argmax of a search is not a result.** A 149-trial search produced an apparent 1.11% winner.
Compared against the expected minimum of 149 pure-noise draws, it was *less* extreme than chance
alone would give. Reading the argmax would have made it look adoptable.
