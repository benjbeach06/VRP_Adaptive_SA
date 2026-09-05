"""
Make the solver importable on Python 3.12/3.13.

The solver currently requires Python 3.14: class-body annotations like
`route: Route | None` are forward references that only became lazy with PEP 649.
`from __future__ import annotations` (Python 3.7+) achieves the same thing, so
this is a one-line-per-file change with no behavioural effect.

    python benchmark/compat_patch.py --apply     # add the import
    python benchmark/compat_patch.py --revert    # take it back out
    python benchmark/compat_patch.py --check     # report status, change nothing

Both directions are idempotent. If you are on 3.14 you do not need this at all.

(The remaining floor is PEP 695 generic syntax -- `def f[T](...)` in
SimAnn_VRP_Core_Model.py -- which needs 3.12. Those appear only on an unused
helper, so deleting them would drop the floor to 3.10.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

LINE = "from __future__ import annotations\n"
TARGETS = [
    "SimAnn_VRP_Core_Model.py",
    "SimAnn_VRP_BLOperators.py",
    "SimAnn_VRP_Operators.py",
    "SimAnn_VRP_Solver.py",
]
ROOT = Path(__file__).resolve().parent.parent


def status(path: Path) -> bool:
    return any(l.strip() == LINE.strip() for l in path.read_text().splitlines()[:5])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    g.add_argument("--check", action="store_true")
    args = ap.parse_args()

    missing = [t for t in TARGETS if not (ROOT / t).exists()]
    if missing:
        sys.exit(f"not in the repo root -- missing {missing}. "
                 f"Expected the solver modules in {ROOT}")

    for target in TARGETS:
        path = ROOT / target
        present = status(path)
        if args.check:
            print(f"{'patched  ' if present else 'unpatched'}  {target}")
            continue
        if args.apply and not present:
            path.write_text(LINE + path.read_text())
            print(f"patched   {target}")
        elif args.revert and present:
            text = path.read_text()
            path.write_text(text.replace(LINE, "", 1))
            print(f"reverted  {target}")
        else:
            print(f"unchanged {target}")


if __name__ == "__main__":
    main()
