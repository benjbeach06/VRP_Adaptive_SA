"""Record WHICH SOLVER produced a result, so a reader never has to reconstruct it.

    from run_stamp import solver_stamp
    results = {"_solver": solver_stamp(), ...}

A measurement describes the solver that produced it, and the solver changes. Without a stamp, the
only way to date a result is to match its file mtime against the commit log -- which is inference,
and a mislabelled result is worse than an unlabelled one.

The stamp is written by the harness AT RUN TIME, so it records what actually ran.

WHAT IT CATCHES
    A roster that grew, an uncommitted working tree, a different Python. All of those change what a
    number means, and none of them is visible in the number.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The modules whose state changes what a solve DOES. SimAnn_VRP.py is the driver -- harnesses build
# their own instances and never import it -- so edits there do not invalidate a measurement.
SOLVER_MODULES = frozenset({
    "SimAnn_VRP_Core_Model.py",
    "SimAnn_VRP_BLOperators.py",
    "SimAnn_VRP_Operators.py",
    "SimAnn_VRP_Solver.py",
})


def _git(*args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
        # rstrip, NOT strip: porcelain status lines begin with a space, and stripping it
        # shifts every field left so the path slice below eats a character.
        return out.stdout.rstrip() if out.returncode == 0 else ""
    except Exception:
        return ""


_CACHED: dict | None = None


def solver_stamp(solver=None) -> dict:
    """
    Identity of the solver that is about to run. Cheap; call it once per harness invocation.

    Pass `solver` when the caller already has one. Otherwise a throwaway 10-customer instance is
    built just to read the roster, which costs milliseconds.

    `solver_dirty` is the field that matters. It is scoped to SOLVER_MODULES, not the whole tree:
    edited docs or planning files do not change what a solve does, and listing them would bury the
    one fact that does. A true value means the SHA does NOT describe the code that ran.
    """
    global _CACHED
    cacheable = solver is None          # reassigned below, so record the caller's intent now
    if _CACHED is not None and cacheable:
        return _CACHED

    roster = []
    if solver is None:
        try:
            sys.path.insert(0, str(ROOT))
            sys.path.insert(0, str(ROOT / "tools"))
            import tune                                     # noqa: E402
            from SimAnn_VRP_Solver import SimAnnVRPSolver   # noqa: E402
            solver = SimAnnVRPSolver(tune.build_instance(10), max_time=1)
        except Exception as exc:
            roster = [f"<roster unavailable: {type(exc).__name__}: {exc}>"]

    if solver is not None and not roster:
        roster = [type(op).__name__ for op in solver.operators]

    dirty = [l[3:] for l in _git("status", "--porcelain").splitlines() if l[:2] != "??"]
    solver_dirty = sorted(f for f in dirty if f in SOLVER_MODULES)
    stamp = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_sha": _git("rev-parse", "--short", "HEAD"),
        "git_subject": _git("log", "-1", "--format=%s"),
        "solver_dirty": bool(solver_dirty),
        "solver_dirty_files": solver_dirty,
        "roster_size": len(roster),
        "roster": roster,
        "python": sys.version.split()[0],
    }
    if cacheable:
        _CACHED = stamp
    return stamp


def stamp_header(stamp: dict) -> str:
    """One-line form, for text logs that cannot carry a dict."""
    return (f"# SOLVER: {stamp['roster_size']} operators, "
            f"git {stamp['git_sha']}{'+SOLVER DIRTY' if stamp['solver_dirty'] else ''}, "
            f"python {stamp['python']}, {stamp['when']}")


if __name__ == "__main__":
    s = solver_stamp()
    print(stamp_header(s))
    print(json.dumps(s, indent=1))
