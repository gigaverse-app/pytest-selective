"""Fixture repositories remain real, independent Git histories."""

import subprocess
from pathlib import Path

from tests.testing.git_repo import commit, init, write


def test_minimal_template_keeps_independent_committed_trees(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        init(root)
        assert not (root / ".git" / "hooks").exists()
    write(first, "module.py", "value = 1\n")
    before = commit(first)
    write(first, "module.py", "value = 2\n")
    after = commit(first)
    assert before != after
    assert subprocess.check_output(["git", "-C", str(first), "show", f"{before}:module.py"], text=True) == "value = 1\n"
    write(second, "other.py", "value = 3\n")
    commit(second)
    assert (
        subprocess.check_output(["git", "-C", str(second), "ls-tree", "--name-only", "HEAD"], text=True) == "other.py\n"
    )
