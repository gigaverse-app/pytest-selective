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
