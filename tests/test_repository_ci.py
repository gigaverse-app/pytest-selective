"""Exercise this repository's actual routing policy against real Git changes."""

import subprocess
from pathlib import Path

import pytest

from pytest_selective.ci import LaneConfig, plan
from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("README.md", False),
        ("docs/ci.md", False),
        ("docs/benchmarks/data.json", False),
        (".github/dependabot.yml", False),
        (".github/pull_request_template.md", False),
        (".github/workflows/observe-ci.yml", False),
        (".github/actions/plan-lanes/action.yml", True),
        (".github/test-lanes.json", True),
        (".github/workflows/release.yml", True),
        ("src/sample.py", True),
        ("scripts/tutorial.py", True),
        ("tests/test_sample.py", True),
        (".github/workflows/ci.yml", True),
        ("uv.lock", True),
        (".pre-commit-config.yaml", True),
        (".python-version", True),
    ],
)
def test_repository_routes_prose_but_preserves_executable_inputs(tmp_path, path, expected):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/sample.py", "VALUE = 1")
    write(tmp_path, "tests/test_sample.py", "from sample import VALUE\ndef test_value(): assert VALUE")
    base = commit(tmp_path)
    write(tmp_path, path, "# changed input\n")
    head = commit(tmp_path)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    result = plan(tmp_path, config, base, head)
    assert result.lanes == {"tests": expected}, result.reason
    assert plan(tmp_path, config, base, head, full=True).lanes == {"tests": True}
    assert plan(tmp_path, config, "missing-base", head).lanes == {"tests": True}
