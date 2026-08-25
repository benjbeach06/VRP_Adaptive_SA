# Retro — the penalty rebuild and the time-based schedule

**Covers `23e8df2..ccf7089`, 2026-08-22 to 2026-08-25.** Six commits.

## What happened

The scoring rework's penalty was diagnosed as defective, rebuilt, tuned, and grounded against its
own starting point.

**Diagnosed.** The per-operator arm of the trajectory ablation showed the improvement-weighted
penalty promoting the expensive exhaustive operator instead of suppressing it — the opposite of what
it was built to do. A design defect, not an implementation bug: it reached commits and blocked
effective use.

**Rebuilt.** Cost left the score entirely. The penalty became a pure cost ratio, so cost is priced
exactly once. Three real defects surfaced alongside and were fixed: apply time never counted toward
`segment_time`; invalid and no-op proposals were invisible to the weight EMA's denominator; and the
penalty read a raw mean that bypassed the `weight_by_time` guard, which had quietly broken
determinism.

**Converted to time.** Weight decay moved to per-operator elapsed time. Cooling and plateau
detection moved onto one schedule clock, bimodal — the iteration clock stayed so
`set_deterministic_weighting()` could close all three wall-clock paths at once. Both
`SolverDeterminism` tests went green again as a result.

**Measured.** A 47-trial, 8-hour search over six parameters, then a 3-arm grounding ablation at 15
paired seeds. Both tuned arms beat the rework's stage-1 commit decisively.
`ReorderShortSpanExactly` fell from about half the wall clock to a few percent. Numbers in
[experiment_logs/ablations/2026-08-23_tuned_vs_stage1/README.md](../experiment_logs/ablations/2026-08-23_tuned_vs_stage1/README.md).

**Documented.** Three design docs; both finished plans moved to `planning/implemented/`
([scoring-rework.md](../planning/implemented/scoring-rework.md),
[hierarchical-magnetism.md](../planning/implemented/hierarchical-magnetism.md)); and
`tools/check_links.sh` built to enforce the doubly-linked reference rule.

## Attribution

**Benjamin.** The time-based EMA direction, and making it the default immediately rather than
sweeping first. The bimodal determinism fallback. Refusing the reduced parameter set. The
"original plan first, divergence last" structure for implemented plans. The rule that design docs
carry no results and no archaeology. The reference and back-link semantics. The gitignore rule. The
worktree path scheme. He also corrected a wrong claim of mine — that the reheat equilibrium needed
re-validating in seconds. It does not; it is unit-invariant.

**Claude.** Implementation throughout, the ablation and tuning harnesses, the center-picker, the
link checker, and the diagnosis write-ups.

## What went well

**Stopping work mid-turn on the parameter set.** Benjamin: "You proposed to reduce the tuning
parameter set and I never accepted." The 6-parameter search found a region a 4-parameter one would
have missed. The interruption was worth more than the tokens it cost.

**Shipping the default before tuning it.** The mechanism moved hard enough that a τ sweep first
would have been premature precision.

**Reframing a leftover as a feature.** "Iteration mode exists to enable determinism" is a better
justification than "it was there and we kept it", and it changed what the design doc says.

**Smoke-testing before the 2.5-hour ablation.** It caught a stale worktree that would have wasted
the entire run.

**Checking before blaming.** When determinism broke, confirming `segment_time` had exactly one
reader ruled out the obvious suspect and pointed at the real cause. Guessing would have gone the
wrong way.

## What we each learned

**Ranked by time lost.**

1. **Session files were not written live.** The whole hiccups log for 2026-08-23 was reconstructed
   from the transcript afterwards. Detail is permanently lost.
   → [feedback-log-session-files-live]
2. **Tooling was committed after the worktree that had to run it.** Silent failure: every tuned arm
   scored `inf` because the checkout held the old script.
   → [feedback-commit-before-worktree]
3. **A real measurement supported a wrong conclusion.** Throughput rose 174%, measured. Concluding
   the annealing schedule had "rescaled 2.7x" was wrong, because cooling and reheat are both
   iteration quantities and throughput cancels. It felt like evidence-based reasoning, which is why
   it passed its own check.
   → [feedback-stop-serial-speculation], new section
4. **Design docs were written as change logs.** "What changed", rejected alternatives, and results
   all appeared in documents that should state only what is and why.
   → [feedback-design-docs-state-what-is]
5. **An explicit structural instruction was not followed.** The implemented-plan layout had been
   stated, and the first draft inverted it anyway.

**Benjamin, and the evidence is thin.** Constructor defaults moved several times while documents
cited them, so a doc could be stale within the hour. Inherent to live tuning, and cheap to fix at
the end.

## What changed about how we work

- **Commit tooling before creating any worktree that runs it.** A worktree is a checkout;
  uncommitted work does not exist inside it.
- **Worktrees live at `_worktrees/<short-commit>` in the repo root**, keyed by commit so arms
  differing only in runtime parameters share one. The previous scheme sat 15 characters from the
  Windows path limit and got worse with every study committed.
- **Append to `_session/*.md` at the moment, not at the retro.**
- **Anything intentionally untracked goes in `.gitignore`**, so it stops being re-evaluated on every
  status check.
- **Retros get their own folder** ([README.md](README.md)), and each implemented plan links to the
  one covering its period.

## Memories written

| memory | what it records |
|---|---|
| `feedback-commit-before-worktree` | worktree ordering, keying, and the Windows path trap |
| `feedback-design-docs-state-what-is` | design docs state what is; implemented plans carry divergence |
| `feedback-log-session-files-live` | append to session files as things happen |
| `feedback-stop-serial-speculation` | updated: a real measurement can still support a wrong conclusion |

## References

- [planning/implemented/scoring-rework.md](../planning/implemented/scoring-rework.md) — the plan
  whose penalty was rebuilt in this period.
- [planning/implemented/hierarchical-magnetism.md](../planning/implemented/hierarchical-magnetism.md)
  — the plan that landed first and supplied the magnet.
- [README.md](README.md) — what belongs in a retro and what does not.

## Links to here

- [planning/implemented/scoring-rework.md](../planning/implemented/scoring-rework.md) — links to
  this retro as the record of the period it landed in.
- [planning/implemented/hierarchical-magnetism.md](../planning/implemented/hierarchical-magnetism.md)
  — same.
