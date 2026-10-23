"""Exercise the installed pytest entry point in real, dirty Git repositories."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_selective.impact_graph import git, inventory, policy_fingerprints
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, init, write


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init(tmp_path)
    write(tmp_path, ".gitignore", "__pycache__/\n.pytest_cache/\n")
    write(tmp_path, "pytest.ini", "[pytest]\npythonpath = .\n")
    write(tmp_path, "pkg/__init__.py")
    write(tmp_path, "pkg/value.py", "VALUE = 1\n")
    write(tmp_path, "tests/test_value.py", "from pkg.value import VALUE\ndef test_value(): assert VALUE == 1\n")
    write(tmp_path, "tests/test_other.py", "def test_other(): assert True\n")
    commit(tmp_path)
    configure(tmp_path)
    return tmp_path


def configure(repo: Path) -> None:
    policy = ImpactConfig(test_roots=["tests"], pytest_policy=policy_fingerprints(repo, inventory(repo, "HEAD")))
    write(repo, "selection.json", policy.model_dump_json())
    commit(repo)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Autoload is deliberate: this must exercise distribution entry-point discovery.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=60
    )


@pytest.mark.parametrize("workers", [[], ["-n", "2"]])
def test_native_plugin_selects_regressions_and_preserves_git(repo: Path, workers: list[str]) -> None:
    write(repo, "pkg/value.py", "VALUE = 2\n")
    before = (repo / ".git/index").read_bytes(), git(repo, "rev-parse", "HEAD")
    result = run(repo, "--selective", *workers)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout and "1 passed" not in result.stdout
    assert "pytest-selective:" in result.stdout
    assert before == ((repo / ".git/index").read_bytes(), git(repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize("workers", [[], ["-n", "2"]])
def test_empty_selection_succeeds_but_filters_and_collection_errors_keep_pytest_status(
    repo: Path, workers: list[str]
) -> None:
    result = run(repo, "--selective", *workers)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" not in result.stdout and "none:" in result.stdout
    filtered = run(repo, "--selective", "-k", "does_not_exist", *workers)
    assert filtered.returncode == 5, filtered.stdout + filtered.stderr
    write(repo, "tests/test_bad.py", "this is invalid python\n")
    broken = run(repo, "--selective", *workers)
    assert broken.returncode != 0 and "invalid syntax" in broken.stdout + broken.stderr
    (repo / "tests/test_bad.py").unlink()
    write(repo, "tests/test_bad.py", "raise RuntimeError('collection failure')\n")
    broken = run(repo, "--selective", *workers)
    assert broken.returncode != 0 and "collection failure" in broken.stdout


@pytest.mark.parametrize(
    "options", [[], ["--selective", "--no-selective"], ["--selective", "--selective-base", "missing"]]
)
def test_disabled_and_missing_history_run_complete_suite(repo: Path, options: list[str]) -> None:
    result = run(repo, *options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    if "missing" in options:
        assert "fallback" in result.stdout


@pytest.mark.parametrize("change", ["staged", "untracked", "deleted", "conftest", "lock"])
def test_local_changes_are_observed(repo: Path, change: str) -> None:
    expected = "1 passed"
    code = 0
    if change == "staged":
        write(repo, "pkg/value.py", "VALUE = 1\n# changed\n")
        git(repo, "add", "pkg/value.py")
    elif change == "untracked":
        write(repo, "tests/test_new.py", "def test_new(): assert True\n")
    elif change == "deleted":
        (repo / "pkg/value.py").unlink()
        expected, code = "ModuleNotFoundError", 2
    else:
        write(repo, "conftest.py" if change == "conftest" else "requirements.txt", "# new shared input\n")
        expected = "2 passed"
    result = run(repo, "--selective")
    assert result.returncode == code, result.stdout + result.stderr
    assert expected in result.stdout


def test_config_defaults_cli_override_and_explicit_nodeids(repo: Path) -> None:
    write(repo, "pytest.ini", "[pytest]\npythonpath = .\nselective = true\nselective_config = selection.json\n")
    commit(repo)
    configure(repo)
    write(repo, "pkg/value.py", "VALUE = 1\n# changed\n")
    selected = run(repo, "tests/test_value.py::test_value")
    assert selected.returncode == 0 and "1 passed" in selected.stdout, selected.stdout + selected.stderr
    all_tests = run(repo, "--no-selective")
    assert all_tests.returncode == 0 and "2 passed" in all_tests.stdout
    invalid = run(repo, "--selective-config", "missing.json")
    assert invalid.returncode == 4 and "configuration" in invalid.stderr


def test_non_git_directory_falls_back(repo: Path) -> None:
    other = repo.parent / "outside"
    other.mkdir()
    write(other, "test_ok.py", "def test_ok(): pass\n")
    result = run(other, "--selective")
    assert result.returncode == 0 and "1 passed" in result.stdout, result.stdout + result.stderr
    assert "fallback" in result.stdout


def test_unmodeled_tests_and_doctests_are_never_deselected(repo: Path) -> None:
    write(repo, "outside/test_extra.py", "def test_extra(): pass\n")
    write(repo, "example.txt", ">>> 1 + 1\n2\n")
    commit(repo)
    result = run(repo, "--selective", "--selective-config", "selection.json", "--doctest-glob=*.txt")
    assert result.returncode == 0 and "2 passed" in result.stdout, result.stdout + result.stderr


def test_empty_repository_keeps_no_tests_exit_code(repo: Path) -> None:
    result = run(repo, "--selective", "pkg")
    assert result.returncode == 5, result.stdout + result.stderr


def test_base_includes_committed_and_dirty_changes(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    write(repo, "pkg/value.py", "VALUE = 2\n")
    commit(repo)
    write(repo, "tests/test_new.py", "def test_new(): pass\n")
    result = run(repo, "--selective", "--selective-base", base)
    assert result.returncode == 1 and "1 failed, 1 passed, 1 deselected" in result.stdout, result.stdout + result.stderr


def test_subdirectory_and_src_layout(repo: Path) -> None:
    write(repo, "pytest.ini", "[pytest]\npythonpath = . src\n")
    write(repo, "src/otherpkg/__init__.py")
    write(repo, "src/otherpkg/value.py", "VALUE = 1\n")
    write(repo, "tests/test_src.py", "from otherpkg.value import VALUE\ndef test_src(): assert VALUE == 1\n")
    commit(repo)
    write(repo, "src/otherpkg/value.py", "VALUE = 2\n")
    result = run(repo / "tests", "--selective")
    assert result.returncode == 1 and "1 failed, 2 deselected" in result.stdout, result.stdout + result.stderr


def test_markers_and_custom_python_patterns(repo: Path) -> None:
    write(repo, "pytest.ini", "[pytest]\npythonpath = .\npython_files = check_*.py\nmarkers = slow\n")
    write(
        repo,
        "tests/check_value.py",
        "import pytest\nfrom pkg.value import VALUE\n@pytest.mark.slow\ndef test_value(): assert VALUE == 1\n",
    )
    commit(repo)
    write(repo, "pkg/value.py", "VALUE = 2\n")
    result = run(repo, "--selective")
    assert result.returncode == 1 and "1 failed" in result.stdout, result.stdout + result.stderr
    filtered = run(repo, "--selective", "-m", "not slow")
    assert filtered.returncode == 5, filtered.stdout + filtered.stderr


def test_precollection_full_override_is_not_reselected_by_ini(repo: Path) -> None:
    write(repo, "pytest.ini", "[pytest]\npythonpath = .\nselective = true\n")
    write(repo, "tests/test_other.py", "def test_other(): assert False\n")
    commit(repo)
    configure(repo)
    result = subprocess.run(
        [sys.executable, "-m", "pytest_selective", "run", "--config", "selection.json", "--full", "--", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        timeout=60,
    )
    assert result.returncode == 1 and "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr


def test_nonstandard_pytest_configuration_changes_run_full(repo: Path) -> None:
    write(repo, "custom.ini", "[pytest]\npythonpath = .\n")
    commit(repo)
    write(repo, "custom.ini", "[pytest]\npythonpath = .\n# changed execution policy\n")
    result = run(repo, "--selective", "-c", "custom.ini")
    assert result.returncode == 0 and "2 passed" in result.stdout, result.stdout + result.stderr
