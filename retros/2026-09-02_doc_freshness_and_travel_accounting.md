# Retro — per-route travel, slotting, and a documentation freshness pass

Covers 2026-08-31 to 2026-09-02, after the finalization recorded in section 6 of
[2026-08-29_raw_delta_accounting_implementation.md](2026-08-29_raw_delta_accounting_implementation.md).

## 1. What happened

Two commits landed, plus a documentation pass and two new best-known solutions.

### Built

**`6df59e0` — travel attributed per route through the accounting pipeline.** Benjamin's call.
`RawDeltaRecord.travel_distance`, a single number, became `travel_changes`, a per-route delta map;
the bulk figure is now a derived property. `AccountingRecord` gained `route_delta_travel` and
`vehicle_delta_travel`, both plain deltas, so apply adds and `inverse` negates.
`Route.current_travel` and `Vehicle.current_travel` are sink-written, with `total_distance()` and
`get_total_distance()` kept as the recompute twins. No mutator touches either cache.

**`4bd2d15` — `__slots__` across the core model.** Benjamin's work. `RouteVisit` stopped inheriting
`Node`. Claude diagnosed two bugs and wrote `tools/compare_operator_propose_time.py`.

**`tools/log_to_solution.py` and `tools/hexaly_log_to_solution.py`.** Benjamin's. They rebuild a
solution file from a run log, re-derive the seed-42 instance, and refuse to write anything that
fails a check. The Hexaly script is a deliberate copy rather than a shared path, because
`log_to_solution.py` belongs to this solver and does not carry Hexaly's cases.

**A documentation freshness pass.** Three top-level docs refreshed, then all 16 design docs verified
against the code and 8 of them rewritten.

### Measured

| | |
|---|---|
| `then()` composition defect, found by the travel work | two removals of 10 and 11 from a load of 75 composed to `(75, 64)`; truth is `(75, 54)` |
| the new sub-chain seam | **0.70 arcs per proposal** |
| travel commit gates | 101 tests, 0 failures; pyright clean; `stress.py` no findings, injection fires on all 24 operators; `compare_deterministic.py dd17a13` IDENTICAL |
| `ReorderShortSpanExactly`, 60 s | 37,901 calls at 41.5 µs mean — **2.6% of wall clock**, against 74% before the scoring rework. 1,201 improving calls, **20/s** against 7.5. 95.9% no-op returns |
| **small family, this solver** | **3381.54** at 180 s, commit `4bd2d15`, 6.0M iterations, 48 plateau reheats — a new record, 79.56 under the previous 3461.10 |
| **small family, Hexaly** | **3355.82**, first reached at **178 s** of a 600 s budget |
| gap on the small family | **0.77%**, at a matched budget |
| CVRPLIB X-instances, 600 s, 5 seeds | **4.32% mean best gap**, 1.96% to 7.82% |
| design docs | 16 read, 7 verified clean, 8 rewritten, 15 stale link labels corrected, `check_links.sh` clean at 60 files, 14 re-verification assertions pass |

**The gap is routing, not vehicle count.** This solver used two vehicles, Hexaly three. Hexaly paid
10 more for the third vehicle and won 35.72 on travel, so the two-vehicle structure is earning its
keep and the whole deficit is routing quality. Benjamin's reading, and it corrects a weaker one
Claude had written into `RESULTS.md` — that the gap was partly which side of a near-balanced term a
search lands on.

### Decided

- **Travel is a delta, not a transition**, at both route and vehicle level. Distance has no step
  function of its own. Benjamin's instruction.
- **Numeric transition fields compose by delta, not by endpoint.** A sink-written base does not move
  when the structure does, so an operator pricing two sub-steps against one route reads the same
  pre-move base twice. Not reachable from today's roster; ruin-and-recreate reaches it immediately.
- **The next destination is vehicle time limits**, which unlocks the MDVRPI benchmark. Benjamin's
  direction, and it retired Claude's "wrong axis" assessment.
- **Superseded design sections get a resolution banner, not deletion.** The old diagnosis is usually
  why the replacement exists.
- **`SimAnn_VRP.py` and `Hexaly_VRP.py` are scratch drivers.** Their values are never a fact to
  cite. Benjamin's rule.

### Fixed

Benjamin fixed both defects Claude surfaced: a duplicate `current_travel` in `Vehicle.__slots__`,
and `ReorderLongRouteByFarthestInsertion` walking every path when the sink-written cache was already
there. He corrected its docstring in the same pass.

### Abandoned

Nothing built and discarded this period.

## 2. Attribution

**Benjamin drove:** the per-route travel design and the delta-not-transition rule; the `__slots__`
refactor; both defect fixes; both new runs and both solution files; the correction that the scoring
section was eleven days stale, supplied with the run data that proved it; the correction that the
repository is published; the direction toward vehicle time limits; the partial-correlation re-check
that caught a claim in `RESULTS.md`; the scratch-driver rule.

**Claude drove:** the travel analysis and build under that design;
`tools/compare_operator_propose_time.py`; both defect diagnoses; the project assessment; the
`README`/`RESULTS`/`METHODOLOGY` refresh; the design-doc verification pass and the eight rewrites.

## 3. What went well

**Benjamin: correcting a stale claim with the measurement attached.** "That is a stale evaluation"
plus 37,901 calls, 41.5 µs, 1,201 improving. The claim was refutable in one step instead of one
round. A correction that carries its own evidence costs a fraction of one that does not.

**Benjamin: re-running the correlation rather than accepting the caveat.** Claude wrote "these two
cannot be separated" and moved on. Benjamin ran the control anyway. The caveat was doing the work a
test should have done.

**Benjamin: saving both new results as re-verifiable files, immediately.** Claude had just flagged
"no routes are saved" as a gap for the reference family. The small-family runs came back with full
provenance in the file itself — budget, first-reached time and iteration, solver commit, run log,
instance descriptor, and a note on what the route order does and does not mean. `first_reached: 178`
is what turned a 3-minute-against-10-minute comparison into a matched-budget one.

**Benjamin: timeboxing the batch-2 questions.** Two open questions, both with stated defaults, both
low-stakes. "Do all 3 batches" was the right call and saved a round trip.

**Claude: measuring the tool before trusting it.** `compare_operator_propose_time.py` leads with a
comparability check on proposal counts and best objective, because two arms that walked different
searches cannot be compared per operator. Follows [[feedback-verify-harness-first]] unprompted.

**Claude: blast radius by index, not by search.** Every blast-radius question in the doc pass was
answered by reading `## References` ∪ `## Links to here`, per
[[feedback-mechanical-tools-over-search]]. No repository search was run for it.

**Claude: a verification script at the end of the doc pass.** Fourteen assertions checked the
rewritten claims against the code, not against memory of the code. That is the habit that should
have opened the assessment rather than closed the pass.

## 4. What we can each learn

### Claude — ranked by time lost

**1. Four wrong claims in the project assessment, all one class.** By far the most expensive item.
It cost a full assessment round and required Benjamin to supply data to correct it.

- "The weighting cannot price rarity against cost" — stale by eleven days. The scoring rework
  shipped the fix on 2026-08-22.
- "Publishing keeps receding" — the repository is public. `git remote -v` was never run.
- "High-quality work on the wrong axis" — the refactor chain is the dependency path to vehicle time
  limits. `_from_advisor/START_HERE.md` names the benchmark and was in the repository.
- "One instance family" — eight measured CVRPLIB comparisons already existed.

Class: **I read the document that describes the code instead of the code, and never checked the
document's date against the commit that last changed what it describes.** `METHODOLOGY.md` already
carries the rule in its measurement form — a measurement is citeable only if its solver version is —
and I applied it to his numbers and not to my own reading. Extends
[[feedback-stop-serial-speculation]], which already says the read IS the measurement for existing
code. The missing half is that a *document about* the code is not that read.

**2. I wrote "these two cannot be separated" instead of running the test.** The two predictors
correlate at +0.94, which I reported. A partial correlation separates them anyway: route length
survives the control at +0.75, instance size flips to −0.58. I had the data in hand.

Class: **stating a confound is not the same as testing it.** Naming a limitation reads like rigor
and can substitute for the two-line calculation that would settle it. Related to
[[feedback-stop-serial-speculation]] — measure, do not narrate — but the failure mode is new,
because the narration was a *caveat*, which is why it passed my own check.

**3. I wrote the retro file before discussing it.** [[feedback-confirm-the-fix-plan]] says docs
raise the bar highest, and [[feedback-assessments-surface-dont-autowrite]] says working-style
observations go to chat for sign-off first. A retro is the clearest instance of both, and I wrote it
straight to disk. Benjamin: *"You messed up the retro. We TALK before making a file."*

**4. I anchored a documentation claim to a scratch toggle.** `RESULTS.md` said the reference family
is "the shape `SimAnn_VRP.py` ships." That file's instance size and capacity are commented
alternatives Benjamin flips per session, so the claim was stale within a day — in the same document
where I had just added a rule about documents going stale.

Class: **a file whose values change per session is not a source of truth.** Same class as
[[project-vrp-reference-instance]]'s existing rule about not taking an instance shape from a tool's
flag list.

**5. I ran neither path for the session logs.** `hiccups.md`, `obstacles.md`, `attributions.md` and
`deviations.md` all end at 2026-08-31, so this retro was reconstructed from the transcript.

There are two paths and both were skipped: live append at the moment of noticing, and the
`context_handoff` skill, which dumps a session into those files wholesale. Claude maintains those
files; Benjamin does not. So this is not a missing mechanism — Claude's first draft of this retro
proposed building one that already exists, which is its own instance of finding 1. It is a
mechanism that was never invoked. Second recurrence with [[feedback-log-session-files-live]] in
place.

### Benjamin

**Small, and named as small.** The two defects Claude surfaced both survived a commit gate. A
duplicate `__slots__` entry and an unused cache are invisible to the test suite, to pyright and to
`stress.py`, because every gate in the routine tests correctness and none tests waste. The
`__slots__` commit's whole purpose was memory layout, and it shipped with a wasted slot per vehicle.

That is a gap in what the gates cover rather than a process failure, and it is the argument for
`tools/compare_operator_propose_time.py` becoming a standing gate rather than a scratch tool.

No premature approval this period. Every go-ahead followed a stated plan and a stated file list.

## 5. Workflow improvements

**Date the evidence before using it.** When a document describes code behavior, check the commit
that last changed that code before citing the document.
`git log -1 --format=%ad -- <file>` against the doc's own date is two seconds.

**Verify first, assess second.** The fourteen-assertion script that closed the doc pass should have
opened the assessment. Any claim about how the solver behaves gets checked against the code before
it is written down, not after it is challenged.

**A stated confound must be tested, or the claim dropped.** Writing "these cannot be separated" is
only honest when separating them is genuinely impossible. If the data is in hand, run the test.

**Run `context_handoff` at the end of a work chunk, not only at a context limit.** The skill exists
and writes the session into `_session/*.md`. Live append remains the supplement, because it catches
what a later dump cannot reconstruct — the option considered and dropped, the surprise, the thing
that was expected.

**Performance gates are missing from the pre-commit routine.** Correctness gates cannot see waste,
and `compare_operator_propose_time.py` is already written for this.

## References

- [2026-08-29_raw_delta_accounting_implementation.md](2026-08-29_raw_delta_accounting_implementation.md) -- the prior retro; its section 6 is where this period starts

## Links to here

*(none yet)*
