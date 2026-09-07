#!/usr/bin/env python3
"""Lift methods out of class bodies into free-function source text.

    python tools/method_to_function/extract.py <spec.json> <manifest.json> [package-dir]

Step ONE of a two-step move. This produces the new function bodies and a manifest describing them;
`rewire.py` then reads that manifest and fixes the call sites. Run them in that order.

`self` becomes an explicitly typed first parameter named for its class:

    class Route:
        def total_distance(self) -> Num: ...      ->   def total_distance(route: Route) -> Num: ...

WHAT IT DOES NOT TOUCH. Only NAME and COMMENT tokens equal to `self` are rewritten, via `tokenize`.
STRING tokens are left exactly as they were, so an assert message like "Cannot combine with self"
survives and gets reviewed by hand afterwards. Everything else -- blank lines, alignment, the
comment block above the def -- is copied verbatim, which is what lets a behaviour-equivalence check
be meaningful after the move.

THE SPEC is a JSON list. One entry per method:

    [{"module": "routes.py",      // file inside the package directory
      "cls":    "Route",          // class the method is defined on
      "name":   "cost_deltas_if_removed",
      "param":  "route",          // what `self` becomes
      "annot":  "Route",          // its type annotation; ignored for a staticmethod
      "rename": "..."}]           // OPTIONAL new function name, for collisions

A rename is needed when two classes define the same method name, because free functions share one
namespace and methods do not.

THE MANIFEST it writes carries, per resulting function: the source text, the `kind` that `rewire.py`
dispatches on (instance / static / property), and the origin class and name. `rewire.py` derives its
whole classification from this file, so there is no second table to keep in step -- a name missing
from a hand-written table is a silent miscompile, and that is the failure this design exists to
prevent.

Decorators are dropped: `@staticmethod` and `@property` are meaningless on a free function, and the
`kind` field records which one was there.
"""
import ast
import io
import json
import pathlib
import re
import sys
import tokenize


def rewrite_self(text: str, newname: str) -> str:
    """Replace the identifier `self` with `newname`, in code and comments only.

    Splices by token position rather than running the token stream back through `untokenize`,
    which would reflow the source.
    """
    edits = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.NAME and tok.string == "self":
            edits.append((tok.start, tok.end, newname))
        elif tok.type == tokenize.COMMENT and re.search(r"\bself\b", tok.string):
            edits.append((tok.start, tok.end, re.sub(r"\bself\b", newname, tok.string)))

    lines = text.split("\n")
    for (r0, c0), (r1, c1), new in sorted(edits, reverse=True):
        assert r0 == r1, "NAME and COMMENT tokens are single-line by construction"
        line = lines[r0 - 1]
        lines[r0 - 1] = line[:c0] + new + line[c1:]
    return "\n".join(lines)


def lift(pkg: pathlib.Path, module: str, cls: str, name: str, param: str, annot: str,
         rename: str | None = None) -> tuple[str, str]:
    """Return (kind, source) for one method, lifted to module level."""
    src = (pkg / module).read_text(encoding="utf-8")
    lines = src.split("\n")
    tree = ast.parse(src)

    matches = [m for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
               for m in c.body if isinstance(m, ast.FunctionDef) and m.name == name]
    assert len(matches) == 1, f"{module}:{cls}.{name}: found {len(matches)} definitions"
    node = matches[0]

    decorators = {d.id for d in node.decorator_list if isinstance(d, ast.Name)}
    kind = "static" if "staticmethod" in decorators else \
           "property" if "property" in decorators else "instance"

    start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    # Take any explanatory comment block sitting directly above, but never a region marker.
    while start > 1:
        prev = lines[start - 2].strip()
        if prev.startswith("#") and not prev.startswith(("#region", "#endregion")):
            start -= 1
        else:
            break

    body = "\n".join(lines[start - 1:node.end_lineno])
    body = re.sub(r"^\s*@(staticmethod|property)\n", "", body, flags=re.M)
    body = rewrite_self(body, param)

    if kind != "static":
        # `self` is already `param`; give it the explicit annotation.
        pat = re.compile(r"(def\s+" + re.escape(name) + r"\s*\(\s*)" + re.escape(param) + r"\b")
        body, n = pat.subn(r"\g<1>" + f"{param}: {annot}", body, count=1)
        assert n == 1, f"{cls}.{name}: could not annotate the lifted first parameter"

    if rename:
        body = re.sub(r"(def\s+)" + re.escape(name) + r"\b", r"\g<1>" + rename, body, count=1)

    dedented = [line[4:] if line.startswith("    ") else line for line in body.split("\n")]
    return kind, "\n".join(dedented).rstrip() + "\n"


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    spec_path, manifest_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    pkg = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else pathlib.Path(".")

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    functions: dict[str, dict] = {}
    for item in spec:
        new_name = item.get("rename") or item["name"]
        assert new_name not in functions, (
            f"{new_name}: two entries produce the same function name. Give one a \"rename\".")
        kind, source = lift(pkg, item["module"], item["cls"], item["name"],
                            item["param"], item["annot"], item.get("rename"))
        functions[new_name] = {"kind": kind, "origin_class": item["cls"],
                               "origin_name": item["name"], "source": source}

    manifest_path.write_text(json.dumps({"functions": functions}, indent=1), encoding="utf-8")
    kinds: dict[str, int] = {}
    for f in functions.values():
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print(f"lifted {len(functions)} functions -> {manifest_path}")
    for k in sorted(kinds):
        print(f"  {k:9} {kinds[k]}")


if __name__ == "__main__":
    main()
