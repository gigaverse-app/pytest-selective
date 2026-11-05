"""Freeze local edits as a Git tree without changing HEAD or the user's index."""

import shutil
import tempfile
from pathlib import Path

if __package__:
    from .git_operations import git
else:
    # The expansion action runs from this source directory without installation.
    from git_operations import git


def snapshot_working_tree(repo: Path, *, pathspec: str = ".") -> str:
    """Include edits/deletions and nonignored untracked files in the requested scope.

    A private index owns all staging. Git writes unreachable tree/blob objects,
    but no commit, ref or working file; normal Git garbage collection owns those
    objects afterwards. Seed from the real index to retain force-added ignored
    files, staged inputs outside the scope and the stat cache. Git resolves a split
    index through the repository's shared index; linked worktrees resolve their
    own index path. The expansion guard updates only Python sources; the planner
    updates every input.
    """
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    if repo.resolve() != root.resolve():
        raise ValueError("--repo must name the Git repository root")
    real_index = root / git(root, "rev-parse", "--git-path", "index").decode().strip()
    with tempfile.TemporaryDirectory(prefix="pytest-selective-index-") as directory:
        index = Path(directory) / "index"
        if real_index.is_file():
            # Git compares file timestamps to the index timestamp for racy-clean
            # detection. A fresh copy timestamp can hide same-size local edits.
            shutil.copy2(real_index, index)
        git(root, "add", "--all", "--", pathspec, index=index)
        return git(root, "write-tree", index=index).decode().strip()
