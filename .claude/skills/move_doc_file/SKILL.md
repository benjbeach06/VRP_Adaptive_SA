---
name: move_doc_file
description: Move a planning/design doc to a new path, correcting every link that has to change (the file's own outgoing links, and every backlink from files that reference it) via tools/update_linkages_for_move.py. Use when asked to move, rename, or relocate a doc file.
argument-hint: <source> <target>
---

# move_doc_file

Runs `tools/update_linkages_for_move.py <source> <target>`. The script does everything:
rewrites the moving file's own links (body, References, Links to here) against its new
directory, rewrites the matching link in every file listed in its Links to here section, and
moves the file (`git mv` if tracked, a plain rename otherwise).

## Steps

1. Run:

   ```bash
   python tools/update_linkages_for_move.py <source> <target>
   ```

2. If it exits nonzero, report the error to the user and stop. The two expected failure
   modes:
   - `<source>` has no `## Links to here` section yet — run the `link_doc_file` skill on
     it first so its backlink list is known, rather than searching for one.
   - `<target>` already exists.
3. On success (silent, exit 0), report the move to the user: old path, new path, and how
   many referencing files had their backlink rewritten (count the entries in `<source>`'s
   `## Links to here` section before the move).

## What NOT to do

- Don't grep the repo for other files that might reference `<source>` — the script trusts
  its `## Links to here` section completely, by design, so there's nothing to double-check.
- Don't hand-edit any paths this script already touched.
- Don't read the full contents of `<source>` or any referencing file — the script reports
  success/failure; there's nothing left to verify by reading.
