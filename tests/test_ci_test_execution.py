"""The CI consumer executes the shared plan without collecting unrelated tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.testing.git_repo import write

# gv:test-dependency: scripts/run_ci_tests.py
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_ci_tests.py"


@pytest.mark.parametrize(
    "result, mode, files, expected",
    [
        ("success", "scoped", '["tests/test_selected.py"]', 0),
        ("success", "none", "[]", 0),
        ("success", "full", "[]", 1),
        ("failure", "none", "[]", 1),
        ("success", "scoped", "[]", 1),
        ("success", "scoped", "invalid-json", 1),
        ("success", "unknown", "[]", 1),
    ],
)
def test_execution_respects_selection_and_falls_back_on_missing_proof(tmp_path, result, mode, files, expected):
    write(tmp_path, "tests/test_selected.py", "def test_selected(): pass\n")
    write(tmp_path, "tests/test_unrelated.py", "def test_unrelated(): assert False\n")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "-q"],
        cwd=tmp_path,
        env={
            **os.environ,
            "CI_PLANNER_RESULT": result,
            "CI_TEST_MODE": mode,
            "CI_TEST_FILES": files,
            "CI_COVERAGE": "false",
        },
        capture_output=True,
        text=True,
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    if mode == "none" and result == "success":
        assert "pytest was not started" in completed.stdout
    elif expected == 0:
        assert "1 passed" in completed.stdout


def test_selected_paths_with_spaces_are_passed_as_single_arguments(tmp_path):
    write(tmp_path, "tests/test with spaces.py", "def test_selected(): pass\n")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "-q"],
        cwd=tmp_path,
        env={
            **os.environ,
            "CI_PLANNER_RESULT": "success",
            "CI_TEST_MODE": "scoped",
            "CI_TEST_FILES": json.dumps(["tests/test with spaces.py"]),
            "CI_COVERAGE": "false",
        },
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
