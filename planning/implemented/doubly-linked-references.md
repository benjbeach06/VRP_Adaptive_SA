# Every reference is doubly linked

**Status: implemented at commit `e5262c3`.**
Rule agreed 2026-08-22, Benjamin's. Rolled out repo-wide 2026-08-26.

## The problem it solves

Changing a document means finding everything that depends on it. Today that is a guess.

Moving a planning file into `implemented/`, retiring a superseded mechanism, or changing a core
detail all have a blast radius that nobody can enumerate without grepping and hoping. **Grep finds
the link but not the meaning.** A file that links to another usually also SUMMARISES it, and that
summary goes stale silently.

**Blast-radius resolution should be a lookup, not a search.**

## The rule

**Every reference between documents is recorded at both ends.**

Each document carries two sections, at the bottom. (`{...}` stands in for `[...]` below so this
illustration is not itself parsed as a real reference by `tools/link_scan.py`.)

```markdown
## References

- {share_floors.md}(share_floors.md) -- the projection this doc's floors rely on.

## Links to here

- {family_selection.md}(family_selection.md) -- summarises the projection's guarantees.
- {planning/implemented/scoring-rework.md}(../../planning/implemented/scoring-rework.md) -- cites the floor ordering.
```

**`References`** is what this file points at. **`Links to here`** is what points at this file.

**`References` lists DOCUMENTATION only** -- other design and planning docs, `RESULTS.md`,
`METHODOLOGY.md`. Not code, not experiment folders, not run logs. An experiment belongs under a
separate `## Related experiments` heading, which names what was studied and what it informed, and
never restates its result.

**The two sections are maintained in opposite directions.** `References` is derived from the links
in a file's own BODY, and is the only list an author writes by hand. `Links to here` then fills in
as a SIDE EFFECT of other files adding References. Nobody writes a back-link speculatively.

**Links inside the two sections do not themselves count as references.** Only body links do.
Otherwise a back-link would manufacture a forward reference and the two lists would inflate each
other.

Both entries carry a short reason. The reason is the part that makes the section worth having: it
says WHY the other file cares, so a reader can judge whether a change reaches it without opening it.

## Link TEXT is repo-root-relative; the target stays relative

**Unresolved, recorded 2026-08-25. The convention is currently inconsistent and needs a cleanup
pass.**

What a reader sees should locate the file from the repository root, so a path means the same thing
in every document. The link target stays a normal relative path, because that is what resolves.
(`{...}` stands in for `[...]` below for the same reason as above.)

```markdown
{design/operator_selection/share_floors.md}(share_floors.md)
{planning/ablations.md}(../../planning/ablations.md)
```

Not `{share_floors.md}(share_floors.md)`, which reads differently depending on which file it
appears in, and gives a reader no idea where the target lives.

Today some entries use the bare filename and some use the full path, including in docs written
after the rule was agreed. `tools/check_links.sh` does not check display text yet. Both are for the
cleanup pass, not now.

## What it buys

**Editing a file starts by reading both its `Links to here` and its `References`.** Together they
are the blast radius. `Links to here` names the files whose body links here. `References` names the
files this one links to -- and each of those carries a reciprocal `Links to here` entry that points
back, so a move breaks that entry too. Either section alone is half the set.

Any file in either list may hold a summary that the edit invalidates.

This is what makes the moves we already do routine:

| move | resolution |
|---|---|
| plan finished, move to `planning/implemented/` | every entry in `Links to here` AND `References` needs its path updated |
| mechanism superseded | every entry may carry a stale summary of it |
| a core detail changes | entries whose reason mentions that detail are the ones to re-read |

## Scope

**Design, planning, retro, and experiment documents.** `design/**`, `planning/**`, `retros/**`,
`experiment_logs/**`, `RESULTS.md`, `METHODOLOGY.md`, and the folder `README.md` files.

**Not source comments.** A one-line design-doc reference in code stays one line. Source is covered by
the existing rule: a design doc replaces long prose, and the code keeps a pointer.

## Tooling

**Built: `tools/check_links.sh`.** A by-hand back-link rots, so the rule is enforced by a script.

```bash
bash tools/check_links.sh                       # every in-scope doc
bash tools/check_links.sh design/foo.md ...     # just these
```

It does four things:

1. **Derives `References`** from each file's body links, ignoring fenced code blocks so an
   illustrative example is not mistaken for a real reference.
2. **Reports `REF MISSING` / `REF EXTRA`** where the section and the body disagree, and
   `REF NOT A DOC` where a reference points at something that is not documentation.
3. **Reports `BACKLINK GAP`** -- A references B, and B has no `Links to here` entry for A.
4. **Reports `DANGLING`** paths, wherever they appear.

**It reports only, and deliberately has no `--fix`.** A `Links to here` entry carries a REASON, and
a generated reason is worse than a missing one because it reads as verified.

A pre-commit hook is the obvious home once the sections exist more widely.

## Rollout state

Complete. `bash tools/check_links.sh` reports zero problems across every in-scope folder --
`design/**`, `planning/**`, `retros/**`, `experiment_logs/**`, `RESULTS.md`, `METHODOLOGY.md`.

## Cost, stated honestly

**Two edits per new link instead of one.** For a folder the size of `design/operator_selection/`
that is small. It grows with the documentation, which is the point at which a script stops being
optional.

**The reason text is the real cost**, and it is also the whole value. A back-link with no reason
degenerates into what grep already gives.

## Order of work

1. Add both sections to `design/operator_selection/*.md` first. That folder is the most densely
   cross-linked and is where a stale summary does the most damage.
2. Extend to `planning/**` when the `implemented/` folder lands, since that move is the first one the
   rule directly serves.
3. Build `tools/check_links.py` once the sections exist in more than one folder.

## How this diverged, and why

**The tooling is bigger than a checker.** The plan specified reporting only, deliberately with no
`--fix` -- a generated reason reads as verified, which is worse than a missing one. What shipped
keeps that principle for the reason text, but adds mechanical maintenance around it:
`tools/link_scan.py` adds and removes bare `## References`/`## Links to here` entries by diffing
a file's body links against its existing section, and `tools/link_annotate.py` is the one
sanctioned way to then set the reason text on an entry it added. `tools/update_linkages_for_move.py`
rewrites every link a move breaks, using the union of a file's `## Links to here` and its
`## References` as the referrer list -- no repo search -- and refuses to run unless
`check_links.sh` reports the file clean first. The `link_doc_file` and `move_doc_file` skills wrap these for one-file-at-a-
time use. `check_links.sh` (bash, not the `check_links.py` this plan named) stays the read-only
verifier underneath all of it.

**Rollout went wider than planned.** The "Order of work" above stops at `planning/**`. Actual
scope reached every documentation folder, including `experiment_logs/**`, added when a tuning run's
summary doc needed to cite an ablation folder and vice versa.

**The repo-root-relative display text question resolved itself as a side effect.** The plan left it
"Unresolved... needs a cleanup pass" on 2026-08-25. `display_text()`, shared by all three scripts,
now enforces it (bare filename for a sibling, repo-root path otherwise) for anything they touch.
Entries written by hand before the tooling existed were never swept in bulk -- that remains a real,
narrower gap than the plan anticipated, not a solved one.

**No pre-commit hook was built.** The plan floated one as "the obvious home once the sections exist
more widely." The three scripts plus two skills, run per-file through the skill, replaced the need
for one so far.

**A `find_heading` bug was found and fixed during rollout, not before it.** `find_heading` in all
three scripts matched a `## References`/`## Links to here` heading anywhere in a file, including
inside this file's own fenced illustrative examples -- which are literal text showing the section
format. That silently pointed the reconciliation logic at the wrong span on this file specifically.
Fixed by requiring a blank line on both sides of a real heading, plus a fence-skip as a second,
independent guard. A related bug in `link_scan.py` alone -- `body_links()` assumed `## References`
always precedes `## Links to here` in file order, which is false for at least one design doc --
was fixed by masking out both sections by span rather than by a single boundary cut.

## References


## Links to here

- [README.md](README.md) -- cites this feature in the implemented-features index
- [retros/2026-08-26_doc_linking_and_time_robust_tuning.md](../../retros/2026-08-26_doc_linking_and_time_robust_tuning.md) -- retro for the rollout, the find_heading and body_links bugs, and the move here
- [retros/2026-08-27_planning_reorg_and_move_script_fix.md](../../retros/2026-08-27_planning_reorg_and_move_script_fix.md) -- retro for the session that corrected this doc and fixed update_linkages_for_move.py
