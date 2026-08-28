# Retro — 2026-08-27, planning/ reorganization and the move-script fix

Scope: everything since commit `7a721f9` (the raw-delta accounting plan retro). All uncommitted at
retro time. No solver code.

## What happened

**Reorganized `planning/`.** 20 flat plan files moved into 5 themed subfolders:

| folder | count | holds |
|---|---|---|
| `core-refactors/` | 6 | internal restructuring, no new solver behavior |
| `problem-model/` | 3 | extends what the solver can represent |
| `operator-selection/` | 5 | the hub and its mechanisms |
| `search-methods/` | 3 | new algorithms and neighbor machinery |
| `experiments/` | 3 | measurement and tuning |

`README.md`, `_analogies.md`, `implemented/`, and the raw-delta `.txt` guide stayed at root. The
README roadmap became 5 per-folder tables under `## Roadmap, by folder`.

**Built `tools/update_all_linkages_and_move.py`.** A batch wrapper over
`update_linkages_for_move.py`. Reads a moves file, pre-flights the whole batch while the tree is
clean (every source exists, every target free, no path listed twice, `check_links.sh` clean on all
sources), then runs one core move per line. Stops on first failure with an applied / not-run
report.

**Fixed `tools/update_linkages_for_move.py`.** The first batch run crashed at move 3 of 20. The
script built its referrer list from the moved file's `## Links to here` only. That section names
files whose *body* links here. It never names a file the moved doc points at -- and each of those
holds a reciprocal backlink in its own `## Links to here`. Two changes: stage 0 runs
`check_links.sh <source>` and aborts on any report; stage 1 referrer set widened to
`## Links to here` ∪ `## References`.

**Updated `planning/implemented/doubly-linked-references.md`.** The doctrine said the blast radius
of a file is its `## Links to here`. Corrected to the union with `## References`.

**Numbers.** First run: 2 of 20 moves applied, then crash, then surgical rollback to HEAD. Second
run after the fix: 20 of 20 applied. `check_links.sh` clean, 53 files repo-wide. Backlinks updated
in `design/**`, `RESULTS.md`, `experiment_logs/**`, `retros/**`.

### Attribution

- **Benjamin.** Requested the reorg as a proposal first, no action. Directed the wrapper. Rejected
  my first framing of the crash as a data problem: "the move script is WRONG if it's leaving
  dangling links." Directed the rollback. Gave the 4-stage algorithm the script must follow. Made
  the attribution call on the original bug: neither of us followed the `## References` side in the
  script's first session, weighted to him.
- **Claude.** Wrote the proposal, both scripts, and the README regrouping. After Benjamin's
  pushback, produced the correct diagnosis -- the referrer set must include `## References`,
  because each entry there holds a reciprocal backlink -- and verified it against
  `check_links.sh`'s `BACKLINK GAP` check. Implemented the fix and the pre-flight. Tested
  pre-flight by import so the real run stayed gated.

## What went well

- **Benjamin attacked the premise, not the symptom.** I framed the dangling links as an inherent
  "limitation" with a "precondition." He rejected the frame outright. He was right. The wrapper
  would have shipped over a broken core. This is the trait in `user-benjamin-beach` -- "attacks
  the premise not the number."
- **Claude recovered to the right diagnosis under pushback.** The first framing was wrong. The
  second -- referrer set is `## Links to here` ∪ `## References` -- was correct, specific, and
  checked against the spec's own `BACKLINK GAP` rule before being acted on.
- **Benjamin gave the algorithm as numbered stages.** Not "fix the bug." Four explicit stages with
  the data each reads. The fix was then unambiguous.
- **Claude stopped after the crash instead of forward-fixing.** Captured the full diff to
  scratchpad before the rollback. The rollback was surgical and preserved an unrelated
  pre-existing `.gitignore` edit.

## What we can each learn

### Claude

**1. Built and ran the wrapper before verifying the core it depends on.** (most time lost -- one
crash-and-rollback cycle) Class: trusting existing code on a path never exercised.
`project-vrp-refactor-scope-creep` already states it -- "expect latent bugs in first-exercised
paths." The move script's `## References`-side referrer logic had never run on a real file with
that link shape. One hand-run move of one such file would have exposed it before the wrapper
existed. `feedback-verify-harness-first` covers the principle for new harnesses; extended this
retro to an existing tool about to be batched.

**2. Called a defect a "limitation."** Class: mislabeling a bug as a constraint.
`feedback-addition-vs-defect-framing` covers the opposite error -- over-calling "bug." Same
underlying fault: not checking the code against its stated intent before naming the result.
Extended that memory with the reverse direction.

**3. Diagnosed the crash wrong on the first pass** -- "asymmetric backlink records, graph
inconsistent" -- when the graph was consistent and the script was incomplete. Recovered after
pushback. Class: serial speculation on existing behavior before reading the spec.
`feedback-stop-serial-speculation` already names it and the fix -- "for EXISTING code the read IS
the measurement." `doubly-linked-references.md` and `check_links.sh`'s header were the read.

### Benjamin

- The original `update_linkages_for_move.py` session: the 4-stage intent was clear, but only half
  of stage 1 reached the code, and neither of us caught it at review. Class: a spec held
  verbally, not written into the tool's docstring or a test, so the gap was invisible. Now fixed
  -- the 4 stages are in the docstring, and the doctrine doc is corrected. One-off, low residual
  risk. No memory.

## Workflow improvements

- **Before wrapping or batching an existing tool, run its core on the hardest single case first.**
  Here: one hand-run move of a file with a `## References`-only backlink. Extends
  `feedback-verify-harness-first` -- "the harness" includes a script you are about to depend on,
  not only one you just wrote.
- **A doc's blast radius is `Links to here` ∪ `References`.** Either alone is half the set. Now in
  the doctrine doc and in `project-doc-linking-tooling`.
- **When existing code gives a bad result, check it against its intent before deciding the result
  is unavoidable.** Extends `feedback-addition-vs-defect-framing` with the reverse direction.

## Memories

- **`feedback-addition-vs-defect-framing`** -- added a "reverse direction" paragraph: do not
  default to "limitation / precondition / constraint" for a bad result from existing code either.
  Check against intent first.
- **`feedback-verify-harness-first`** -- added a paragraph: before batching or wrapping an
  existing tool, exercise its core on the hardest single case first.
- **`project-doc-linking-tooling`** -- rewritten. The tooling has run on all 20 real `planning/`
  files. The reorg is done. The move script's referrer set is now the union of both sections plus
  a stage-0 `check_links.sh` gate. The blast radius of any doc is that union.

## References


## Links to here

