"""Exercise this repository's actual routing policy against real Git changes."""

# gv:test-dependency: .github/test-lanes.json
# gv:test-dependency: .github/plan-lanes.json
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/observe-ci.yml
# gv:test-dependency: .github/workflows/public-actions.yml
# gv:test-dependency: .github/workflows/weekly-checkpoint.yml

import json
import tomllib
from contextlib import closing
from pathlib import Path

import pytest
import yaml

from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_graph import GraphCache, matches
from pytest_selective.impact_selection import affected
from scripts.ci_file_config import file_config
from tests.testing.git_repo import commit, init, write

ROOT = Path(__file__).resolve().parents[1]
# CI plans lanes with CI-esta from the workflow and this file, which extends it.
LANE_FILE = ROOT / ".github/test-lanes.json"
# The complete lane file: file selection's graph and global inputs, and public-actions.yml's plan-lanes planner.
PLAN_LANES = ROOT / ".github/plan-lanes.json"


def ci_jobs() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]


def lane_rules() -> dict[str, dict]:
    return {rule["name"]: rule for rule in json.loads(LANE_FILE.read_text())["rules"]}


def test_lane_file_extends_the_workflow_and_names_the_tests_lanes_roots():
    document = json.loads(LANE_FILE.read_text())
    assert document["extends"] == "workflow"
    # The tests lane's jobs run `pytest-selective execute-plan`, which collects pytest's testpaths. CI-esta reads roots
    # only from pytest commands, so without this override a changed test would reach no lane.
    testpaths = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]["testpaths"]
    assert {name: Lane.model_validate(lane).roots for name, lane in document["lanes"].items()} == {"tests": testpaths}
    jobs = ci_jobs()
    for name in ("tests", "pytest-minimum"):
        commands = [step.get("run", "") for step in jobs[name]["steps"]]
        assert any("pytest-selective execute-plan" in command for command in commands), name


def test_python_environment_rule_keeps_the_locked_environment_global_but_not_the_docs_site():
    rule = lane_rules()["python-environment"]
    assert rule["select"] == ["all"]
    graph = LaneConfig.model_validate_json(PLAN_LANES.read_text()).graph
    assert set(graph.global_inputs) <= set(rule["when"])
    # Read the Docs dependencies are not the test environment (#70).
    for path in ("documentation/requirements.txt", "documentation/requirements.in"):
        assert not matches(path, rule["when"]), path


def test_distribution_smoke_rule_follows_the_step_gated_on_the_planned_tests_lane():
    rule = lane_rules()["distribution-smoke"]
    steps = {step["run"]: step for step in ci_jobs()["distributions"]["steps"] if "run" in step}
    smoke = steps["uv run --locked python scripts/smoke_distribution.py"]
    # The step runs only when the tests lane is planned, so the script that is its only input must plan that lane.
    assert "fromJSON(needs.select-tests.outputs.planned).tests" in smoke["if"]
    assert rule["when"] == ["scripts/smoke_distribution.py"]
    assert rule["select"] == ["lane:tests"]


def test_quality_checks_the_lane_routing_and_wiring_with_ci_esta():
    quality = ci_jobs()["quality"]
    # Never lane-gated: the routing check runs on every change, including the documentation-only ones it pins.
    assert "if" not in quality and "needs" not in quality
    commands = [step.get("run", "") for step in quality["steps"]]
    routing = next(command for command in commands if "scripts/check_lane_routing.py" in command)
    assert "ci-esta[selection]>=1.12.0" in routing
    check = next(command for command in commands if "ci-esta check-workflow" in command)
    assert "--lanes .github/test-lanes.json" in check


def test_distributions_follow_the_package_lane_and_smoke_follows_runtime_selection():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    distributions = jobs["distributions"]
    assert distributions["needs"] == "select-tests"
    # A failed planner must not skip packaging or its runtime checks.
    assert (
        distributions["if"].split()
        == (
            "${{ always() && !cancelled() && (needs.select-tests.result != 'success' || "
            "fromJSON(needs.select-tests.outputs.lanes).package) }}"
        ).split()
    )
    steps = {step["run"]: step for step in distributions["steps"] if "run" in step}
    smoke = steps["uv run --locked python scripts/smoke_distribution.py"]
    # Step admission preserves the default success() check for preceding build steps. It follows the plan before
    # lane reuse: reused test proof does not stand in for smoking the distributions built in this run.
    assert (
        smoke["if"].split()
        == (
            "${{ needs.select-tests.result != 'success' || fromJSON(needs.select-tests.outputs.planned).tests }}"
        ).split()
    )
    for command in (
        "uv build",
        "uv run --locked twine check --strict dist/*",
        "uv run --locked python scripts/check_metadata.py",
    ):
        assert "if" not in steps[command], command


def test_documentation_only_commit_selects_no_test_file(tmp_path):
    init(tmp_path)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/sample.py", "VALUE = 1")
    write(tmp_path, "tests/test_sample.py", "from sample import VALUE\ndef test_value(): assert VALUE")
    documentation = ("docs/ci.md", "documentation/requirements.in", "documentation/requirements.txt", "mkdocs.yml")
    for path in (*documentation, "README.md"):
        write(tmp_path, path, "# documentation\n")
    base = commit(tmp_path)
    # A Read the Docs dependency bump (#70) together with prose pages (#65) in one commit.
    for path in documentation:
        write(tmp_path, path, "# changed documentation\n")
    docs = commit(tmp_path)
    # The package README is embedded in both distributions, so it rebuilds them without running tests.
    write(tmp_path, "README.md", "# changed package description\n")
    readme = commit(tmp_path)
    # The lanes these commits plan are pinned by scripts/check_lane_routing.py.
    lanes = LaneConfig.model_validate_json(PLAN_LANES.read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        assert affected(tmp_path, base, docs, file_config(lanes), cache).selected == []
        files = affected(tmp_path, base, readme, file_config(lanes), cache)
    assert files.selected == [], files.reasons


def test_pytest_jobs_consume_the_public_actions_shared_file_plan():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    planner = jobs["select-tests"]
    file_step = next(step for step in planner["steps"] if step.get("id") == "files")
    assert file_step["uses"] == "./"
    assert planner["outputs"]["mode"] == "${{ steps.files.outputs.mode }}"
    assert planner["outputs"]["files"] == "${{ steps.files.outputs.test_roots_json }}"
    for job in ("tests", "pytest-minimum"):
        execution = next(
            step
            for step in jobs[job]["steps"]
            if any(
                command in step.get("run", "")
                for command in ("scripts/run_ci_tests.py", "pytest-selective execute-plan")
            )
        )
        assert execution["env"]["CI_PLANNER_RESULT"] == "${{ needs.select-tests.result }}"
        assert execution["env"]["CI_TEST_MODE"] == "${{ needs.select-tests.outputs.mode }}"
        assert execution["env"]["CI_TEST_FILES"] == "${{ needs.select-tests.outputs.files }}"
    observer = yaml.safe_load((ROOT / ".github/workflows/observe-ci.yml").read_text())
    assert observer["jobs"]["report"]["with"]["test-selection-artifact"] == "test-impact-explanation"


@pytest.mark.parametrize(
    "name, planner",
    [
        ("ci.yml", "gigaverse-app/ci-esta/actions/plan-work@v1"),
        # The public action smoke plans with the repository's own plan-lanes action, selectively on every change.
        ("public-actions.yml", "./actions/plan-lanes"),
    ],
)
def test_self_adoption_keeps_weekly_full_checkpoints(name, planner):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    assert "workflow_dispatch" in workflow[True]
    assert "schedule" not in workflow[True]
    checkpoint = yaml.safe_load((ROOT / ".github/workflows/weekly-checkpoint.yml").read_text())
    events = checkpoint.get("on", checkpoint.get(True))
    assert events["schedule"]
    assert "workflow_dispatch" in events
    assert checkpoint["permissions"]["actions"] == "write"
    action = checkpoint["jobs"]["dispatch"]["steps"][0]
    assert action["uses"] == "gigaverse-app/ci-esta/actions/weekly-checkpoint@v1"
    assert name in json.loads(action["with"]["workflows"])
    selection = next(step for step in workflow["jobs"]["select-tests"]["steps"] if step.get("uses") == planner)
    assert selection.get("with", {}).get("full", "auto") == "auto"


def test_tutorial_executes_through_selected_pytest_without_a_second_matrix_run():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    commands = [step.get("run", "") for step in jobs["tests"]["steps"]]
    assert any("pytest-selective execute-plan" in command for command in commands)
    assert not any("scripts/tutorial.py" in command for command in commands)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("README.md", []),
        ("docs/guide.md", []),
        (".github/PULL_REQUEST_TEMPLATE/change.md", []),
        ("src/sample.py", ["tests/test_sample.py"]),
        (".github/workflows/ci.yml", ["tests/test_other.py", "tests/test_sample.py"]),
        ("uv.lock", ["tests/test_other.py", "tests/test_sample.py"]),
        # This uv-locked repository declares its environment files; requirements files are documentation's.
        ("requirements.txt", []),
        ("documentation/requirements.txt", []),
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
    lanes = LaneConfig.model_validate_json(PLAN_LANES.read_text())
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
    # The CLI the readers run in a subprocess. The plugin itself reaches every test (below).
    write(tmp_path, "src/pytest_selective/__main__.py", "VALUE = 2")
    head = commit(tmp_path)
    lanes = LaneConfig.model_validate_json(PLAN_LANES.read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        result = affected(tmp_path, base, head, file_config(lanes), cache)
    assert result.selected == [reader], result.reasons


def test_the_repositorys_own_pytest_plugin_reaches_every_test(tmp_path):
    # pyproject.toml registers pytest_selective.plugin as a pytest11 entry point, so the installed
    # project loads it into every session, including tests that never import it.
    init(tmp_path)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/pytest_selective/__init__.py")
    write(tmp_path, "src/pytest_selective/plugin.py", "VALUE = 1")
    write(tmp_path, "tests/test_unrelated.py", "def test_unrelated(): pass")
    base = commit(tmp_path)
    write(tmp_path, "src/pytest_selective/plugin.py", "VALUE = 2")
    head = commit(tmp_path)
    lanes = LaneConfig.model_validate_json(PLAN_LANES.read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        result = affected(tmp_path, base, head, file_config(lanes), cache)
    assert result.selected == ["tests/test_unrelated.py"], result.reasons
