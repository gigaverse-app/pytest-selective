import glob
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_selective.impact_declarations import _path_pattern
from pytest_selective.impact_graph import inventory
from tests.testing.git_repo import commit, write


@pytest.mark.parametrize("pattern", ["**", "**/*.py", "*.py", "a/**", "a/**/b?.py", "**/**/b*.py", "a/*/b.py"])
@pytest.mark.skipif(sys.version_info < (3, 14), reason="stdlib glob.translate oracle requires Python 3.14")
def test_portable_globs_agree_with_original_stdlib_contract(pattern: str) -> None:
    oracle = re.compile(glob.translate(pattern, recursive=True, include_hidden=True, seps="/"))
    portable = _path_pattern(pattern)
    for path in [
        "b.py",
        "a/b.py",
        "a/b1.py",
        "a/x/b2.py",
        "a/.hidden/b.py",
        ".hidden.py",
        "a/x/y/b.py",
        "a/new\nline.py",
    ]:
        assert bool(portable.fullmatch(path)) == bool(oracle.fullmatch(path)), (pattern, path)


def test_explicit_repository_wins_over_inherited_hook_git_environment(tmp_path: Path, monkeypatch) -> None:
    requested = tmp_path / "requested"
    other = tmp_path / "hook-repository"
    for root in (requested, other):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        write(root, f"{root.name}.py", "VALUE = 1")
        commit(root)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert set(inventory(requested, "HEAD").files) == {"requested.py"}


@pytest.mark.parametrize("revision", ["--all", "--help", "--output=unexpected-file"])
def test_option_shaped_revisions_cannot_be_interpreted_as_git_options(tmp_path: Path, revision: str) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "sample.py", "VALUE = 1")
    commit(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        inventory(tmp_path, revision)
    assert not (tmp_path / "unexpected-file").exists()
