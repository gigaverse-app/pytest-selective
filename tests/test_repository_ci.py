"""Exercise this repository's actual routing policy against real Git changes."""

# gv:test-dependency: .github/test-lanes.json
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/observe-ci.yml

from contextlib import closing
from pathlib import Path

import pytest
import yaml

from pytest_selective.ci import LaneConfig, plan
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_selection import affected
from scripts.ci_file_config import file_config
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


def test_pytest_jobs_consume_the_public_actions_shared_file_plan():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    planner = jobs["select-tests"]
    file_step = next(step for step in planner["steps"] if step.get("id") == "files")
    assert file_step["uses"] == "./"
    assert planner["outputs"]["mode"] == "${{ steps.files.outputs.mode }}"
    assert planner["outputs"]["files"] == "${{ steps.paths.outputs.files }}"
    for job in ("tests", "pytest-minimum"):
        execution = next(step for step in jobs[job]["steps"] if "scripts/run_ci_tests.py" in step.get("run", ""))
        assert execution["env"]["CI_PLANNER_RESULT"] == "${{ needs.select-tests.result }}"
        assert execution["env"]["CI_TEST_MODE"] == "${{ needs.select-tests.outputs.mode }}"
        assert execution["env"]["CI_TEST_FILES"] == "${{ needs.select-tests.outputs.files }}"
    observer = yaml.safe_load((ROOT / ".github/workflows/observe-ci.yml").read_text())
    assert observer["jobs"]["report"]["with"]["test-selection-artifact"] == "test-impact-explanation"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("README.md", []),
        ("docs/guide.md", []),
        (".github/PULL_REQUEST_TEMPLATE/change.md", []),
        ("src/sample.py", ["tests/test_sample.py"]),
        (".github/workflows/ci.yml", ["tests/test_other.py", "tests/test_sample.py"]),
        ("uv.lock", ["tests/test_other.py", "tests/test_sample.py"]),
        ("requirements.txt", ["tests/test_other.py", "tests/test_sample.py"]),
        ("scripts/helper.py", ["tests/test_other.py", "tests/test_sample.py"]),
    ],
)
def test_repository_file_plan_skips_docs_and_follows_imports(tmp_path, path, expected):
    init(tmp_path)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/sample.py", "VALUE = 1")
    write(tmp_path, "tests/test_sample.py", "from sample import VALUE\ndef test_value(): assert VALUE")
    write(tmp_path, "tests/test_other.py", "def test_other(): pass")
    base = commit(tmp_path)
    write(tmp_path, path, "# changed input\n")
    head = commit(tmp_path)
    lanes = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        result = affected(tmp_path, base, head, file_config(lanes), cache)
    assert result.selected == expected, result.reasons


@pytest.mark.parametrize(
    "reader",
    ["tests/testing/test_pytest_plugin.py", "tests/testing/test_working_tree.py", "tests/test_tutorial.py"],
)
def test_subprocess_plugin_readers_declare_their_runtime(tmp_path, reader):
    init(tmp_path)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/pytest_selective/__init__.py")
    write(tmp_path, "src/pytest_selective/plugin.py", "VALUE = 1")
    write(tmp_path, "src/pytest_selective/__main__.py", "VALUE = 1")
    write(tmp_path, "scripts/tutorial.py", (ROOT / "scripts/tutorial.py").read_text())
    write(tmp_path, reader, (ROOT / reader).read_text())
    write(tmp_path, "tests/test_unrelated.py", "def test_unrelated(): pass")
    base = commit(tmp_path)
    write(tmp_path, "src/pytest_selective/plugin.py", "VALUE = 2")
    head = commit(tmp_path)
    lanes = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        result = affected(tmp_path, base, head, file_config(lanes), cache)
    assert result.selected == [reader], result.reasons
