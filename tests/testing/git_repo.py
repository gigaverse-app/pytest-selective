"""Real Git repositories for tests of tools that read committed trees."""

import atexit
import shutil
import subprocess
import tempfile
from pathlib import Path

# Starting a process costs ~40 ms on Windows, so fixtures avoid Git processes whose result
# is known: a fresh repository is a copy, and a new commit's id is in its ref file.
_template: Path | None = None


def write(root: Path, path: str, content: str = "") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def init(root: Path) -> None:
    """A fresh repository at `root`, copied from one `git init` per test process."""
    global _template
    if _template is None:
        directory = Path(tempfile.mkdtemp(prefix="pytest-selective-git-template-"))
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(directory)], check=True, capture_output=True)
        _template = directory / ".git"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_template, root / ".git")


def head(root: Path) -> str:
    """The checked-out commit, read from Git's files when it is a loose ref."""
    git_dir = root / ".git"
    if git_dir.is_dir():
        reference = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not reference.startswith("ref: "):
            return reference
        loose = git_dir / reference.removeprefix("ref: ")
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip()
    # Packed refs, reftable and linked worktrees keep the id elsewhere.
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def commit(root: Path, message: str = "fixture") -> str:
    """Commit the whole working tree, ignoring the developer's identity and hooks, and return HEAD."""
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "core.hooksPath=",
            # Disposable fixture histories need no automatic background maintenance.
            "-c",
            "maintenance.auto=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
    )
    return head(root)
