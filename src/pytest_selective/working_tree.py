"""Freeze local edits as a Git tree without changing HEAD or the user's index."""

import shutil
import tempfile
from pathlib import Path

if __package__:
    from .git_operations import git
else:
    # The expansion action runs from this source directory without installation.
    from git_operations import git


def snapshot_working_tree(repo: Path, *, pathspec: str = ".", preserve_stat_cache: bool = False) -> str:
    """Include edits/deletions and nonignored untracked files in the requested scope.

    A private index owns all staging. Git writes unreachable tree/blob objects,
    but no commit, ref or working file; normal Git garbage collection owns those
    objects afterwards. Both modes seed from the real index, retaining staged and
    force-added ignored files. The planner rebuilds its entries to see edits hidden
    by assume-unchanged/skip-worktree flags. The expansion guard preserves the stat
    cache while updating only Python sources. Both support split indexes and linked
    worktrees without changing the user's index.
    """
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    if repo.resolve() != root.resolve():
        raise ValueError("--repo must name the Git repository root")
    with tempfile.TemporaryDirectory(prefix="pytest-selective-index-") as directory:
        index = Path(directory) / "index"
        if preserve_stat_cache:
            real_index = root / git(root, "rev-parse", "--git-path", "index").decode().strip()
            if real_index.is_file():
                # Git compares file timestamps to the index timestamp for racy-clean
                # detection. A fresh copy timestamp can hide same-size local edits.
                shutil.copy2(real_index, index)
        else:
            staged = git(root, "ls-files", "--stage", "-z")
            git(root, "read-tree", "--empty", index=index)
            git(root, "update-index", "-z", "--index-info", data=staged, index=index)
        git(root, "add", "--all", "--", pathspec, index=index)
        return git(root, "write-tree", index=index).decode().strip()
