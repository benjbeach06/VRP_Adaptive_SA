# Retro — 2026-08-27, the raw-delta accounting plan

Scope: one planning cycle, start to finish, plus doc-tree maintenance. No code written.

## What happened

**Decided: the raw-delta accounting refactor.** The core model reports raw structural deltas only.
A static processor reconstructs objective terms and an accounting record. `OperatorBL` owns
bookkeeping on apply and revert. This removes the dual-truth structure, where pricing and mutation
each derive activation independently and nothing forces them to agree.

The design settled over five rounds. Transition form `(initial, final)` for load and customer
count, plain deltas for distance. An `UNASSIGNED` sentinel that makes route creation and disposal
ordinary transitions. Reconstruction reads `FullSolution` rather than carrying shadow state.
Comprehensive rollout, not staged.

**Sequencing changed.** `raw-delta-accounting` now precedes `route-distance-tracking`, which still
blocks `vehicle-time-limits`.

**Written.** [planning/raw-delta-accounting.md](../planning/raw-delta-accounting.md), and a
function-level touch list covering roughly 26 methods that stay, 29 the processor absorbs, 24 that
become raw producers, 44 mutator call sites, and 5 open questions for the implementing session.

**Fixed.** `route-distance-tracking.md`'s status, shape and gate. Three stale `## References`
entries in the 2026-08-26 retro. Four backlinks.

**Verified.** `unittest discover -s tests` works — 55 tests, 1 skip. This contradicts a claim in the
session carryover file, which was corrected. `check_links.sh` clean across 52 files.

### Attribution

The design is Benjamin's: the three-stage split, `num_use` against `is_used`, the `UNASSIGNED`
sentinel, reconstruction reading `FullSolution`, precede-not-subsume for distance tracking, and
rejecting both a staged rollout and a parallel path on blast-radius grounds.

Claude's: transition form for step-function fields, accepted for two of five fields and correctly
rejected for distance; identifying `depot_activation_delta_from_depot_num_usage_deltas` as the
existing prototype the processor generalizes; identifying `unlink_from_route_no_depot_accounting` as
the visible symptom of the entanglement, and its disappearance as a completion check; the
`ObjectiveTermDelta` default-value trap in the test harness; the inventory and both documents.

## What went well

**Benjamin's.**

- **"Have you taken even a brief look at it?"** One question ended four rounds of speculation. It
  was the highest-value message in the session and it cost a single line.
- **Objections answered with mechanism, not authority.** Every concern got a specific fact back.
  That is what allowed clean concession instead of defense.
- **Partial acceptance.** Transition form was taken for load and customer count and rejected for
  distance. A wholesale yes or no would have been worse in both directions.
- **The `UNASSIGNED` sentinel** removed a raised problem without adding a special case.

**Claude's.**

- The touch list is real work product: layered, batched, and explicit about which claims were
  verified against which were predicted from signatures.
- Three findings survived review — the existing prototype, the `no_depot_accounting` completion
  check, and the `ObjectiveTermDelta` default trap.
- Session files were appended before reporting rather than reconstructed afterward.

## What we can each learn

### Claude's, ranked by time lost

**1. Four rounds of objections from modeling the code instead of reading it.** Concern 1 was wrong:
accounting already runs during delta computation. Concern 2 was impossible: a parallel path means
duplicating the mutators. Composition already had implicit coverage. The oracle question had one
possible answer.

The class is covered by `feedback-stop-serial-speculation`, but the rule did not fire, because
"measure" was read as "run an experiment." **For a question about existing code, the read is the
measurement.**

The corrected form is not "always read." Cost is (turns times tokens-per-turn) plus real time, in
some weighted combination — token spend and wall-clock time are separate axes that add. Both
extremes are expensive. Benjamin: *"'always read' and 'always speculate' are dangerous
extremes; strive for a solid middle ground."* README first for orientation, then a targeted grep or
partial read, then a full read only for a moderate and central file.

**2. Asked a question whose answer was in text read one turn earlier.** The `_harness.py` docstring
states that the suite exists because cached quantities have recompute-from-scratch twins.
Benjamin: it *"only had one answer for any remotely competent developer."*

**3. Re-opened a closed decision.** Float drift was re-argued after periodic oracles had been
approved. `feedback-a-correction-is-final`.

**4. Raised documentation placement during planning.** Documentation is a post-implementation
concern and that workflow is already solved.

### The structural one

The session carryover file stated that `unittest discover` does not work here. It does. The same
file gave a HEAD and two commit hashes that are not in `git log`.

Both claims were written by an earlier session, so the authorship is Claude's. The fix belongs at
the handoff-creation stage, where the context to check still exists — not as a rule about
distrusting handoff files at read time. Benjamin: *"If they're stale that's a handoff fault;
verification of handoff claims should happen on the handoff-creation stage where the context
exists."*

**Acted on:** `.claude/skills/context_handoff/SKILL.md` gained a verification step. Every checkable
claim — branch, HEAD, commit hashes, test commands and their counts, file paths, push status — gets
run before it is written. A claim too expensive to check is dated and marked unverified, which is
acceptable; an unverified claim stated as fact is the defect. A check that disproves an existing
`_session/` claim corrects that file in the same turn.

## Workflow improvements

**Reads are cheap relative to speculation, and the expense of speculation lands on Benjamin's
attention rather than on the token budget.** This session used heavy Opus for over an hour and
reached roughly 20% of session usage. Token cost was never the binding constraint. Optimizing
output for concision is right; suppressing input reads to save tokens is not the same thing and was
the direct cause of the four bad rounds.

**A stale handoff claim gets fixed in the turn it is disproven.** The test command was verified and
the discrepancy reported, but the carryover file was left wrong in the same turn.

**Session files still went in one batch** near the end of the work rather than as events happened.

## Tooling assessment

**The doubly-linked reference tooling paid for itself within one session of being built.**

The proof is specific. A hand edit to `route-distance-tracking.md`'s gate section added a live body
link to the new plan. It went unnoticed. `check_links.sh` reported `REF MISSING` and `BACKLINK GAP`
on the next run. The tool caught a real miss by the person who had just finished using it.

It also found three stale references in the 2026-08-26 retro that predated this session.

Total cost was about six shell calls, with no repo greps and no reading of target files to discover
backlinks. The `link_doc_file` skill's constraints — do not read files in full, do not grep for
inbound links — held.

**On what the tooling does not check.** It validates the link graph, not the explanation text. That
is the correct division. The graph is the product and the graph is checked; explanations are useful
context that a reader could derive by following the link. Benjamin: *"Even if we removed link
explanations it would still be doing its job — a reader can... read for context."*

**One friction point, accepted.** `link_scan.py` rewrites files whose content it does not change.
`planning/implemented/README.md` showed as modified with a blob hash identical to the index. It adds
noise to `git status` during doc work. Recorded in `_session/obstacles.md` so the noise can be
filtered rather than investigated again.

## References

- [planning/raw-delta-accounting.md](../planning/raw-delta-accounting.md) -- the plan this session produced; the retro covers how it was arrived at, not what it says
## Links to here
