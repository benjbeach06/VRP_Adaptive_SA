#!/usr/bin/env python3
"""Report every name a module USES but never binds, imports, or gets from builtins.

    python tools/free_names.py <file.py> [file.py ...]

Answers one question: **what does this file still need from somewhere else?** Point it at a module
you just split out of a larger one and it prints the import header you have to write. Point it at a
finished module and a clean report means every name resolves.

WHY THIS EXISTS. Splitting a file means writing an import header for each piece, and the tempting
way to build one is to scan the extracted text for capitalized names and import those. That cannot
tell an ANNOTATION from a CONSTRUCTOR CALL. It put a class under `TYPE_CHECKING` in
`SimAnn_VRP_Core_Model/vehicle.py` while `Vehicle.__init__` was constructing one, and 114 tests
failed on `NameError`. This reports what the code actually references, so the header is written from
evidence.

It is a static check and it is deliberately simple:

    - Reports a name once, however often it appears.
    - Counts a name as bound by an assignment, a def, a class, a parameter, an import, a `global`
      or `nonlocal` declaration, an `except ... as`, a `with ... as`, or a match capture.
    - Does NOT model scope. A name bound anywhere in the file counts as bound everywhere in it, so
      this UNDER-reports rather than over-reports. It will not catch a name used before its
      assignment.
    - Reports only the root of a dotted path: `np.linalg.norm` reports `np`.
    - Attribute names are never reported, so `record.travel_changes` reports nothing.

Exit status is 0 when every file is clean and 1 when any file has free names, so it can gate a
commit.
"""
import ast
import builtins
import pathlib
import sys


def free_names(source: str) -> set[str]:
    """Names read in `source` that nothing in it binds."""
    tree = ast.parse(source)
    bound: set[str] = set()
    used: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            a = node.args
            args = a.posonlyargs + a.args + a.kwonlyargs
            if a.vararg:
                args.append(a.vararg)
            if a.kwarg:
                args.append(a.kwarg)
            bound.update(arg.arg for arg in args)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        elif isinstance(node, ast.Name):
            (bound if isinstance(node.ctx, (ast.Store, ast.Del)) else used).add(node.id)

    return {n for n in used if n not in bound and not hasattr(builtins, n)}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    problems = 0
    for arg in sys.argv[1:]:
        path = pathlib.Path(arg)
        names = sorted(free_names(path.read_text(encoding="utf-8")))
        if names:
            problems += 1
            print(f"{path.as_posix()}: {len(names)} free")
            for n in names:
                print(f"    {n}")
        else:
            print(f"{path.as_posix()}: clean")

    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
