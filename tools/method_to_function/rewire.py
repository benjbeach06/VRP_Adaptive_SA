#!/usr/bin/env python3
"""Rewrite call sites after `extract.py` has lifted methods into free functions.

    python tools/method_to_function/rewire.py <manifest.json> <file.py> [file.py ...]

Step TWO. `receiver.method(args)` becomes `method(receiver, args)`, in place, in every file named.

WHY THIS IS NOT A REGEX. The receiver is an arbitrary expression and it has to move INTO the
argument list:

    route.first_visit.start_travel_delta_if_route_removed()
    -> start_travel_delta_if_route_removed(route.first_visit)

So the edit is driven by AST node positions and applied by splicing text from the end of the file
backwards. Comments, alignment and line breaks inside the call survive untouched, which is what lets
a behaviour-equivalence check mean something afterwards.

THREE KINDS, taken from the manifest rather than from a table kept here:

    instance   receiver becomes the first positional argument
    static     receiver is dropped -- it was only ever a namespace
    property   receiver becomes the only argument, and parentheses are added

**The classification is never hand-maintained.** `extract.py` reads it off the decorators and writes
it into the manifest. A name missing from a hand-written table produces a silently wrong call, which
is a real defect this tool shipped with once.

AMBIGUOUS NAMES. One method name can be lifted from two classes with different kinds -- an instance
method on one and a property on another. The parentheses settle it: an `Attribute` used as a call
target is the method, a bare `Attribute` is the property. If two entries share a name AND a kind,
nothing in the syntax can separate them, and this exits rather than guessing.

Every file is re-parsed after rewriting. A file that no longer parses is a bug here, not a warning.
"""
import ast
import collections
import json
import pathlib
import sys


def _slice(lines, r0, c0, r1, c1) -> str:
    if r0 == r1:
        return lines[r0 - 1][c0:c1]
    return "\n".join([lines[r0 - 1][c0:]] + lines[r0:r1 - 1] + [lines[r1 - 1][:c1]])


def _splice(lines, r0, c0, r1, c1, new) -> None:
    block = (lines[r0 - 1][:c0] + new + lines[r1 - 1][c1:]).split("\n")
    lines[r0 - 1:r1] = block


class Table:
    """Maps an ORIGINAL method name to the free function it became, per kind."""

    def __init__(self, manifest: dict):
        self.by_name: dict[str, dict[str, str]] = collections.defaultdict(dict)
        for new_name, info in manifest["functions"].items():
            origin, kind = info["origin_name"], info["kind"]
            if kind in self.by_name[origin]:
                sys.exit(f"{origin}: lifted twice as '{kind}' -- syntax cannot tell the call sites "
                         f"apart. Split this move into two runs.")
            self.by_name[origin][kind] = new_name

    def called(self, attr: str) -> tuple[str, str] | None:
        """The function an `X.attr(...)` call becomes, or None if attr was not moved."""
        kinds = self.by_name.get(attr)
        if not kinds:
            return None
        for kind in ("instance", "static"):
            if kind in kinds:
                return kinds[kind], kind
        return None

    def accessed(self, attr: str) -> str | None:
        """The function a bare `X.attr` becomes, or None."""
        kinds = self.by_name.get(attr)
        return kinds.get("property") if kinds else None


def rewire(text: str, table: Table, where: str, report: list) -> str:
    lines = text.split("\n")
    tree = ast.parse(text)
    call_targets, edits = set(), []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            hit = table.called(node.func.attr)
            if hit:
                call_targets.add(id(node.func))
                edits.append(("call", node, hit[0], hit[1]))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and id(node) not in call_targets:
            prop = table.accessed(node.attr)
            if prop:
                edits.append(("prop", node, prop, "property"))
            elif node.attr in table.by_name:
                sys.exit(f"{where}:{node.lineno}: '{node.attr}' was moved, but appears here as a "
                         f"bare attribute with no property form. Check this by hand.")

    for kind, node, new_name, moved_as in sorted(
            edits, key=lambda e: (e[1].lineno, e[1].col_offset), reverse=True):
        if kind == "prop":
            recv = _slice(lines, node.value.lineno, node.value.col_offset,
                          node.value.end_lineno, node.value.end_col_offset)
            _splice(lines, node.lineno, node.col_offset,
                    node.end_lineno, node.end_col_offset, f"{new_name}({recv})")
            report.append(f"  {where}:{node.lineno}  {recv}.{node.attr} -> {new_name}(...)")
            continue

        func = node.func
        recv = _slice(lines, func.value.lineno, func.value.col_offset,
                      func.value.end_lineno, func.value.end_col_offset)
        args = _slice(lines, func.end_lineno, func.end_col_offset,
                      node.end_lineno, node.end_col_offset)
        assert args.startswith("(") and args.endswith(")"), f"{where}:{node.lineno}: {args[:40]}"
        inner = args[1:-1]

        if moved_as == "static":
            new = f"{new_name}({inner})"
        elif inner.strip() == "":
            new = f"{new_name}({recv})"
        else:
            new = f"{new_name}({recv}, {inner})"
        _splice(lines, node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, new)
        report.append(f"  {where}:{node.lineno}  {recv}.{func.attr}(...) -> {new_name}(...)")

    out = "\n".join(lines)
    ast.parse(out)          # a file that no longer parses is a bug in this tool
    return out


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    table = Table(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))

    report: list[str] = []
    for arg in sys.argv[2:]:
        p = pathlib.Path(arg)
        p.write_text(rewire(p.read_text(encoding="utf-8"), table, p.name, report), encoding="utf-8")

    print("\n".join(report) if report else "  (no call sites matched)")
    print(f"{len(report)} call sites rewired across {len(sys.argv) - 2} files")


if __name__ == "__main__":
    main()
