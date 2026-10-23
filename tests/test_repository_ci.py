"""Exercise this repository's actual routing policy against real Git changes."""

from pathlib import Path

import pytest
import yaml

from pytest_selective.ci import LaneConfig, plan
from tests.testing.git_repo import commit, init, write

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("action.yml", True),
        ("actions/plan-lanes/action.yml", True),
        ("actions/plan-lanes/helper.py", True),
        ("README.md", False),
        ("docs/ci.md", False),
        ("docs/benchmarks/data.json", False),
        (".github/dependabot.yml", False),
        (".github/pull_request_template.md", False),
        (".github/workflows/observe-ci.yml", False),
        ("actions/plan-lanes/action.yml", True),
        (".github/test-lanes.json", True),
        (".github/workflows/release.yml", True),
        ("src/sample.py", True),
        ("scripts/tutorial.py", True),
        ("scripts/smoke_distribution.py", True),
        ("pyproject.toml", True),
        ("tests/test_sample.py", True),
        (".github/workflows/ci.yml", True),
        ("uv.lock", True),
        (".pre-commit-config.yaml", True),
        (".python-version", True),
    ],
)
def test_repository_routes_prose_but_preserves_executable_inputs(tmp_path, path, expected):
    init(tmp_path)
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


def test_distribution_smoke_follows_runtime_selection_but_metadata_always_runs():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    distributions = jobs["distributions"]
    assert distributions["needs"] == "select-tests"
    # A failed planner must not skip packaging or its runtime checks.
    assert distributions["if"] == "${{ !cancelled() }}"
    steps = {step["run"]: step for step in distributions["steps"] if "run" in step}
    smoke = steps["uv run --locked python scripts/smoke_distribution.py"]
    # Step admission preserves the default success() check for preceding build steps.
    assert (
        smoke["if"].split()
        == ("${{ needs.select-tests.result != 'success' || fromJSON(needs.select-tests.outputs.lanes).tests }}").split()
    )
    for command in (
        "uv build",
        "uv run --locked twine check --strict dist/*",
        "uv run --locked python scripts/check_metadata.py",
    ):
        assert "if" not in steps[command], command
