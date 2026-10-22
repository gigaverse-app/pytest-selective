"""Real Git repositories for tests of tools that read committed trees."""

import re
import subprocess
from pathlib import Path


def write(root: Path, path: str, content: str = "") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


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


def head(root: Path) -> str:
    """Read the just-written fixture ref; let Git handle packed refs and worktrees.

    Fixture commits write a loose HEAD/ref. Reading that result avoids a second
    Git process per commit without substituting a fake commit or repository.
    """
    try:
        value = (root / ".git" / "HEAD").read_text().strip()
        if value.startswith("ref: "):
            value = (root / ".git" / value.removeprefix("ref: ")).read_text().strip()
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
            return value
    except OSError:
        pass
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
