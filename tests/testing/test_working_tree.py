"""Local selection runs real dirty repositories without staging the user's work."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_selective.impact_cli import main
from pytest_selective.impact_graph import git
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, init, write


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    init(root)
    write(root, ".gitignore", "__pycache__/\n.pytest_cache/\n.test-impact/\n")
    write(root, "pkg/__init__.py")
    write(root, "pkg/value.py", "VALUE = 1\n")
    write(root, "tests/test_value.py", "from pkg.value import VALUE\ndef test_value(): assert VALUE == 1\n")
    write(root, "tests/test_other.py", "def test_other(): assert True\n")
    write(root, "selection.json", ImpactConfig(test_roots=["tests"]).model_dump_json())
    commit(root)
    return root


@pytest.mark.parametrize("change", ["unstaged", "staged", "deleted", "renamed", "untracked"])
def test_working_tree_selection_preserves_index_and_head(repo: Path, tmp_path: Path, change: str) -> None:
    if change == "deleted":
        (repo / "pkg/value.py").unlink()
    elif change == "renamed":
        (repo / "pkg/value.py").rename(repo / "pkg/renamed.py")
    elif change == "untracked":
        write(repo, "tests/test_new.py", "def test_new(): assert True\n")
    else:
        write(repo, "pkg/value.py", "VALUE = 2\n")
        if change == "staged":
            git(repo, "add", "pkg/value.py")
    index_before = (repo / ".git/index").read_bytes()
    head_before = git(repo, "rev-parse", "HEAD")
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(repo / "selection.json"),
                "--working-tree",
                "--base",
                "HEAD",
                "--cache",
                str(tmp_path / "cache.sqlite3"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text())
    assert report["selected"] == ["tests/test_new.py" if change == "untracked" else "tests/test_value.py"]
    assert (repo / ".git/index").read_bytes() == index_before
    assert git(repo, "rev-parse", "HEAD") == head_before


def run_local(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest_selective",
            "run",
            "--repo",
            str(repo),
            "--config",
            str(repo / "selection.json"),
            *args,
        ],
        cwd=repo,
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(repo)),
        capture_output=True,
        text=True,
    )


def test_local_runner_catches_regression_without_importing_unaffected_tests(repo: Path) -> None:
    write(repo, "tests/test_other.py", "raise RuntimeError('unaffected module was imported')\n")
    commit(repo)
    write(repo, "pkg/value.py", "VALUE = 2\n")
    result = run_local(repo, "--", "-q")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert "unaffected module was imported" not in result.stdout


def test_local_runner_skips_pytest_on_empty_plan_but_full_override_executes(repo: Path) -> None:
    write(repo, "tests/test_other.py", "def test_other(): assert False\n")
    commit(repo)
    result = run_local(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No affected tests" in result.stdout
    full = run_local(repo, "--full", "--", "-q")
    assert full.returncode == 1
    assert "1 failed, 1 passed" in full.stdout


def test_local_runner_missing_history_runs_all_tests(repo: Path) -> None:
    result = run_local(repo, "--base", "missing-history", "--", "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert "full-suite fallback" in result.stderr


def test_force_added_ignored_test_is_still_a_local_input(repo: Path, tmp_path: Path) -> None:
    write(repo, ".gitignore", "tests/test_new.py\n")
    commit(repo)
    write(repo, "tests/test_new.py", "def test_new(): assert False\n")
    git(repo, "add", "--force", "tests/test_new.py")
    index_before = (repo / ".git/index").read_bytes()
    result = run_local(repo, "--", "-q")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert (repo / ".git/index").read_bytes() == index_before


def test_working_tree_default_base_is_current_head(repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(repo / "selection.json"),
                "--working-tree",
                "--cache",
                str(tmp_path / "cache.sqlite3"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["selected"] == []
