# 2026-09-04 — The vehicle duration objective

Covers everything after `70bb360`. One feature, two plan migrations, and a first design doc for the
objective itself.

## What happened

### The plan was already built

The session opened with a request to implement route distance tracking.
[route-distance-tracking](../planning/implemented/route-distance-tracking.md) said
**"Status: not started"**. Every item in
it was already live in the code, landed in `6df59e0`.

The status line had survived the 2026-09-02 doc-freshness pass, which refreshed `design/` against
the code but never touched the `planning/` status headers. Reading the code before building cost
about six tool calls. Building it again would have cost the session.

The real ask was the downstream plan,
[vehicle-time-limits](../planning/implemented/vehicle-time-limits.md).

### The duration objective

A vehicle accrues duration from distance travelled, customers served, and active routes run. Four
bands price it. `ObjectiveTermDelta` went from five terms to nine.

**The finding that set the size of the work:** all three duration inputs already existed as
sink-written per-vehicle caches, each with a per-vehicle delta the accounting processor already
built. So neither the raw record nor the accounting record gained a field. The whole feature is
arithmetic over deltas that were already there.

That was only true because of a deviation from the plan. The plan said "routes run" is the length
of the vehicle's route list. It became the ACTIVE route count instead — an empty route is a
modelling artifact and no vehicle was loaded for it. Benjamin: *"Matches intent. Counting only
active 'loading' depots."* The alternative reading would have needed a new cache, a new record
field, a new oracle, and a new completeness case, because `len(vehicle.routes)` is live off the
structure and reads post-mutation for the two `_evaluates_by_applying` operators.

### Numbers

| check | result |
|---|---|
| pyright | 0 errors, 0 warnings |
| tests | 101 → 121, 1 skipped, 0 failures |
| `compare_deterministic.py 70bb360` | `IDENTICAL` on all four fields |
| `tools/stress.py` | clean to 792,398 probes |
| `check_links.sh` | clean, 63 files |
| fault injections | 4, all caught |

The objective is off by default, which is why the determinism gate passes.

### Docs

Two plans moved into `planning/implemented/` and had their bodies rewritten to state what shipped.
A new plan,
[end-depot-usage-tracking](../planning/core-refactors/end-depot-usage-tracking.md), carries forward
the one piece route-distance-tracking had been holding.
[design/objective/objective_terms.md](../design/objective/objective_terms.md) is new and covers the
whole objective, not only duration. [RESULTS.md](../RESULTS.md)'s MDVRPI claim was corrected: the
blocker is gone, the run is still owed.

## Attribution

**Benjamin** set the shape of the objective. Four bands rather than the plan's two-part overload
mirror. The `-1`-means-unspecified convention on the setter. The $1000 default when a legal limit is
stated. The 10x excess rate and its fallback to the hourly rate. Overtime continuing to accrue past
the limit. The names `time_limit` and `overtime_threshold`. He approved both deviations, and he
restructured the design doc after first draft — splitting it into core objective and feasibility
penalties, and adding the domain motivation the mechanism alone does not carry.

**Claude** found the stale status, found that the three inputs already existed as caches, proposed
the active-route reading and the derived-not-cached duration, caught a determinism hazard before it
shipped, and wrote the code, the tests and the fault injections.

## What went well

**Benjamin attacked the premise of a binary question.** The question offered two options: cap the
overtime band at the legal limit, or leave it uncapped. He answered with a band that was in
neither — *"why not allow a steeper gradient rate after legal limit, defaulting to 10x the unit
cost."* The two-option frame was too narrow and he did not accept it. The resulting model prices a
violating hour at 11x a legal one while keeping the objective sloped.

**Benjamin restructured the design doc himself instead of round-tripping.** The first draft had
three groupings that repeated each other. Returning that as a list of edits would have cost two
turns and probably still missed the reorganization.

**Stopping to report rather than building.** The stale status was found by reading the code before
writing any.

**Fault injection before trusting a passing test.** The four duration terms are zero in every other
test in the operator-contract suite, so `test_contract_with_vehicle_duration_objective` passing
proved nothing on its own. Four injections — one per duration input, plus the active-route
reading — confirmed each detector fires.

## What we can learn

### Claude

**1. Asserting an absence in a document without reading it closely enough.**

After the design doc was rewritten, two comment blocks in the code looked like the only record of
their reasoning, and both were raised before cutting them. One of those was wrong. The rewritten
doc already said it: *"Conversely, if any input is nonzero, the true duration is computed and
reported — even in the absence of associated costs and bounds."* That covers exactly what the
comment argued.

The class is narrow and does not need a rule: **when claiming a document does not state something,
the claim needs the same care as a claim about code.** The second question, about a determinism
hazard genuinely absent from the doc, was legitimate and was answered as such.

**2. Running a whole-repo verification at per-file frequency.** `check_links.sh` with no arguments
scans every doc in the repo. It ran three times before Benjamin stopped it: *"Only run the global
check_links.sh tool at the very end of the report-design phase; it takes too long to run it
repeatedly."* The per-file form was available throughout and was used inconsistently.

Recorded in the memory `project-doc-linking-tooling`.

**3. Session files written in one batch at the end.** `deviations.md`, `design_changes.md` and
`attributions.md` were all written — in a single pass near the end of the code work. `hiccups.md`
got nothing, for the second period running.

**A batch written at the end is a reconstruction**, so it holds what survived into the summary
rather than what was noticed at the time. Writing three of four files late is not partial credit.
Recorded in `feedback-log-session-files-live`, which already covered the class and now carries the
form that looks like compliance.

### Benjamin

**The four-band specification arrived in fragments, and two of them read as contradictory.** Across
four messages: a steeper gradient past the legal limit, then *"keep pricing overtime at same rate
after exceeding limit too."* Read separately those are a cap and a no-cap. They reconcile only once
the bands are understood as additive rather than exclusive.

It was resolved by inference rather than by asking, which is where a wrong reading would have gone
unnoticed. Small — each fragment individually saved time over writing one long specification up
front, and the redirects throughout the session were fast and prevented waste.

## Memories

| memory | change |
|---|---|
| `project-doc-linking-tooling` | Added: `check_links.sh` with no arguments is a whole-repo run and is slow. Once, at the end; per-file during the work. |
| `feedback-log-session-files-live` | Added the 2026-09-04 recurrence: a batch written at the end is the same defect as writing nothing. |

No new memory files, and none written for finding 1 — the incident was a single misreading, not a
class worth a standing rule.

## References

- [design/objective/objective_terms.md](../design/objective/objective_terms.md) -- the design doc this period produced, covering the whole objective rather than only duration
- [planning/core-refactors/end-depot-usage-tracking.md](../planning/core-refactors/end-depot-usage-tracking.md) -- the plan split out of route-distance-tracking during this period, so the implemented doc states only what is
- [planning/implemented/vehicle-time-limits.md](../planning/implemented/vehicle-time-limits.md) -- the plan that landed this period; the retro covers how it was built
- [planning/implemented/route-distance-tracking.md](../planning/implemented/route-distance-tracking.md) -- found already implemented at the start of this period, with a stale status header
- [RESULTS.md](../RESULTS.md) -- its MDVRPI claim was corrected this period: the blocker is gone, the run is still owed

## Links to here

- [planning/implemented/vehicle-time-limits.md](../planning/implemented/vehicle-time-limits.md) -- the plan this retro covers; it points here for the session narrative
