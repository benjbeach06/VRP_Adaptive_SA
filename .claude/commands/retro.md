---
description: Summarize work since the last retro, review what both of us did well and can learn, and turn findings into standing rules
argument-hint: "[optional scope, e.g. 'since the tuning run' or a topic]"
---

Run a retro. Scope is `$ARGUMENTS` if given, otherwise everything since the last retro.

## 0. Read `_session/hiccups.md` first

That file is the running log of friction, dead ends and wasted effort, appended as things happened
rather than reconstructed afterwards. Read it before writing anything -- it is the raw material for
sections 3 and 4, and it holds the items that are easiest to forget precisely because they were
resolved.

**Clear it once consumed.** Anything durable graduates to a memory.

## 1. Summarize the work since the last retro

Do this first, and do it properly. It is not a preamble.

Say what was built, what was measured, what was decided, and what was abandoned. Use `git log` for
the commit range. Give the numbers that came out of it.

A reader should be able to see the shape of the period without reading the transcript.

**Include a brief attribution summary.** Say which parts he drove and which parts I drove. Design
calls, corrections that changed direction, and measurements he ran himself all belong to him. Keep
it to a few lines. Do not inflate my share, and do not inflate his.

**This summary is the basis for the commit message.** Write it so it can be cut down into one, then
do that in step 6.

## 2. What went well

**Cover both of us.** A retro that only lists my failures loses half the information.

Name the specific decision or habit that worked, not a general compliment. A confirmed approach is
as reusable as a correction, and it is easier to lose because nothing went wrong to mark it.

## 3. What we can each learn

**Cover both of us here too.** Be direct about mine. Be honest and specific about his, without
padding it.

For each item, name the **class** of the problem, not only the instance. Ask whether an existing
memory already covers that class. If it does, cite it instead of writing a near-duplicate.

Rank by time lost, not by how wrong the mistake was.

## 4. Workflow improvements

The main output. What should change in HOW we work, not in the code.

Look hard for the failures that waste work early, because they are the expensive ones:

- **Work started before a plan was agreed.** Implementation that ran ahead of confirmation.
- **New code that was not verified before it was trusted**, or trusted because a suite passed that
  never covered it.
- **A long or unattended run launched without a preflight**, or without a stated claim scope.
- **An assumption that was never stated**, so neither of us could check it.
- **Re-work.** Anything built twice, or built and discarded.
- **Repeated corrections.** The same instruction given more than once is a workflow defect, not a
  memory defect.

## 5. Then: record it

Promote each finding from instance to class before you write it. A rule that covers only the exact
incident is worth little.

Write or update a memory for each finding that generalizes. Update `MEMORY.md`. Prefer updating an
existing memory over creating a near-duplicate.

Say plainly which memories you wrote and what changed.

## 6. Commit

Write a **brief** commit message from the summary in step 1.

**ENUMERATE what landed.** One line each, grouped by area. A commit message is a manifest, not an
argument for it.

**SEPARATE ADDS FROM FIXES.** A reader needs to know whether a line is new capability or repaired
behavior; without the distinction the message gives no context. Group them, or mark each line.

**LINK TO FILES, NOT FOLDERS.** `design/x/y.md`, never `design/x/`. A folder link makes the reader
search.

**GROUP FEATURES UNDER THE DESIGN DOC, not the reference under each feature.** When two or more
lines share a doc, name the doc once as a heading and list them beneath it. Repeating the same path
three times is noise. A single item keeps its reference inline.

**IMPETUS BELONGS IN DESIGN DOCS.** Do not explain why a mechanism exists or what it measured. Link
the design doc and let it carry the reasoning.

Include one short line of attribution.

Brief means brief. His own messages are one line plus a short parenthetical. Mine run far too long.
Match his.

Show him the message before you commit.

## Style

Be concrete. Quote what he actually said when it is the clearest statement of a rule.

Do not pad. Do not apologize repeatedly. State the finding, state the rule, move on.

ASD-STE100 Simplified Technical English. Short active sentences. One idea each. See memory
`feedback-use-simplified-technical-english`.
