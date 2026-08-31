# Retro — raw-delta accounting, implementation (steps 0–5)

Covers 2026-08-28 to 2026-08-29. The previous retro,
[2026-08-27_raw_delta_accounting_plan.md](2026-08-27_raw_delta_accounting_plan.md), covered the
plan. This one covers building it.

## 1. What happened

**12 commits on `raw-delta-accounting`**, plus steps 2, 3 and 5 still in the working tree.

### Built

Step 0, plumbing and detectors, 12 commits, green at each one:
- `RawDeltaRecord` with `.then()` composition, `AccountingRecord`,
  `FullSolution.apply_accounting` as the single sink.
- `SimAnn_VRP_Accounting.py` — the processor, in its own file, so the core model never imports it.
- `Move` gained two independent bits, `already_applied` and `accounting_applied`.
  `Operator._account`/`_unaccount` at all four apply/revert gates.
- Three new oracles: per-vehicle counter truth, `vehicle.routes` chain membership, and the
  raw-record oracle in two halves — claim and completeness.
- `tools/compare_deterministic.py`, a fixed-iteration cross-commit equivalence gate.

Steps 1 through 5 moved each objective term from the L3 aggregators into the processor:
`travel_distance`, then `total_route_overload`, then the three coupled activation terms together.
Step 5 deleted the dual return; every aggregator now returns a bare `RawDeltaRecord`.

Mid-flight, the record was reshaped from one `RouteDelta` per route to four per-field maps, and the
accounting record was rebuilt around plain deltas.

### Measured

| | |
|---|---|
| by-applying path | **14 / 180** actionable moves arrive already applied (~8%), all PermuteChain-based |
| final suite | **98 tests, 1 failure**, ~18s. Was 55 before the refactor. |
| pyright | **0 errors, 0 warnings** |
| `stress.py` | **NO FINDINGS** — 24 operators, 43,499 probes, 95 episodes |
| `stress.py --inject-delta 0.5` | **detector fires** — travel_distance findings on every operator |
| `compare_deterministic.py 4cbb636` | **DIFFERS**, +2.780127292 on best, `fingerprint` moved |
| post-build state, both trees | **byte-identical** — depot order, loads, all vehicle counters |

The one remaining test failure is `DepotUsageOrderAcrossRevert`, which now fails by design.

### Decided

All of these are Benjamin's calls:

- The record carries **four per-field maps**, not one struct per route. Absence means unchanged.
- **Every accounting update is a plain delta.** Applying adds it, reverting subtracts it. No inverse
  built at apply time, no positions, no ordering.
- **Core performance is never traded for determinism.** Stated as an absolute.
- `start_depot_changes` **passes through raw** to the sink, which skips virtual depots on both the
  remove and the add pass.
- **A virtual depot at either end means the route counts against no depot there.** Making that a
  property of the record removed all activity logic from the sink.
- Accounting happens at **construction**, never at route initialization. `shore_up_accounting()`
  sits at the END of a build, so the build owns the call rather than the caller.
- Depot membership is checked by **symmetric difference**, not by comparing sorted representations.

### Abandoned

- `DepotStartChange` and its `position` field, the inverse built during apply, the ordered `touched`
  pass in the processor, and the test that policed all of it. Every piece existed to preserve
  RouteSet ordering across revert.
- The `DepotUsageAccounting` test class, 3 tests — obsolete once mutators stopped accounting.
- Three `AccountingApplication` tests covering position restore and last-first undo.

### Attribution

**Benjamin drove:** the per-field reshape, the delta-only accounting rule, the
performance-over-determinism rule, the depot pass-through and virtual-marker design, the
`shore_up_accounting` placement, and the final processor. He fixed the overload sign inversion and
the wrong-map write himself, wrote the `for_customers_changing` activity-crossing fix, and replaced
the sorted-representation invariant check with symmetric difference.

**Claude drove:** step 0's plumbing and its three oracles, `compare_deterministic.py`, steps 1 and
2, the first step-3 processor (since rewritten), `shore_up_accounting`'s body, the oracle
corrections, and the diagnoses — the insert-guard mismatch, the overload sign flip, the wrong-map
write, and the emptying-route depot gap.

## 2. What went well

**Building the detector before the conversion.** The two-half raw-record oracle was written in step
0, before any aggregator produced a real record. It later caught the `cost_deltas_if_inserted_before`
guard mismatch and the emptying-route gap, both as exact one-line findings. Neither was visible in
the objective.

**Constructing the failing case instead of arguing it.** The insert guard went from "this looks
wrong" to a reproducible oracle finding in a single probe. That is what made it actionable rather
than a suggestion.

**Splitting the sweep by adjacency before reporting.** A first pass reported ~90 findings. Bucketing
by adjacency showed 0/54 non-adjacent, 0/54 the other direction, and 48/54 in a configuration the
operator rejects as INVALID. All 90 were the harness. That check ran before the report, not after.

**Benjamin: attacking the premise instead of the number.** "I don't see why accounting order matters
at all. It's all aggregate. Why did you put ordered machinery in there for something by nature
unordered?" — that is a better question than "can this be made faster", and it deleted a whole
subsystem rather than optimizing it.

**Benjamin: collapsing a two-part proposal into one call site.** I proposed a shore-up at the start
of `solve()`, then proposed a second patch to fix the `best_objective` ordering trap that created.
He asked "if make_initial_solution ends with setting the best objective, then why the heck can't we
just do the accounting right before the line is called?" and the whole complication vanished.

**Benjamin: fixing from a line-level report rather than round-tripping.** Two processor bugs were
reported with file, line and reasoning; he fixed both directly. That was faster than handing them
back.

## 3. What we can each learn

### Claude — ranked by time lost

**1. I built determinism machinery into the hot pricing path.** By far the most expensive item. It
produced `DepotStartChange.position`, an inverse built during apply, an ordered `touched` pass, a
test to police the ordering, and a determinism-gate divergence that then needed its own
investigation. All of it was deleted.

The memory `feedback-determinism-costs-nothing` already says determinism is for correctness, not
performance, and must never cost more than nominal per call. It existed and did not stop me.

Class: **I treated a testing property as a design requirement.** The missing test is whether the
mechanism serves the solver or serves the test suite. Ordering served only the suite.

**2. I did not check the design against his stated constraint.** He said at the start that
accounting updates are simple deltas — apply adds, revert subtracts. I then built an absolute-valued
`RouteLoadChange`, a membership changeset with a direction flag, and an inverse record. I even wrote
a docstring justifying why loads were "an ABSOLUTE value, not a delta, unlike VehicleCounterChange"
— documenting the deviation instead of treating it as a warning.

Class: **a constraint stated once at the start does not survive into detailed design unless
something re-checks it there.** Writing a comment that explains why my design differs from his rule
is the signal that I have drifted.

**3. I read aggregate counts from a harness I had not validated.** The sweep drove
`link_to_vehicle_before` on pairs where it is a documented no-op, while the aggregator priced a
swap. `feedback-verify-harness-first` covers proving a detector fires; it does not cover proving the
detector is pointed at the right thing. Caught before it reached him, but only just.

**4. I dropped a guard while generalizing a function.** The processor used `VirtualDepot` as a dict
key. `FirstRouteVisit.replace_depot` had skipped virtual depots on both sides; I carried across its
arithmetic and not its guards. It raised rather than miscounted only because `VirtualDepot` is
unhashable.

**5. I scripted an identical edit across five call sites and broke three.** Three of the five used
`DirectOperator`, the wrapper, which already accounts — so those double-applied. Only one failed
loudly.

Class for 4 and 5 together: **I apply a transformation uniformly and check for exceptions
afterwards.** The discriminating condition belongs in the transformation.

**6. Two tool-usage errors.** A `grep -rn` without `--include` scanned both venvs and returned ~200
irrelevant lines. `stress.py --inject-delta 0.5` ran without `--out` and overwrote
`tools/stress_results.json`, a tracked file, with corrupt-by-design data.

### Benjamin

**1. Deleting step-3 mutator code during step 2 left two sessions of work unverifiable.** He
self-reported it. `swap_demand_from_route` and its call sites went before the sink could write
`current_load`, so the tree sat at 11 failures and `compare_deterministic.py` could not run at all.
The per-field reshape and step 2 both landed with no gate behind them.

Class: **a strip that outruns its replacement removes the gate that would have caught it.** Cost was
not the failures themselves — it was that nothing could be verified while they stood.

**2. Minor, and already acknowledged.** The `for_customers_changing` docstring still says "Start
depot and vehicle hold, so those maps stay empty", and the invariant check still carries the comment
explaining the sorted comparison it replaced. He has said he will maintain them.

## 4. Workflow improvements

**Re-read his stated constraints at design time, not only at instruction time.** The delta rule was
given up front and violated three ways. Nothing in the process re-checked the design against it.

**A design choice with a per-call cost needs that cost written down.** I never stated what the
ordered machinery cost per proposal. Had I written "this runs on every proposal, including the ~90%
rejected", the question would have answered itself.

**Validate a throwaway harness against the thing it grades before reading its output.** Proving the
detector fires is not enough. The mutation has to be the one the priced record describes.

**Do not strip a cache until its replacement writer lands in the same change.** This is the shape
behind both his hiccup and the load-mutator breakage.

## 5. Open at the end of this period

- `compare_deterministic.py 4cbb636` DIFFERS. The build is byte-identical and `stress.py` finds no
  pricing error, so the suspect is the apply/revert ordering that step 3 deliberately stopped
  preserving. Analysis and the confirming experiment are in `_session/obstacles.md`.
- `DepotUsageOrderAcrossRevert` fails by design and wants either the `@expectedFailure` decorator
  back or deletion. *(Resolved 2026-08-31: deleted -- see section 6.)*
- Step 4, end-depot usage tracking, is not started. *(2026-08-31: deferred, moved to
  `planning/core-refactors/route-distance-tracking.md`.)*
- No performance measurement yet. The dual return is gone, so it is finally measurable.

## 6. Finalization (2026-08-31)

Covers the wrap-up and `/report_design` on the same refactor. No new solver logic.

### Done

- **Deferred step 4** (end-depot usage tracking). Moved to
  [route-distance-tracking.md](../planning/core-refactors/route-distance-tracking.md).
- **Deleted `DepotUsageOrderAcrossRevert`** and its dead imports. Fixed stale prose in
  `tools/compare_deterministic.py` and `tests/test_raw_delta_record.py` that still said step 3
  would carry a removal position.
- **Moved the plan** to
  [planning/implemented/raw-delta-accounting.md](../planning/implemented/raw-delta-accounting.md)
  via the move tooling, with an `IMPLEMENTED` banner and a `## How this diverged, and why` section.
  Blast radius: `planning/README.md`, `planning/implemented/README.md`, `route-distance-tracking.md`.
  Deleted the refactor guide.
- **Renamed** `shore_up_accounting` -> `initialize_accounting` (5 files).
- **Wrote** [design/raw_delta_accounting/README.md](../design/raw_delta_accounting/README.md) plus
  `raw_delta_record.md`, `processor.md`, `accounting_record.md`,
  `tracking_for_cached_accounting.md`. Indexed in `design/README.md`.
- **Thinned** the long design-argument docstrings in `SimAnn_VRP_Accounting.py`,
  `SimAnn_VRP_Core_Model.py`, `SimAnn_VRP_Operators.py` to a summary plus a design-doc link.
- Fixed the missing doubly-links on this retro -- see the learning below.

Suite 97 / 1 skip. `check_links.sh` clean.

### What went well

- I surfaced that design docs were premature -- the refactor is uncommitted and its settled
  decisions live in the uncommitted steps -- rather than only complying or only proceeding.
  Benjamin overrode with context I did not have (step 4 deferred, treat it as landed).
- Adopted the move tooling for untracked doc renames as soon as Benjamin noted it "saves work even
  when things aren't formalized".
- `_session/report_design_progress.md` stayed current through four review rounds, so handoff state
  was always accurate.
- Benjamin's design-doc review was thorough with low noise: every nit traced to a standard, and
  non-issues were waved through explicitly.

### What Claude can learn -- ranked by time lost

1. **First design-doc draft carried decision-history narration, a verbatim chat quote, and
   test-framing.** Benjamin cut a whole section that quoted him and narrated a rejected
   alternative, plus "import direction is a completion check". Class: a design doc states what is;
   history, rejected alternatives and quotes belong here in the retro.
   [[feedback-design-docs-state-what-is]] updated with the specifics.
2. **Exact code identifiers scattered through the docs.** Names only where they define a record's
   fields or a sentinel. `depot_activation_delta_from_depot_num_usage_deltas` was in the draft and
   the method was deleted the same session.
3. **The doc set was restructured about three times** because prose was written before the file
   list was agreed. Class: doc structure is part of the plan; agree it, then draft.
   [[feedback-confirm-the-fix-plan]].
4. **The processor tables were reworked four times.** Deleted a table Benjamin valued, then
   under-specified its replacement (missed vehicle reassignment as an input). Same class as 3.
5. **This retro file was created last session without reconciling its doubly-links.** Benjamin
   noticed a session later. Class: creating or editing a doc is not done until the link tooling
   has run over it. The retro workflow skipped it; it now runs the tooling.

### What Benjamin can learn

Small, and named as small. The processor accounting-record table churned about four edits because
two passes disagreed: one round said the table duplicated `accounting_record.md` and had it cut to
prose, a later round read it as a different perspective and had it restored, then reshaped. The
table's heading already framed it as "how the processor derives them". Cost was minor -- a handful
of short edits on one table.

No skill or tool would have shortened the work he did. No premature "go" -- every approval followed
a stated plan.

The earlier framing that review "arrived across four rounds" as a fault is retracted: iterative
review is the process working. But the search for his side is done each retro, per
[[feedback-retro-procedure]], not skipped.

### Workflow improvements

- Multi-doc deliverable: agree the file list and per-file scope before writing prose.
- Read the full [[feedback-design-docs-state-what-is]] checklist before the first draft; extend it
  when a review adds a class.
- Doc creation ends with the link tooling. Retros included.
- Retro language: say "built" vs "committed" precisely. This retro's section 1 said steps 2/3/5
  were "done"; they were built, not committed, which is why they land in the same commit as the
  finalization.

## References

- [2026-08-27_raw_delta_accounting_plan.md](2026-08-27_raw_delta_accounting_plan.md) -- the prior retro; it covered planning the refactor, this one covers building it
- [design/raw_delta_accounting/README.md](../design/raw_delta_accounting/README.md) -- the design docs written in the finalization section
- [planning/core-refactors/route-distance-tracking.md](../planning/core-refactors/route-distance-tracking.md) -- carries deferred step 4 and the distance work this refactor unblocks
- [planning/implemented/raw-delta-accounting.md](../planning/implemented/raw-delta-accounting.md) -- the plan, moved to implemented in the finalization

## Links to here

- [planning/implemented/raw-delta-accounting.md](../planning/implemented/raw-delta-accounting.md) -- the plan this session implemented; its divergence section points back here for the why
