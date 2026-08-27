---
name: context_handoff
description: End-of-session handoff. Dumps this session into the _session/*.md scratch logs, then summarizes what was learned about Benjamin. Use when starting a new chat, hitting a context limit, or asked to hand off / dump context.
---

# context_handoff

## 1. Dump to `_session/`

- Read `_session/README.md` first. It says what each file is for.
- Read each other file before writing to it. Match its existing style.
- `context_carryover.md` is the misc file. Put anything else worth keeping there.
- Append. Do not overwrite history.
- Exception: `session_summary.md`. Update its state (branch, HEAD, done, owed) in place.
- Skip a file if nothing this session fits it.

## 2. Verify every checkable claim BEFORE writing it

A handoff file is read by a session that cannot check it cheaply. **A wrong claim is worse than a
missing one, because it suppresses the check.** Verification belongs here, at creation, where the
context to check still exists.

Run the check. Do not write from memory of what happened earlier in the session.

| claim | how to verify |
|---|---|
| branch, HEAD, commit hashes | `git log --oneline -5`, `git status --porcelain` |
| "commit X landed" | confirm X is in `git log`, not just that it was written |
| a test or lint command | run it; record the actual pass/fail counts it printed |
| "N tests, M skipped" | from the run's own output, this session |
| a file or function path | confirm it exists at that path now |
| "X does not work here" | re-run X. A negative claim ages worst of all |
| push status | `git log origin/<branch>..HEAD` |

If a check is too expensive to run, write the claim with its date and say it is unverified. An
unverified claim marked as such is fine. An unverified claim stated as fact is the defect.

If a check DISPROVES something already in a `_session/` file, correct that file in the same turn.

2026-08-27 found two stale claims that had survived into a later session: `context_carryover.md`
said `unittest discover` does not work here (it does — 55 tests, 1 skipped), and
`session_summary.md` gave a HEAD and two commit hashes absent from `git log`. Both would have
misled the next session. Benjamin: *"If they're stale that's a handoff fault; verification of
handoff claims should happen on the handoff-creation stage where the context exists."*

## 3. Summarize what was learned about Benjamin

- The point: let him see this before the context is lost. State it in chat, not a file.
- Cover working style too: skill level, rigor, what he caught, what he confirmed.
- Do NOT write or update memory files. Suggest updates instead, and wait.
- Keep it short. State what changed, not the technical recap.
