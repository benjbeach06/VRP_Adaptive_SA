# Every reference is doubly linked

**Status: rule agreed, tooling not built. Benjamin's, 2026-08-22.**

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
- [planning/scoring-rework.md](../../planning/scoring-rework.md) -- cites the floor ordering.
```

**`References`** is what this file points at. **`Links to here`** is what points at this file.

Both entries carry a short reason. The reason is the part that makes the section worth having: it
says WHY the other file cares, so a reader can judge whether a change reaches it without opening it.

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

## Tooling, when it is worth building

The rule is enforceable by a script, and should be, because a by-hand back-link rots.

`tools/check_links.py`, doing three things:

1. **Parse every markdown link** between tracked documents.
2. **Report asymmetry** -- A references B while B has no `Links to here` entry for A, or the reverse.
3. **Report dangling paths.** The existing check already does this and would fold in.

`--fix` could insert missing `Links to here` entries with a placeholder reason, leaving the reason
for a human. **It must never write a reason**, because an invented reason is worse than a missing
one: it reads as verified.

A pre-commit hook is the obvious home once the sections exist.

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
