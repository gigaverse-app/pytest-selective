"""Local selection runs real dirty repositories without staging the user's work."""

# gv:test-dependency: src/pytest_selective/__main__.py
# gv:test-dependency: src/pytest_selective/plugin.py

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pytest_selective.impact_cli import main
from pytest_selective.impact_graph import git
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.pytest_expansion import worktree_snapshot
from pytest_selective.working_tree import snapshot_working_tree
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


@pytest.mark.parametrize("python_only", [False, True], ids=["planner", "expansion"])
@pytest.mark.parametrize("layout", ["normal", "split-index", "linked-worktree"])
def test_private_snapshots_preserve_index_and_requested_file_scope(
    repo: Path, tmp_path: Path, python_only: bool, layout: str
) -> None:
    """Snapshots retain staged inputs, update their declared scope and never stage user edits."""
    write(repo, "data.txt", "committed\n")
    write(repo, ".gitignore", "ignored.py\n")
    commit(repo)
    if layout == "linked-worktree":
        linked = tmp_path / "linked"
        git(repo, "worktree", "add", "-b", "snapshot-test", str(linked))
        repo = linked
    write(repo, "data.txt", "staged\n")
    write(repo, "ignored.py", "VALUE = 'staged'\n")
    git(repo, "add", "--force", "data.txt", "ignored.py")
    if layout == "split-index":
        git(repo, "update-index", "--split-index")
        assert git(repo, "rev-parse", "--shared-index-path").strip()
    write(repo, "data.txt", "working\n")
    write(repo, "ignored.py", "VALUE = 'working'\n")
    write(repo, "new.py", "VALUE = 2\n")
    write(repo, "new.txt", "new data\n")
    (repo / "pkg/value.py").unlink()
    index = repo / git(repo, "rev-parse", "--git-path", "index").decode().strip()
    index_before = index.read_bytes()
    head_before = git(repo, "rev-parse", "HEAD")

    tree = worktree_snapshot(repo) if python_only else snapshot_working_tree(repo)

    assert git(repo, "show", f"{tree}:ignored.py") == b"VALUE = 'working'\n"
    assert git(repo, "show", f"{tree}:new.py") == b"VALUE = 2\n"
    assert git(repo, "show", f"{tree}:data.txt") == (b"staged\n" if python_only else b"working\n")
    paths = git(repo, "ls-tree", "-r", "--name-only", tree).decode().splitlines()
    assert ("new.txt" in paths) is not python_only
    assert "pkg/value.py" not in paths
    assert index.read_bytes() == index_before
    assert git(repo, "rev-parse", "HEAD") == head_before


@pytest.mark.parametrize("python_only", [False, True], ids=["planner", "expansion"])
def test_private_snapshot_detects_same_size_edits_in_the_index_timestamp_window(repo: Path, python_only: bool) -> None:
    """Copying the index must preserve Git's racy-clean check, not make a dirty file look older."""
    git(repo, "config", "core.trustctime", "false")
    git(repo, "config", "core.checkstat", "minimal")
    source = repo / "pkg/value.py"
    timestamp = int(time.time()) - 10
    os.utime(source, (timestamp, timestamp))
    git(repo, "add", "pkg/value.py")
    index = repo / ".git/index"
    os.utime(index, (timestamp, timestamp))
    index_before = index.read_bytes()
    write(repo, "pkg/value.py", "VALUE = 2\n")
    os.utime(source, (timestamp, timestamp))

    tree = worktree_snapshot(repo) if python_only else snapshot_working_tree(repo)

    assert git(repo, "show", f"{tree}:pkg/value.py") == b"VALUE = 2\n"
    assert index.read_bytes() == index_before


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_planner_snapshot_observes_edits_hidden_by_index_flags(repo: Path, flag: str) -> None:
    """Selection must see tracked local edits even if Git's stat-cache hints hide them."""
    git(repo, "update-index", flag, "pkg/value.py")
    write(repo, "pkg/value.py", "VALUE = 2\n")
    index = repo / ".git/index"
    index_before = index.read_bytes()

    tree = snapshot_working_tree(repo)

    assert git(repo, "show", f"{tree}:pkg/value.py") == b"VALUE = 2\n"
    assert index.read_bytes() == index_before


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


@pytest.mark.skipif(sys.platform != "win32", reason="Exercise the actual Windows command-line limit")
@pytest.mark.parametrize("full_plan", [False, True])
def test_large_local_selection_runs_tests_instead_of_exceeding_command_limit(repo: Path, full_plan: bool) -> None:
    for number in range(500):
        name = f"tests/test_{number:04d}_" + "long_realistic_suite_name_" * 3 + ".py"
        write(repo, name, "from pkg.value import VALUE\ndef test_ok(): assert VALUE > 0\n")
    write(repo, "tests/test_other.py", "def test_other(): assert False\n")
    commit(repo)
    if full_plan:
        write(repo, "requirements.txt", "# changed environment\n")
    else:
        write(repo, "pkg/value.py", "VALUE = 1\n# changed source\n")
    result = run_local(repo, "--", "-q")
    # The deliberately unaffected failing test proves the scoped overflow also
    # executes the complete roots, and the pytest failure status is preserved.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 501 passed" in result.stdout
    assert "Traceback" not in result.stderr
    if full_plan:
        assert "command line is too long" not in result.stderr
    else:
        assert "command line is too long" in result.stderr
        assert "full-suite fallback" in result.stderr


@pytest.mark.parametrize("failure", [errno.E2BIG, errno.EACCES, errno.ENAMETOOLONG])
@pytest.mark.parametrize("retry_fails", [False, True])
def test_local_spawn_errors_retry_only_oversized_commands_once(repo: Path, failure: int, retry_fails: bool) -> None:
    write(repo, "pkg/value.py", "VALUE = 2\n")
    original_run = subprocess.run
    attempts: list[list[str]] = []
    initial_error = OSError(failure, "spawn failed")
    retry_error = OSError(errno.E2BIG, "roots also too large")

    def spawn(command, **kwargs):
        if command[1:3] != ["-m", "pytest"]:
            return original_run(command, **kwargs)
        attempts.append(command)
        if len(attempts) == 1:
            raise initial_error
        if retry_fails:
            raise retry_error
        return subprocess.CompletedProcess(command, 5)

    with patch.object(subprocess, "run", side_effect=spawn):
        arguments = ["run", "--repo", str(repo), "--config", str(repo / "selection.json"), "--", "-q"]
        if failure == errno.E2BIG and not retry_fails:
            assert main(arguments) == 5
        else:
            with pytest.raises(OSError) as error:
                main(arguments)
            assert error.value is (retry_error if failure == errno.E2BIG else initial_error)
    assert attempts[0][3:] == ["-p", "selective", "--no-selective", "tests/test_value.py", "-q"]
    if failure == errno.E2BIG:
        assert len(attempts) == 2
        assert attempts[1][3:] == ["-p", "selective", "--no-selective", "tests", "-q"]
    else:
        assert len(attempts) == 1


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
