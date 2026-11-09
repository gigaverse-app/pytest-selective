"""Repository-scoped Git execution, also usable by the standalone expansion guard."""

import os
import subprocess
from pathlib import Path

# Hook location variables outrank `git -C`, including in linked worktrees.
# The explicitly requested repository and optional private index must win.
GIT_LOCATION_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_PREFIX",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_QUARANTINE_PATH",
        "GIT_INDEX_VERSION",
        "GIT_SHALLOW_FILE",
        "GIT_GRAFT_FILE",
    }
)


def git_environment() -> dict[str, str]:
    """Keep authentication/configuration while removing inherited repository locations."""
    return {name: value for name, value in os.environ.items() if name not in GIT_LOCATION_ENV}


def git(repo: Path, *args: str, data: bytes | None = None, index: Path | None = None) -> bytes:
    """Run against the requested repository, preserving binary blobs and failure details."""
    environment = git_environment()
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=True,
        env=environment,
    ).stdout


def git_text(repo: Path, *args: str, index: Path | None = None) -> str:
    """UTF-8 text with universal newlines, independent of the Windows locale."""
    return git(repo, *args, index=index).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def pull_request_merge_base(repo: Path, base: str, head: str, pr_head: str) -> str:
    """
    The base a pull request's merge commit was built on, or `base` when that is not provable.

    GitHub checks out `refs/pull/N/merge`: the PR head merged into the base branch's current tip.
    The event's `pull_request.base.sha` can be older, so commits that landed on the base branch
    since would read as the PR's own changes: a release's version bump then selects every test.
    When `head` is that merge (two parents, the second the PR head) and `base` is an ancestor of
    the first parent, the first parent is the tested base. A push, a shallow history or any other
    shape keeps `base`, which is never narrower than the truth.
    """
    if not pr_head:
        return base
    try:
        parents = git_text(repo, "rev-list", "--parents", "-n", "1", head).split()[1:]
        if len(parents) != 2 or parents[1] != git_text(repo, "rev-parse", f"{pr_head}^{{commit}}").strip():
            return base
        git(repo, "merge-base", "--is-ancestor", base, parents[0])
    except subprocess.CalledProcessError:
        return base
    return parents[0]
