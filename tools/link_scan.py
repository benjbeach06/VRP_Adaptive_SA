#!/usr/bin/env python3
"""Mechanical doubly-linked-reference maintainer. See planning/doubly-linked-references.md.

    python tools/link_scan.py <file>

Given File A, this script:
  1. Ensures File A has ## References and ## Links to here headings (empty if missing).
  2. Scans File A's body (everything before ## References, skipping fenced code blocks) for
     [text](path) links that resolve to in-scope documentation (design/**, planning/**,
     retros/**, experiment_logs/**, RESULTS.md, METHODOLOGY.md).
  3. Adds any such link not already in ## References (bare, no explanation).
  4. Removes any ## References entry whose target no longer appears in the body -- first
     deleting the reciprocal entry in that target's ## Links to here, then the entry itself.
  5. For every reference remaining in ## References, ensures the target file has both
     headings and a back-link to File A in its ## Links to here (bare, no explanation).

Dangling links (target file does not exist) are skipped and logged, never added or removed
blindly -- a human resolves those.

Writes nothing to stdout on success. All changes are logged to _session/link_script_output.md
(truncated at the start of every run). Errors go to stderr with a nonzero exit code.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "_session" / "link_script_output.md"

DOC_PREFIXES = ("design/", "planning/", "retros/", "experiment_logs/")
DOC_EXACT = {"RESULTS.md", "METHODOLOGY.md"}

LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^## (.+)$")
BULLET_RE = re.compile(r"^- \[([^\]]*)\]\(([^)\s]+)\)")

REFERENCES = "References"
LINKS_TO_HERE = "Links to here"
PLACEHOLDER = "*(none yet)*"


class LinkError(Exception):
    pass


def log(line: str) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def rel_to_root(p: Path) -> str:
    return p.resolve().relative_to(REPO_ROOT).as_posix()


def is_doc_path(p: Path) -> bool:
    if p.suffix != ".md":
        return False
    try:
        rel = rel_to_root(p)
    except ValueError:
        return False
    return rel in DOC_EXACT or rel.startswith(DOC_PREFIXES)


def display_text(source_dir: Path, target: Path) -> str:
    if target.resolve().parent == source_dir.resolve():
        return target.name
    return rel_to_root(target)


def href_from(source_dir: Path, target: Path) -> str:
    import os
    return os.path.relpath(target.resolve(), source_dir.resolve()).replace("\\", "/")


def strip_fenced_code(lines: list[str]) -> list[str]:
    """Return a copy with lines inside ``` fences blanked out, for link scanning only."""
    out = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


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


def parse_entries(lines: list[str], span: tuple[int, int]) -> list[dict]:
    """Parse bullet entries within a section span into dicts with line range and href."""
    start, end = span
    entries = []
    i = start + 1
    while i < end:
        line = lines[i]
        m = BULLET_RE.match(line)
        if m:
            entry_start = i
            i += 1
            while i < end and lines[i].strip() and not lines[i].lstrip().startswith("- ") \
                    and not HEADING_RE.match(lines[i]):
                i += 1
            entries.append({"start": entry_start, "end": i, "href": m.group(2), "text": m.group(1)})
        else:
            i += 1
    return entries


def body_links(lines: list[str], excluded_spans: list[tuple[int, int] | None]) -> list[str]:
    """Links in the body -- everything outside ## References, ## Links to here, and fences.

    Masks out both structured sections by span rather than assuming ## References comes
    first: a file with the sections in the other order would otherwise have its whole
    ## Links to here section swept in as "body" and its existing backlinks misread as new
    references.
    """
    masked = list(lines)
    for span in excluded_spans:
        if span is not None:
            for i in range(span[0], span[1]):
                masked[i] = ""
    scan_lines = strip_fenced_code(masked)
    return [m.group(2) for line in scan_lines for m in LINK_RE.finditer(line)]


def ensure_headings(lines: list[str]) -> list[str]:
    """Ensure ## References then ## Links to here exist at the end, empty if missing."""
    refs = find_heading(lines, REFERENCES)
    links = find_heading(lines, LINKS_TO_HERE)
    if refs is not None and links is not None:
        return lines
    while lines and lines[-1].strip() == "":
        lines.pop()
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if refs is None:
        lines += ["\n", f"## {REFERENCES}\n", "\n", f"{PLACEHOLDER}\n"]
    if links is None:
        lines += ["\n", f"## {LINKS_TO_HERE}\n", "\n", f"{PLACEHOLDER}\n"]
    return lines


def remove_entry(lines: list[str], span: tuple[int, int], href: str) -> bool:
    entries = parse_entries(lines, span)
    for e in entries:
        if e["href"] == href:
            del lines[e["start"]:e["end"]]
            return True
    return False


def add_entry(lines: list[str], section_name: str, text: str, href: str) -> None:
    span = find_heading(lines, section_name)
    assert span is not None
    start, end = span
    entries = parse_entries(lines, span)
    new_line = f"- [{text}]({href})\n"
    if not entries:
        # replace placeholder if present, else insert right after heading/blank line
        for i in range(start + 1, end):
            if lines[i].strip() == PLACEHOLDER:
                lines[i] = new_line
                return
        insert_at = start + 1
        if insert_at < end and lines[insert_at].strip() == "":
            insert_at += 1
        lines.insert(insert_at, new_line)
    else:
        lines.insert(entries[-1]["end"], new_line)


def has_entry(lines: list[str], section_name: str, href: str) -> bool:
    span = find_heading(lines, section_name)
    if span is None:
        return False
    return any(e["href"] == href for e in parse_entries(lines, span))


def load(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def save(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def process_file_a(file_a: Path) -> list[Path]:
    """Reconcile File A's References against its body. Returns final list of referenced files."""
    lines = ensure_headings(load(file_a))
    refs_span = find_heading(lines, REFERENCES)
    links_span = find_heading(lines, LINKS_TO_HERE)
    existing = parse_entries(lines, refs_span)

    source_dir = file_a.parent
    resolved_existing = {}
    for e in existing:
        target = (source_dir / e["href"]).resolve()
        resolved_existing[e["href"]] = target

    body = body_links(lines, [refs_span, links_span])
    resolved_body = {}
    for href in body:
        target = (source_dir / href).resolve()
        if is_doc_path(target):
            resolved_body[href] = target

    existing_valid = {h: t for h, t in resolved_existing.items() if t.exists()}
    existing_dangling = {h: t for h, t in resolved_existing.items() if not t.exists()}
    for h in existing_dangling:
        log(f"SKIPPED-DANGLING | {rel_to_root(file_a)} | {REFERENCES} | existing entry [{h}] target does not exist")

    body_valid = {}
    for h, t in resolved_body.items():
        if t.exists():
            body_valid[h] = t
        else:
            log(f"SKIPPED-DANGLING | {rel_to_root(file_a)} | {REFERENCES} | body link [{h}] target does not exist")

    existing_targets = {t.resolve() for t in existing_valid.values()}
    body_targets = {t.resolve() for t in body_valid.values()}

    to_remove = existing_targets - body_targets
    to_add = body_targets - existing_targets

    for target in to_remove:
        href = next(h for h, t in existing_valid.items() if t.resolve() == target)
        b_lines = load(target)
        b_lines = ensure_headings(b_lines)
        back_href = href_from(target.parent, file_a)
        if remove_entry(b_lines, find_heading(b_lines, LINKS_TO_HERE), back_href):
            save(target, b_lines)
            log(f"REMOVED | {rel_to_root(target)} | {LINKS_TO_HERE} | backlink to {rel_to_root(file_a)} removed")
        remove_entry(lines, find_heading(lines, REFERENCES), href)
        log(f"REMOVED | {rel_to_root(file_a)} | {REFERENCES} | [{href}] -> {rel_to_root(target)}")

    for target in to_add:
        href = next(h for h, t in body_valid.items() if t.resolve() == target)
        text = display_text(source_dir, target)
        add_entry(lines, REFERENCES, text, href)
        log(f"ADDED | {rel_to_root(file_a)} | {REFERENCES} | [{text}]({href}) -> {rel_to_root(target)}")

    save(file_a, lines)

    final_span = find_heading(load(file_a), REFERENCES)
    final_lines = load(file_a)
    final_entries = parse_entries(final_lines, find_heading(final_lines, REFERENCES))
    return [(source_dir / e["href"]).resolve() for e in final_entries]


def process_backlinks(file_a: Path, targets: list[Path]) -> None:
    for target in targets:
        if not target.exists():
            continue
        b_lines = ensure_headings(load(target))
        back_href = href_from(target.parent, file_a)
        if not has_entry(b_lines, LINKS_TO_HERE, back_href):
            text = display_text(target.parent, file_a)
            add_entry(b_lines, LINKS_TO_HERE, text, back_href)
            log(f"ADDED | {rel_to_root(target)} | {LINKS_TO_HERE} | [{text}]({back_href}) -> {rel_to_root(file_a)}")
        save(target, b_lines)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: link_scan.py <file.md>", file=sys.stderr)
        return 2
    file_a = Path(sys.argv[1]).resolve()
    if not file_a.exists():
        print(f"error: {file_a} does not exist", file=sys.stderr)
        return 1

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")

    try:
        targets = process_file_a(file_a)
        process_backlinks(file_a, targets)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
