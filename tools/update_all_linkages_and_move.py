#!/usr/bin/env python3
"""Apply a batch of doc moves, running tools/update_linkages_for_move.py for each one.

    python tools/update_all_linkages_and_move.py <moves-file>

The moves file has one move per line:

    planning/family-generation.md    planning/operator-selection/family-generation.md

Blank lines and lines whose first non-space character is `#` are ignored. Each move is
two whitespace-separated paths, relative to the repo root or absolute. A line with any
other field count is a hard error and no move runs.

Before the first move, the whole batch is pre-flighted while the tree is still clean:
every source exists, every target is free, no source or target is listed twice, and
`tools/check_links.sh` reports nothing for any source. A move that trusts stale
back-matter would corrupt links, so a single bad file stops the batch before it starts
rather than after N moves have already been applied.

Ordering does not matter. update_linkages_for_move.py rewrites every file that links to
the moved doc -- the union of its ## Links to here and ## References sections -- as part
of the same move, so each file's links stay live between moves. The core script also
runs check_links.sh on each source itself and creates missing target folders.

Moves run in file order. On the first failure the batch stops: moves already listed as
applied have changed the working tree, the failed move changed nothing (the core script
is atomic), and the rest did not run. Silent on full success apart from a final count.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = Path(__file__).resolve().parent / "update_linkages_for_move.py"
CHECK_LINKS = REPO_ROOT / "tools" / "check_links.sh"


def parse(moves_path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for n, raw in enumerate(moves_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2:
            print(f"error: {moves_path}:{n}: expected 2 paths, got {len(fields)}: {raw!r}",
                  file=sys.stderr)
            sys.exit(2)
        pairs.append((fields[0], fields[1]))
    return pairs


def preflight(pairs: list[tuple[str, str]]) -> list[str]:
    """Return a list of problems found without touching the tree. Empty means go."""
    problems: list[str] = []
    srcs = [Path(s).resolve() for s, _ in pairs]
    dsts = [Path(d).resolve() for _, d in pairs]

    for label, paths in (("source", srcs), ("target", dsts)):
        for p in {p for p in paths if paths.count(p) > 1}:
            problems.append(f"{label} listed more than once: {p}")
    for p in set(srcs) & set(dsts):
        problems.append(f"path is both a source and a target: {p}")

    for i, (src, dst) in enumerate(pairs, 1):
        if not Path(src).resolve().exists():
            problems.append(f"move {i}: source {src} does not exist")
        if Path(dst).resolve().exists():
            problems.append(f"move {i}: target {dst} already exists")

    existing_srcs = [s for s, _ in pairs if Path(s).resolve().exists()]
    if existing_srcs:
        check = subprocess.run(["bash", str(CHECK_LINKS), *existing_srcs],
                               cwd=REPO_ROOT, capture_output=True, text=True)
        if check.returncode != 0:
            problems.append("check_links.sh reported problems on the sources:\n"
                            + (check.stdout + check.stderr).rstrip())
    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: update_all_linkages_and_move.py <moves-file>", file=sys.stderr)
        return 2
    moves_path = Path(sys.argv[1]).resolve()
    if not moves_path.exists():
        print(f"error: {moves_path} does not exist", file=sys.stderr)
        return 1

    pairs = parse(moves_path)
    if not pairs:
        print(f"error: {moves_path} lists no moves", file=sys.stderr)
        return 1

    problems = preflight(pairs)
    if problems:
        print(f"error: pre-flight failed, no move ran ({len(problems)} problem(s)):",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    applied: list[tuple[str, str]] = []
    for i, (src, dst) in enumerate(pairs):
        result = subprocess.run([sys.executable, str(CORE), src, dst], cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"error: move {i + 1}/{len(pairs)} failed: {src} -> {dst}", file=sys.stderr)
            if applied:
                print("applied before the failure:", file=sys.stderr)
                for a, b in applied:
                    print(f"  {a} -> {b}", file=sys.stderr)
            not_run = pairs[i + 1:]
            if not_run:
                print("not run:", file=sys.stderr)
                for a, b in not_run:
                    print(f"  {a} -> {b}", file=sys.stderr)
            return 1
        applied.append((src, dst))

    print(f"{len(applied)} moves applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
