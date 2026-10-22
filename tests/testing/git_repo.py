"""Real Git repositories for tests of tools that read committed trees."""

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
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
    )
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
