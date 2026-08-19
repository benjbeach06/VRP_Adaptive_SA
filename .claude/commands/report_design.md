---
description: Write or update design docs for solver code changed since the last report, verifying each one with Benjamin
argument-hint: "[optional scope, e.g. a feature name or 'since last commit']"
---

Report the design of solver code written since the last design report. Scope is `$ARGUMENTS` if
given.

**Run this BEFORE `/retro`.** The retro covers how we worked. This covers what we built and why.

## Scope

**Solver code only.** `SimAnn_VRP_*.py` and the helpers they use. Not tests, not `tools/`, not
scratch scripts.

Cover what changed since the last design report. Use `git log` and the mtimes in `design/` to find
the boundary.

## Where docs live

```
design/<feature>/          one folder per feature area
```

The target structure is one folder per **BL operator**, and inside it a folder per `Operator` class
that uses it, when there is more than one. Migrate toward that as more of the code is covered. Do
not restructure existing folders without asking.

## A bugfix is NOT a design doc

**Design docs record established design and future direction. They do not track past defects.**

A bug that was found and fixed belongs in the commit message, or in bug tracking.

A defect earns a mention only if it passes all three:

- **It is a DESIGN defect, not a code bug.** The design was wrong, not its implementation.
- **It reached a commit.** Anything fixed before the first commit never existed in the repo.
- **It blocked effective use.** A tuned constant does not qualify. A mechanism that could not work
  does.

Then write the DECISION it forced, not the incident.

Corollary: never open a design folder for a feature area just because a bug was found there. A
design doc for an operator covers **the whole operator**. If there is no appetite for that scope
right now, write nothing and say so.

## Migrate finished planning docs into design

**When a planning item is DONE, it stops being a plan and becomes a design.** Move it -- unless it
was a defect, in which case see above: it just goes away.

For each `planning/` item completed since the last report, decide:

- Does it belong in an existing design doc, or does it stand alone?
- Which design docs should link to it, and which should it link back to?

Then move the durable content across, and remove the planning file. Keep only what a reader needs
now -- a plan argues for doing something, a design records what was done and why.

Ask before moving anything whose placement is not obvious.

## What a design doc contains

- **What the code does**, briefly. Not a line-by-line description.
- **Why it is built this way**, including alternatives that were rejected and the reason.
- **Decisions and their evidence.** A measured number beats an argument.
- **Known costs accepted on purpose**, and what would fix them later.
- **A design defect, only if it forced a decision that still stands.** See the bar below.

Do NOT restate the code. If a reader could get it from the source in ten seconds, leave it out.

## Cross-linking

Design docs link **both ways**. A helper's doc links to every operator that uses it. Each of those
operators links back to the helper.

Link to `planning/` for deferred work, and to `RESULTS.md` for measurements. Do not copy numbers
that live in `RESULTS.md` -- cite them.

## Then: thin the code comments — ONLY for the code this report covers

A design doc **replaces** long prose comments in the source. Once a decision is written down here,
cut it from the code and leave a one-line reference.

**Do not mass-migrate.** Touch only the code this report documents. Long prose elsewhere stays
until a report covers it. A sweeping comment migration is a separate job and needs its own
approval.

```python
# Farthest insertion, not nearest neighbour. See design/furthest_distance/.
```

Keep short comments that explain a non-obvious line. Remove the paragraphs that argue a design.

## Verification

**Verify EVERY design file with Benjamin, one at a time.** Do not batch them and do not assume
agreement.

For each file: say what it claims, name anything you are unsure of, and wait. A design doc that
records a decision he did not make is worse than no doc.

## Style

ASD-STE100 Simplified Technical English. Short active sentences. One idea each. See memory
`feedback-use-simplified-technical-english`.
