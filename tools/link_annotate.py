#!/usr/bin/env python3
"""Narrow, single-purpose editor for doubly-linked-reference explanations.

    python tools/link_annotate.py <file> <section> <href> <explanation>

<section> MUST be exactly "References" or "Links to here" -- anything else is a hard
error and the script makes no edit. This is the ONLY sanctioned way to add or replace the
explanation text on a reference entry; it never touches any other part of a file.

Finds the bullet entry in <section> whose link target is exactly <href> (as it literally
appears in the file, e.g. what tools/link_scan.py logged). If the entry has no explanation
yet, appends " -- <explanation>". If it already has one (contains " -- "), replaces the
existing explanation with the new one. The entry is collapsed to a single line; rewrapping
for the ~90-col style is a manual/cosmetic follow-up, not this script's job.

No stdout on success. Errors go to stderr with a nonzero exit code and no file is modified.
"""
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^## (.+)$")
BULLET_RE = re.compile(r"^- \[([^\]]*)\]\(([^)\s]+)\)")
ALLOWED_SECTIONS = {"References", "Links to here"}


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


def find_entry(lines: list[str], span: tuple[int, int], href: str) -> tuple[int, int] | None:
    start, end = span
    i = start + 1
    while i < end:
        m = BULLET_RE.match(lines[i])
        if m and m.group(2) == href:
            entry_start = i
            j = i + 1
            while j < end and lines[j].strip() and not lines[j].lstrip().startswith("- ") \
                    and not HEADING_RE.match(lines[j]):
                j += 1
            return entry_start, j
        i += 1
    return None


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: link_annotate.py <file> <section> <href> <explanation>", file=sys.stderr)
        return 2
    file_path, section, href, explanation = sys.argv[1:5]

    if section not in ALLOWED_SECTIONS:
        print(f'error: <section> must be exactly "References" or "Links to here", got {section!r}',
              file=sys.stderr)
        return 1

    path = Path(file_path)
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 1

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    span = find_heading(lines, section)
    if span is None:
        print(f"error: {path} has no ## {section} section", file=sys.stderr)
        return 1

    entry_span = find_entry(lines, span, href)
    if entry_span is None:
        print(f"error: no entry for href {href!r} in ## {section} of {path}", file=sys.stderr)
        return 1

    start, end = entry_span
    m = BULLET_RE.match(lines[start])
    text = m.group(1)
    new_line = f"- [{text}]({href}) -- {explanation}\n"
    lines[start:end] = [new_line]

    path.write_text("".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
