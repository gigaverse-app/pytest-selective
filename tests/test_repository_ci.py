"""Exercise this repository's actual routing policy against real Git changes."""

# gv:test-dependency: .github/test-lanes.json
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/observe-ci.yml
# gv:test-dependency: .github/workflows/public-actions.yml

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
    "path, tests, contracts, package",
    [
        ("action.yml", True, True, True),
        ("actions/plan-lanes/action.yml", True, True, True),
        ("actions/plan-lanes/helper.py", True, True, True),
        ("actions/helper.py", True, True, True),
        ("actions/README.md", False, False, False),
        # The distributions embed README.md and LICENSE, so only the package lane rebuilds them.
        ("README.md", False, False, True),
        ("LICENSE", False, False, True),
        ("docs/ci.md", False, False, False),
        ("docs/benchmarks/data.json", False, False, False),
        # Read the Docs dependencies are not the test environment.
        ("documentation/requirements.txt", False, False, False),
        ("documentation/requirements.in", False, False, False),
        ("mkdocs.yml", False, False, False),
        # The one-prompt agent setup and llms.txt are published documentation.
        ("skills/pytest-selective/SKILL.md", False, False, False),
        ("documentation/llms.txt", False, False, False),
        ("documentation/check_site.py", False, False, False),
        ("actions/validation-gate/action.yml", True, True, True),
        (".github/dependabot.yml", False, False, False),
        (".github/pull_request_template.md", False, False, False),
        (".github/workflows/observe-ci.yml", False, False, False),
        (".github/test-lanes.json", True, True, True),
        (".github/workflows/release.yml", True, True, True),
        ("src/sample.py", True, True, True),
        ("scripts/tutorial.py", True, True, True),
        ("scripts/smoke_distribution.py", True, True, True),
        ("pyproject.toml", True, True, True),
        # The fixture's only test: every graph test is affected by imports, which admits only the
        # lanes holding graph tests; the package and contract lanes hold none here.
        ("tests/test_sample.py", True, False, False),
        ("tests/testing/git_repo.py", True, True, False),
        ("contracts/selection/selection.qnt", False, True, False),
        ("contracts/selection/conftest.py", False, True, False),
        (".github/workflows/ci.yml", True, True, True),
        ("uv.lock", True, True, True),
        (".pre-commit-config.yaml", True, True, True),
        (".python-version", True, True, True),
    ],
)
def test_repository_routes_prose_but_preserves_executable_inputs(tmp_path, path, tests, contracts, package):
    init(tmp_path)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/sample.py", "VALUE = 1")
    write(tmp_path, "tests/test_sample.py", "from sample import VALUE\ndef test_value(): assert VALUE")
    base = commit(tmp_path)
    write(tmp_path, path, "# changed input\n")
    head = commit(tmp_path)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    result = plan(tmp_path, config, base, head)
    assert result.lanes == {"tests": tests, "contracts": contracts, "package": package}, result.reason
    every_lane = {"tests": True, "contracts": True, "package": True}
    assert plan(tmp_path, config, base, head, full=True).lanes == every_lane
    assert plan(tmp_path, config, "missing-base", head).lanes == every_lane


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


def test_documentation_only_commit_selects_no_lane_and_no_test_file(tmp_path):
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
    lanes = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    assert plan(tmp_path, lanes, base, docs).lanes == dict.fromkeys(lanes.lanes, False)
    assert plan(tmp_path, lanes, base, readme).lanes == {"tests": False, "contracts": False, "package": True}
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
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


@pytest.mark.parametrize("name", ["ci.yml", "public-actions.yml"])
def test_self_adoption_keeps_weekly_full_checkpoints(name):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    assert workflow[True]["schedule"]
    planner = workflow["jobs"]["select-tests"]
    selection = next(step for step in planner["steps"] if step.get("uses") == "./actions/plan-lanes")
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
    # The CLI the readers run in a subprocess. The plugin itself reaches every test (below).
    write(tmp_path, "src/pytest_selective/__main__.py", "VALUE = 2")
    head = commit(tmp_path)
    lanes = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
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
    lanes = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        result = affected(tmp_path, base, head, file_config(lanes), cache)
    assert result.selected == ["tests/test_unrelated.py"], result.reasons
