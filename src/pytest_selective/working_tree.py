"""Freeze local edits as a Git tree without changing HEAD or the user's index."""

import subprocess
import tempfile
from pathlib import Path

from pytest_selective.impact_graph import git, git_environment


def snapshot_working_tree(repo: Path) -> str:
    """Include tracked edits/deletions and nonignored untracked files.

    A private index owns all staging. Git writes unreachable tree/blob objects,
    but no commit, ref or working file; normal Git garbage collection owns those
    objects afterwards. The planner can therefore reuse its immutable-tree graph
    and both-side dependency analysis for local edits, including removed imports.
    """
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    if repo.resolve() != root.resolve():
        raise ValueError("--repo must name the Git repository root")
    # Reconstruct the actual index rather than HEAD: force-added ignored files
    # are tracked local inputs too. The stage listing also supports split indexes.
    staged = git(root, "ls-files", "--stage", "-z")
    with tempfile.TemporaryDirectory(prefix="pytest-selective-index-") as directory:
        environment = {**git_environment(), "GIT_INDEX_FILE": str(Path(directory) / "index")}

        def indexed(*args: str, data: bytes | None = None) -> str:
            return (
                subprocess.run(
                    ["git", "-C", str(root), *args],
                    env=environment,
                    input=data,
                    capture_output=True,
                    check=True,
                )
                .stdout.decode()
                .strip()
            )

        indexed("read-tree", "--empty")
        indexed("update-index", "-z", "--index-info", data=staged)
        indexed("add", "--all", "--", ".")
        return indexed("write-tree")
