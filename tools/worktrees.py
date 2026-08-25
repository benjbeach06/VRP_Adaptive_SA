"""Short-path git worktrees for cross-commit experiments.

    from worktrees import ensure, remove_all
    root = ensure("c539a1e", note="post_stage1 arm of 2026-08-23_tuned_vs_stage1")

WHY THE PATH IS SHORT
---------------------
Windows caps a path at 260 characters, and `git worktree add` reports the overflow against files
DEEP INSIDE the checkout -- `experiment_logs/ablations/<study>/<arm>/results.json` -- not against
the worktree root. It reads like a corrupted checkout rather than a path-length problem.

Nesting a worktree under `experiment_logs/ablations/<study>/_worktrees/<arm>` put the checkout root
96 characters in. The deepest tracked file inside any checkout is already 103. With a 44-character
repo root that is 245 of 260, and the margin SHRINKS every time an ablation study is committed,
because the deepest tracked file is itself an ablation result. It was going to fail on its own.

`_worktrees/<short-commit>` puts the root 18 characters in instead, leaving roughly 97 spare.

KEYED BY COMMIT, NOT BY ARM
---------------------------
A worktree is a checkout of a commit and nothing more. Two arms that pin the same commit and differ
only in runtime parameters share one -- the 3-arm study on 2026-08-23 built two identical trees
before this existed. `_worktrees/index.tsv` records which experiment asked for each, so a stale one
can be identified rather than guessed at.

These are TEMPORARY. `_worktrees/` is gitignored. Remove them with `remove_all()` or
`git worktree remove <path> --force` when a study is finished.
"""
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WT_DIR = os.path.join(ROOT, "_worktrees")
INDEX = os.path.join(WT_DIR, "index.tsv")


def _short(commit: str) -> str:
    """Resolve to the short hash git itself would print, so the folder name is recognisable."""
    out = subprocess.run(["git", "rev-parse", "--short", commit],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def ensure(commit: str, note: str = "") -> str:
    """Create-or-reuse a worktree pinned to `commit`. Returns its absolute path.

    Reuse is safe because the checkout is immutable -- it is a detached HEAD at one commit, and
    experiments pass their configuration at runtime rather than editing the tree.
    """
    short = _short(commit)
    path = os.path.join(WT_DIR, short)
    os.makedirs(WT_DIR, exist_ok=True)

    if not os.path.isdir(path):
        result = subprocess.run(["git", "worktree", "add", "--detach", path, commit],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"git worktree add {short} failed:\n{result.stderr.strip()}")

    with open(INDEX, "a", encoding="utf-8") as f:
        f.write(f"{short}\t{commit}\t{time.strftime('%Y-%m-%d %H:%M')}\t{note}\n")
    return path


def remove_all() -> list[str]:
    """Remove every worktree under _worktrees/. Returns the ones removed."""
    removed = []
    if not os.path.isdir(WT_DIR):
        return removed
    for name in sorted(os.listdir(WT_DIR)):
        path = os.path.join(WT_DIR, name)
        if not os.path.isdir(path):
            continue
        subprocess.run(["git", "worktree", "remove", path, "--force"],
                       cwd=ROOT, capture_output=True, text=True)
        removed.append(name)
    if os.path.exists(INDEX):
        os.remove(INDEX)
    return removed


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        gone = remove_all()
        print(f"removed {len(gone)} worktree(s): {', '.join(gone) if gone else 'none'}")
    else:
        if os.path.exists(INDEX):
            with open(INDEX, encoding="utf-8") as f:
                print(f.read().rstrip())
        else:
            print("no worktrees. `python tools/worktrees.py clean` to remove any strays.")
