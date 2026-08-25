# Every reference is doubly linked

**Status: rule agreed. Checker BUILT (`tools/check_links.sh`); rollout in progress.**
Benjamin's, 2026-08-22.

## The problem it solves

Changing a document means finding everything that depends on it. Today that is a guess.

Moving a planning file into `implemented/`, retiring a superseded mechanism, or changing a core
detail all have a blast radius that nobody can enumerate without grepping and hoping. **Grep finds
the link but not the meaning.** A file that links to another usually also SUMMARISES it, and that
summary goes stale silently.

**Blast-radius resolution should be a lookup, not a search.**

## The rule

**Every reference between documents is recorded at both ends.**

Each document carries two sections, at the bottom:

```markdown
## References

- [share_floors.md](share_floors.md) -- the projection this doc's floors rely on.

## Links to here

- [family_selection.md](family_selection.md) -- summarises the projection's guarantees.
- [planning/implemented/scoring-rework.md](../../planning/implemented/scoring-rework.md) -- cites the floor ordering.
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

```markdown
[design/operator_selection/share_floors.md](share_floors.md)
[planning/ablations.md](../../planning/ablations.md)
```

Not `[share_floors.md](share_floors.md)`, which reads differently depending on which file it
appears in, and gives a reader no idea where the target lives.

Today some entries use the bare filename and some use the full path, including in docs written
after the rule was agreed. `tools/check_links.sh` does not check display text yet. Both are for the
cleanup pass, not now.

## What it buys

**Editing a file starts by reading its `Links to here`.** That list is the blast radius. Anything
listed there may hold a summary that the edit invalidates.

This is what makes the moves we already do routine:

| move | resolution |
|---|---|
| plan finished, move to `planning/implemented/` | every entry in `Links to here` needs its path updated |
| mechanism superseded | every entry may carry a stale summary of it |
| a core detail changes | entries whose reason mentions that detail are the ones to re-read |

## Scope

**Design and planning documents.** `design/**`, `planning/**`, `RESULTS.md`, `METHODOLOGY.md`, and
the folder `README.md` files.

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

As of 2026-08-23 the checker reports over 200 problems, almost all from the 32 docs that predate
the rule and carry no `References` section at all. That is expected, not a regression: the sections
are being added folder by folder, in the order below.

**Done:** the five docs from the scoring rework and the time-based schedule, plus everything they
link to. Verified with `bash tools/check_links.sh <those five>`.

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

## References

- [operator-selection.md](operator-selection.md) -- the hub whose entries carry summaries of the
  files they link, and so is the first place a stale summary appears.

## Links to here

*(none yet -- this file is new)*
