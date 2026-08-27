#!/usr/bin/env python3
"""Move a doubly-linked doc, rewriting every link that has to change. No search involved --
the move relies entirely on the source file's own ## Links to here section to know who
references it. See planning/doubly-linked-references.md.

    python tools/update_linkages_for_move.py <source> <target>

Assumes both <source> and <target> stay within the documentation-approved folders (design/**,
planning/**, retros/**, experiment_logs/**, RESULTS.md, METHODOLOGY.md, folder README.md files)
-- no scope check is performed here.

1. Reads <source>'s ## Links to here section: that is the full, authoritative list of files
   that link to it. Errors if the section does not exist -- a file that predates the rollout
   has no reliable backlink list, and this script refuses to guess by searching.
2. Rewrites every relative link inside <source> itself -- body, References, Links to here,
   the whole file -- so each still resolves to the same target, now computed from <target>'s
   directory instead of <source>'s.
3. For each file named in that Links to here list, rewrites only the link(s) that point at
   <source>'s old path so they point at <target> instead. Nothing else in those files changes.
4. Moves <source> to <target> -- `git mv` if <source> is tracked, a plain filesystem rename
   otherwise.

Display text follows the repo convention (see planning/doubly-linked-references.md): a link
inside ## References or ## Links to here uses the bare filename when the target is a sibling
(same directory) after the move, and the repo-root-relative path otherwise. That text rewrite
applies ONLY inside those two sections -- body prose links keep their author-chosen text and
have only their path corrected.

Silent on success. Errors go to stderr with a nonzero exit code and no files are changed.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^## (.+)$")
BULLET_RE = re.compile(r"^- \[([^\]]*)\]\(([^)\s]+)\)")

REFERENCES = "References"
LINKS_TO_HERE = "Links to here"
STRUCTURED_SECTIONS = (REFERENCES, LINKS_TO_HERE)


def rel_to_root(p: Path) -> str:
    return p.resolve().relative_to(REPO_ROOT).as_posix()


def relpath(from_dir: Path, target: Path) -> str:
    return os.path.relpath(target.resolve(), from_dir.resolve()).replace("\\", "/")


def display_text(from_dir: Path, target: Path) -> str:
    if target.resolve().parent == from_dir.resolve():
        return target.name
    return rel_to_root(target)


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def find_heading(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return (start, end) line-index span of a `## name` section, end exclusive.

    A real section heading has a blank line (or file boundary) on both sides -- this is
    what distinguishes it from the same heading text appearing inside a fenced example
    embedded in prose, which is indented into surrounding text instead. Fenced code blocks
    are also skipped outright as a second, independent guard.
    """
    start = None
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line.rstrip("\n"))
        if not m or m.group(1).strip() != name:
            continue
        before_ok = i == 0 or _is_blank(lines[i - 1])
        after_ok = i + 1 >= len(lines) or _is_blank(lines[i + 1])
        if before_ok and after_ok:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    in_fence = False
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not HEADING_RE.match(line.rstrip("\n")):
            continue
        before_ok = _is_blank(lines[j - 1])
        after_ok = j + 1 >= len(lines) or _is_blank(lines[j + 1])
        if before_ok and after_ok:
            end = j
            break
    return start, end


def structured_mask(lines: list[str]) -> list[bool]:
    """True for each line inside ## References or ## Links to here."""
    mask = [False] * len(lines)
    for name in STRUCTURED_SECTIONS:
        span = find_heading(lines, name)
        if span is not None:
            for i in range(span[0], span[1]):
                mask[i] = True
    return mask


def fence_mask(lines: list[str]) -> list[bool]:
    """True for each line that sits inside a ``` fence (and must not be rewritten)."""
    mask = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            mask.append(True)
            continue
        mask.append(in_fence)
    return mask


def parse_entries(lines: list[str], span: tuple[int, int]) -> list[dict]:
    start, end = span
    entries = []
    i = start + 1
    while i < end:
        m = BULLET_RE.match(lines[i])
        if m:
            entries.append({"href": m.group(2)})
        i += 1
    return entries


def rewrite_own_links(lines: list[str], old_dir: Path, new_dir: Path) -> list[str]:
    """Recompute every relative link in the file so it still resolves, from new_dir.
    Display text is also updated to convention, but only inside the two structured sections."""
    fenced = fence_mask(lines)
    structured = structured_mask(lines)
    out = []
    for is_fenced, is_structured, line in zip(fenced, structured, lines):
        if is_fenced:
            out.append(line)
            continue

        def repl(m: re.Match) -> str:
            text, href = m.group(1), m.group(2)
            if href.startswith(("http://", "https://", "#")):
                return m.group(0)
            target = (old_dir / href).resolve()
            new_href = relpath(new_dir, target)
            new_text = display_text(new_dir, target) if is_structured else text
            return f"[{new_text}]({new_href})"

        out.append(LINK_RE.sub(repl, line))
    return out


def rewrite_links_to_target(lines: list[str], file_dir: Path, old_target: Path,
                             new_target: Path) -> list[str]:
    """Rewrite only links that point at old_target, to point at new_target instead.
    Display text is updated to convention only inside the two structured sections."""
    fenced = fence_mask(lines)
    structured = structured_mask(lines)
    out = []
    for is_fenced, is_structured, line in zip(fenced, structured, lines):
        if is_fenced:
            out.append(line)
            continue

        def repl(m: re.Match) -> str:
            text, href = m.group(1), m.group(2)
            if href.startswith(("http://", "https://", "#")):
                return m.group(0)
            resolved = (file_dir / href).resolve()
            if resolved != old_target.resolve():
                return m.group(0)
            new_href = relpath(file_dir, new_target)
            new_text = display_text(file_dir, new_target) if is_structured else text
            return f"[{new_text}]({new_href})"

        out.append(LINK_RE.sub(repl, line))
    return out


def load(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def save(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: update_linkages_for_move.py <source> <target>", file=sys.stderr)
        return 2
    source = Path(sys.argv[1]).resolve()
    target = Path(sys.argv[2]).resolve()

    if not source.exists():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 1
    if target.exists():
        print(f"error: {target} already exists", file=sys.stderr)
        return 1

    source_lines = load(source)
    span = find_heading(source_lines, LINKS_TO_HERE)
    if span is None:
        print(f"error: {source} has no ## {LINKS_TO_HERE} section -- run tools/link_scan.py "
              f"on it first so its backlink list is known, rather than searching for one",
              file=sys.stderr)
        return 1

    referrers = parse_entries(source_lines, span)
    referrer_paths = []
    for e in referrers:
        p = (source.parent / e["href"]).resolve()
        if not p.exists():
            print(f"error: backlink target {p} (from {source}'s Links to here) does not exist",
                  file=sys.stderr)
            return 1
        referrer_paths.append(p)

    try:
        new_source_lines = rewrite_own_links(source_lines, source.parent, target.parent)
        save(source, new_source_lines)

        for ref_path in referrer_paths:
            ref_lines = load(ref_path)
            new_ref_lines = rewrite_links_to_target(ref_lines, ref_path.parent, source, target)
            save(ref_path, new_ref_lines)

        target.parent.mkdir(parents=True, exist_ok=True)
        is_tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(source)],
                                     cwd=REPO_ROOT, capture_output=True).returncode == 0
        if is_tracked:
            subprocess.run(["git", "mv", str(source), str(target)], check=True, cwd=REPO_ROOT)
        else:
            source.rename(target)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
