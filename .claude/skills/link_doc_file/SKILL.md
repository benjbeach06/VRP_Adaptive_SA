---
name: link_doc_file
description: Reconcile a planning/design doc's doubly-linked References and Links-to-here sections against its body, using tools/link_scan.py, then write brief explanations for whatever changed. Use when asked to "link" a doc file, or after editing a doc's body links. For more than one file, invoke this skill once per file rather than looping inside it.
argument-hint: <file>
---

# link_doc_file

Maintains the doubly-linked reference structure described in
`planning/doubly-linked-references.md`. The mechanical work (finding what changed) is done
entirely by `tools/link_scan.py` — you never grep the repo for backlinks or read a target
file in full to figure out what points where. Your only job is writing the short
explanation clause for whatever the script added, in the style of
`planning/implemented/scoring-rework.md`'s References/Links to here entries
(e.g. `-- the plan that landed first and supplied the sibling-local machinery this one reused`).

**One file per invocation.** If asked to link several files, run this skill once per file —
that keeps each run's context to one file's grep results and one log, rather than
accumulating context across a whole batch.

## Steps

1. Run the script on the target file (the file argument):

   ```bash
   python tools/link_scan.py <file>
   ```

   This is silent on success. If it errors (nonzero exit), stop and report the error —
   do not attempt to fix link problems by hand.

2. Read `_session/link_script_output.md` **in full**. This is the only file you read in
   full during this skill. If it's empty, there was nothing to reconcile: report "no
   changes" and skip to step 6.

3. For each `ADDED | <file> | References | [text](href) -> <target>` line:
   - `grep -n -C 3` the target's filename/basename inside `<file>`'s body (before its
     `## References` heading) to see how and why it's mentioned there.
   - Write one terse clause explaining why `<file>` cites the target — what it needs from
     it, not what the target contains.
   - Apply it: `python tools/link_annotate.py <file> References <href> "<explanation>"`

4. For each `ADDED | <file> | Links to here | [text](href) -> <source>` line (this is the
   reciprocal backlink landing in some other file because the target file references it):
   - Reuse the same grep context you already pulled in step 3 for that relationship —
     don't re-derive it.
   - Write the reciprocal clause, phrased from `<file>`'s perspective: why does *this* file
     care that `<source>` points at it.
   - Apply it: `python tools/link_annotate.py <file> "Links to here" <href> "<explanation>"`

5. For each `REMOVED | ...` line: no explanation needed — the script already deleted the
   entry and its reciprocal backlink. Just note it in your summary to the user.

   For each `SKIPPED-DANGLING | <file> | References | ... target does not exist` line:
   - Use Glob/Grep to locate the likely intended file (renamed or moved without the link
     being updated).
   - Confirm it's the right file using the surrounding body context, not just filename
     similarity.
   - Fix the link's path directly (Edit) at its point of use in `<file>`'s body, and in the
     `## References` entry if one already exists there.
   - Re-run `python tools/link_scan.py <file>` so the fixed link is picked up normally, then
     continue from step 2 with the fresh log.

6. Delete the temp log: `rm -f _session/link_script_output.md`

7. Report a short summary to the user: files touched, references added/removed, and any
   dangling links you repaired (with what you changed them to).

## What NOT to do

- Don't read any file in full except the temp log.
- Don't grep the repo for "who links to this file" — `tools/link_scan.py` and the file's own
  `## Links to here` section already answer that.
- Don't hand-edit `## References` or `## Links to here` content directly — always go through
  `tools/link_annotate.py`, which enforces the section-name allowlist.
- Don't invent an explanation for an entry you don't have grep context for — pull the
  context first.
