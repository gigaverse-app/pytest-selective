# gv:test-dependency: actions/test-impact/action.yml
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from pytest_selective import impact_cli
from pytest_selective.impact_explanation import (
    CYCLE_MIN_FILES,
    FUNNEL_MIN_TESTS,
    WIDENED_MIN_TESTS,
    dependent_tests,
    explain,
    startup_floor,
)
from pytest_selective.impact_graph import EdgeEvidence, GraphCache
from pytest_selective.impact_models import (
    ChangedFileReach,
    DependencyRule,
    EdgeKind,
    ExplanationUnavailable,
    FloorChange,
    FloorCycle,
    FloorEntry,
    ImpactConfig,
    ImpactReport,
    PathStep,
    SelectionExplanation,
)
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write

#: Enough test files behind one module for it to count as a funnel, and to widen a blast radius.
HUB_TESTS = max(FUNNEL_MIN_TESTS, WIDENED_MIN_TESTS) + 5
UNRELATED_TESTS = 3
HUB_IMPORT = "from app.hub import VALUE\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "src/app/__init__.py")
    write(root, "src/app/leaf.py", "VALUE = 1\n")
    write(root, "src/app/helper.py", "HELP = 1\n")
    write(root, "src/app/hub.py", "import os\n\nfrom app.leaf import VALUE\n")
    for number in range(HUB_TESTS):
        write(root, f"tests/hub/test_hub_{number}.py", HUB_IMPORT + "def test_value(): assert VALUE\n")
    write(root, "tests/test_leaf.py", "from app.leaf import VALUE\ndef test_leaf(): assert VALUE\n")
    write(root, "tests/test_helper.py", "from app.helper import HELP\ndef test_helper(): assert HELP\n")
    for number in range(UNRELATED_TESTS):
        write(root, f"tests/other/test_other_{number}.py", "def test_other(): assert True\n")
    return root


@pytest.fixture
def config() -> ImpactConfig:
    return ImpactConfig(module_roots=["src", "."], test_roots=["tests"])


@pytest.fixture
def cache(tmp_path: Path):
    cache = GraphCache(tmp_path / "cache.sqlite3")
    yield cache
    cache.close()


def explained(repo: Path, config: ImpactConfig, cache: GraphCache, base: str, head: str) -> SelectionExplanation:
    report = affected(repo, base, head, config, cache)
    return explain(repo, cache.snapshot(repo, base, config), cache.snapshot(repo, head, config), report, config)


def assert_routes_cover_selection(explanation: SelectionExplanation) -> None:
    """INVARIANT: every selected test is counted once, in exactly one top-level route."""
    assert sum(route.tests for route in explanation.routes if route.parent is None) == explanation.selected


def test_a_module_that_funnels_most_tests_is_named_with_its_import_line(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    write(repo, "tests/test_leaf.py", "from app.leaf import VALUE\ndef test_leaf(): assert VALUE == 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert_routes_cover_selection(explanation)
    routes = {(route.kind, route.via): route.tests for route in explanation.routes}
    assert routes == {("changed", None): 1, ("funnel", "src/app/hub.py"): HUB_TESTS}
    assert explanation.path == [
        PathStep(path="src/app/hub.py", kind="import", line=3),
        PathStep(path="src/app/leaf.py"),
    ]
    assert explanation.floor_seeds == []


def test_a_change_every_test_loads_is_attributed_to_the_startup_floor_from_its_entry_point(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/conftest.py", "import pytest\n\nfrom app.leaf import VALUE\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert_routes_cover_selection(explanation)
    assert explanation.selected == explanation.total
    assert explanation.floor_seeds == ["src/app/leaf.py"]
    assert [route.kind for route in explanation.routes] == ["floor"]
    assert explanation.path == [
        PathStep(path="tests/conftest.py", kind="import", line=3),
        PathStep(path="src/app/leaf.py"),
    ]


def test_a_module_named_as_a_string_by_a_startup_module_cites_the_string_line(repo: Path, cache: GraphCache) -> None:
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], global_modules=["app.settings"])
    write(repo, "src/app/settings.py", 'DEBUG = False\nSCHEDULE = {"task": "app.leaf.refresh"}\n')
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert explanation.floor_seeds == ["src/app/leaf.py"]
    assert explanation.path == [
        PathStep(path="src/app/settings.py", kind="string", line=2),
        PathStep(path="src/app/leaf.py"),
    ]


def test_a_new_import_from_the_floor_reports_the_files_that_joined_it_and_how(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    base = commit(repo)
    # helper.py already existed and reached one test; now every test loads it.
    write(repo, "src/app/leaf.py", "VALUE = 1\nfrom app.helper import HELP\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert explanation.floor.added == ["src/app/helper.py"]
    assert explanation.floor.after == explanation.floor.before + 1
    assert explanation.floor.path == [
        PathStep(path="tests/conftest.py", kind="import", line=1),
        PathStep(path="src/app/leaf.py", kind="import", line=2),
        PathStep(path="src/app/helper.py"),
    ]
    # A file that joined the floor is reported once, as floor growth, not also as widened.
    assert explanation.widened == []
    # The floor names its files and the files every test loads it through, for the reader to act on.
    assert "src/app/helper.py" in explanation.floor.files
    assert len(explanation.floor.files) == explanation.floor.after
    assert explanation.floor.entries == [
        FloorEntry(path="tests/conftest.py", kind="conftest", floor_files=explanation.floor.after),
        FloorEntry(path="src/app/__init__.py", kind="package", floor_files=1),
    ]
    assert explanation.floor.cycle is None


def test_floor_entries_say_how_tests_load_them(repo: Path, cache: GraphCache) -> None:
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], global_modules=["app.boot"])
    write(repo, "src/app/boot.py", "BOOTED = True\n")
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    # A hook makes a conftest global: tests outside its directory load it too.
    write(repo, "tests/hub/conftest.py", "def pytest_configure(config):\n    pass\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    kinds = {entry.path: entry.kind for entry in explained(repo, config, cache, base, head).floor.entries}

    assert kinds == {
        "tests/conftest.py": "conftest",
        "tests/hub/conftest.py": "hooks",
        "src/app/boot.py": "startup",
        "src/app/__init__.py": "package",
    }


def test_modules_most_tests_import_or_are_declared_to_read_are_entries_of_their_own_kind(
    repo: Path, cache: GraphCache
) -> None:
    rule = DependencyRule(readers=["tests/**"], inputs=["src/app/schema.sql"], reason="tests read the schema")
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], dependencies=[rule])
    write(repo, "src/app/schema.sql", "CREATE TABLE t (id int);\n")
    write(repo, "src/app/shared.py", "SHARED = 1\n")
    for test in sorted((repo / "tests").rglob("test_*.py")):
        test.write_text("import app.shared\n" + test.read_text())
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    kinds = {entry.path: entry.kind for entry in explained(repo, config, cache, base, head).floor.entries}

    assert kinds["src/app/shared.py"] == "import"
    assert kinds["src/app/schema.sql"] == "declared"


def test_an_import_cycle_holding_the_floor_is_reported_with_the_file_it_runs_through(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    members = [f"app.cycle_{number}" for number in range(CYCLE_MIN_FILES)]
    for number, module in enumerate(members):
        onward = members[(number + 1) % len(members)]
        # Each member imports the next, closing a ring, and the first one: the ring runs through it.
        imports = {onward, members[0]} - {module}
        write(repo, f"src/{module.replace('.', '/')}.py", "".join(f"import {name}\n" for name in sorted(imports)))
    write(repo, "tests/conftest.py", f"import {members[0]}\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    cycle = explained(repo, config, cache, base, head).floor.cycle

    assert cycle == FloorCycle(size=len(members), hub="src/app/cycle_0.py", hub_readers=len(members) - 1)


def test_a_new_import_that_makes_a_file_reach_many_more_tests_is_reported_with_its_cause(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(repo, "src/app/hub.py", "import os\n\nfrom app.leaf import VALUE\nfrom app.helper import HELP\n")
    # A new import elsewhere that does not lead to the widened file is not its cause.
    write(repo, "src/app/aaa.py", "from app.leaf import VALUE\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    [widened] = explanation.widened
    assert (widened.path, widened.before, widened.after) == ("src/app/helper.py", 1, HUB_TESTS + 1)
    assert widened.cause == [
        PathStep(path="src/app/hub.py", kind="import", line=4),
        PathStep(path="src/app/helper.py"),
    ]
    assert explanation.floor.added == []


def test_tests_selected_without_reaching_the_change_are_counted_apart(repo: Path, cache: GraphCache) -> None:
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], always_run=["tests/other/*"])
    base = commit(repo)
    write(repo, "src/app/helper.py", "HELP = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert_routes_cover_selection(explanation)
    routes = {route.kind: route.tests for route in explanation.routes}
    assert routes == {"other": 1, "unreached": UNRELATED_TESTS}


def test_nothing_selected_explains_an_empty_selection(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base = commit(repo)
    write(repo, "README.md", "unreferenced\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert (explanation.selected, explanation.routes, explanation.path) == (0, [], [])


def test_every_member_of_an_import_cycle_is_reached_by_the_tests_of_any_member(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/app/first.py", "from app import second\n")
    write(repo, "src/app/second.py", "from app import first\n")
    write(repo, "tests/test_cycle.py", "from app import first\ndef test_cycle(): assert first\n")
    head = commit(repo)

    snapshot = cache.snapshot(repo, head, config)
    reach = dependent_tests(snapshot)

    cycle_test = 1 << snapshot.tests.index("tests/test_cycle.py")
    assert reach["src/app/first.py"] & cycle_test
    assert reach["src/app/second.py"] & cycle_test


def run_affected(
    repo: Path, config: ImpactConfig, tmp_path: Path, base: str, head: str, *extra: str
) -> tuple[int, Path, Path]:
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    report_path, explanation_path = tmp_path / "report.json", tmp_path / "explanation.json"
    status = impact_cli.main(
        [
            "affected",
            "--repo",
            str(repo),
            "--config",
            str(config_path),
            "--cache",
            str(tmp_path / "cli-cache.sqlite3"),
            "--base",
            base,
            "--head",
            head,
            "--output",
            str(report_path),
            "--explanation-output",
            str(explanation_path),
            *extra,
        ]
    )
    return status, report_path, explanation_path


def test_cli_writes_the_explanation_of_the_selection_it_reports(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    status, report_path, explanation_path = run_affected(repo, config, tmp_path, base, head)

    assert status == 0
    report = ImpactReport.model_validate_json(report_path.read_text())
    explanation = SelectionExplanation.model_validate_json(explanation_path.read_text())
    assert explanation.selected == len(report.selected)
    assert (explanation.base, explanation.head) == (report.base, report.head)


@pytest.mark.parametrize("full", [False, True], ids=["selected", "requested"])
def test_cli_records_whether_the_full_suite_was_requested(
    repo: Path, config: ImpactConfig, tmp_path: Path, full: bool
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    _, _, explanation_path = run_affected(repo, config, tmp_path, base, head, *(["--full"] if full else []))

    explanation = SelectionExplanation.model_validate_json(explanation_path.read_text())
    assert explanation.full_suite
    assert explanation.forced_full is full
    assert explanation.natural_full_suite is not full


@pytest.mark.parametrize("known", [True, False], ids=["merge-base", "unknown-commit"])
def test_cli_measures_the_graph_from_the_merge_base_of_the_pr_base(
    repo: Path, config: ImpactConfig, tmp_path: Path, cache: GraphCache, known: bool
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    pr_base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 1\nfrom app.helper import HELP\n")
    validated = commit(repo)
    write(repo, "src/app/hub.py", "import os\n\nfrom app.leaf import VALUE\n# a later push\n")
    head = commit(repo)
    graph_base = pr_base if known else "0" * 40

    status, _, explanation_path = run_affected(repo, config, tmp_path, validated, head, "--graph-base", graph_base)

    assert status == 0
    explanation = SelectionExplanation.model_validate_json(explanation_path.read_text())
    # Without the commit the deltas fall back to the selection base rather than failing.
    expected_base = pr_base if known else validated
    assert explanation.graph_base == cache.snapshot(repo, expected_base, config).tree
    assert explanation.floor.added == (["src/app/helper.py"] if known else [])


def test_cli_keeps_the_selection_when_the_explanation_fails(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    with patch.object(impact_cli, "explain", side_effect=RuntimeError("graph unavailable")):
        status, report_path, explanation_path = run_affected(repo, config, tmp_path, base, head)

    assert status == 0
    assert ImpactReport.model_validate_json(report_path.read_text()).selected
    assert not explanation_path.exists()
    assert "Test selection explanation unavailable: graph unavailable" in capsys.readouterr().err


def test_nested_funnels_are_reported_inside_the_funnel_nearest_the_change(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    # Two parallel imports join again at the hub; the hub tests reach it through an API module.
    write(repo, "src/app/mid_a.py", "from app.leaf import VALUE\n")
    write(repo, "src/app/mid_b.py", "from app.leaf import VALUE\n")
    write(repo, "src/app/hub.py", "from app.mid_a import VALUE\nfrom app.mid_b import VALUE as OTHER\n")
    write(repo, "src/app/api.py", "from app.hub import VALUE\n")
    for number in range(HUB_TESTS):
        write(repo, f"tests/hub/test_hub_{number}.py", "from app.api import VALUE\ndef test_value(): assert VALUE\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert_routes_cover_selection(explanation)
    funnels = [(route.via, route.parent, route.tests) for route in explanation.routes if route.kind == "funnel"]
    assert funnels == [("src/app/hub.py", None, HUB_TESTS), ("src/app/api.py", "src/app/hub.py", HUB_TESTS)]
    assert [step.path for step in explanation.path] == ["src/app/hub.py", "src/app/mid_a.py", "src/app/leaf.py"]


def test_a_few_more_dependent_tests_is_not_widening(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base = commit(repo)
    write(
        repo, "tests/test_leaf.py", "from app.leaf import VALUE\nfrom app.helper import HELP\ndef test_leaf(): pass\n"
    )
    head = commit(repo)

    assert explained(repo, config, cache, base, head).widened == []


def test_the_floor_path_leads_past_a_changed_startup_root_to_the_rest_of_the_change(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    base = commit(repo)
    write(repo, "tests/conftest.py", "import os\n\nfrom app.leaf import VALUE\n")
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)

    assert explanation.floor_seeds == ["src/app/leaf.py", "tests/conftest.py"]
    assert [step.path for step in explanation.path] == ["tests/conftest.py", "src/app/leaf.py"]


def test_graph_changes_are_measured_from_the_pr_base_not_a_validated_tree(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    """After a green push, selection starts from that push; the floor it grew must stay visible."""
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    pr_base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 1\nfrom app.helper import HELP\n")
    validated = commit(repo)
    write(repo, "src/app/hub.py", "import os\n\nfrom app.leaf import VALUE\n# a later push\n")
    head = commit(repo)

    report = affected(repo, validated, head, config, cache)
    before, after = cache.snapshot(repo, validated, config), cache.snapshot(repo, head, config)
    since_validated = explain(repo, before, after, report, config)
    since_pr_base = explain(repo, before, after, report, config, graph_before=cache.snapshot(repo, pr_base, config))

    assert since_validated.floor.added == []
    assert since_pr_base.floor.added == ["src/app/helper.py"]
    assert since_pr_base.graph_base == cache.snapshot(repo, pr_base, config).tree
    # Routes still follow what this push selected.
    assert since_pr_base.routes == since_validated.routes


def test_adding_tests_that_import_a_module_is_not_widening(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base = commit(repo)
    for number in range(HUB_TESTS):
        write(repo, f"tests/new/test_new_{number}.py", "from app.helper import HELP\ndef test_help(): assert HELP\n")
    head = commit(repo)

    assert explained(repo, config, cache, base, head).widened == []


def test_widening_declared_by_a_manifest_is_reported_without_a_changed_import(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(
        repo,
        "src/app/.gv-dependencies.yaml",
        "dependencies:\n  - readers: [hub.py]\n    inputs: [helper.py]\n    kind: import\n    reason: hub loads it\n",
    )
    head = commit(repo)

    [widened] = explained(repo, config, cache, base, head).widened
    assert (widened.path, widened.cause) == ("src/app/helper.py", [])


@pytest.mark.parametrize(
    ("reader", "dependency", "kind"),
    [
        ("src/app/sub/mod.py", "src/app/sub/__init__.py", "package"),
        ("tests/other/test_other_0.py", "tests/conftest.py", "conftest"),
        ("tests/other/test_other_0.py", "src/app/settings.py", "startup"),
        ("tests/other/test_other_0.py", "tests/hub/conftest.py", "startup"),
        ("src/app/hub.py", "@contents:src/app/helper.py", "declared"),
        ("deploy/run.sh", "src/app/helper.py", "declared"),
    ],
    ids=[
        "own-package",
        "ancestor-conftest",
        "global-module",
        "plugin-conftest",
        "content-declaration",
        "non-python-reader",
    ],
)
def test_edges_without_an_import_line_name_the_rule_that_creates_them(
    repo: Path, cache: GraphCache, reader: str, dependency: str, kind: EdgeKind
) -> None:
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], global_modules=["app.settings"])
    write(repo, "src/app/sub/__init__.py")
    write(repo, "src/app/sub/mod.py", "VALUE = 1\n")
    write(repo, "src/app/settings.py", "DEBUG = False\n")
    write(repo, "tests/conftest.py", "import pytest\n")
    write(repo, "tests/hub/conftest.py", "def pytest_configure(config): pass\n")
    write(repo, "deploy/run.sh", "python -m app.helper\n")
    head = commit(repo)

    step = EdgeEvidence(repo, cache.snapshot(repo, head, config), config).step(reader, dependency)

    assert step == PathStep(path=reader, kind=kind)


def test_a_repository_without_tests_has_no_startup_floor(
    tmp_path: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    init(root)
    write(root, "src/app/__init__.py")
    head = commit(root)

    snapshot = cache.snapshot(root, head, config)

    assert startup_floor(snapshot, dependent_tests(snapshot)) == set()


ACTION = Path("actions/test-impact/action.yml")
EXPLANATION_FILE = "test-impact-explanation.json"


def action_steps() -> list[dict[str, object]]:
    return yaml.safe_load(ACTION.read_text())["runs"]["steps"]


def run_select_step(
    repo: Path, config: ImpactConfig, tmp_path: Path, base: str, *, planner_fails: bool, graph_base: str = ""
) -> Path:
    """Run the action's selection script in `repo`: the real CLI from this checkout, no network."""
    select = next(step for step in action_steps() if step.get("id") == "select")
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    python = shlex.quote(Path(sys.executable).as_posix())
    script = tmp_path / "select.sh"
    script.write_text(
        "set -euo pipefail\n"
        + f'python3() {{ {python} "$@"; }}\n'
        + 'git() { if [ "$1" = fetch ]; then return 0; fi; command git "$@"; }\n'
        # `uv run ... python -m module args` runs the same module with this interpreter.
        + (
            "uv() { return 1; }\n"
            if planner_fails
            else f'uv() {{ while [ "$1" != python ]; do shift; done; shift; {python} "$@"; }}\n'
        )
        + str(select["run"]),
        newline="\n",
    )
    output = tmp_path / "github-output"
    env = dict(
        os.environ,
        IMPACT_CONFIG=config_path.as_posix(),
        IMPACT_BASE=base,
        IMPACT_HEAD="HEAD",
        IMPACT_FULL="false",
        IMPACT_EXTRA="",
        IMPACT_ROOTS="tests",
        IMPACT_SHARDS="2",
        IMPACT_MINIMUM="0",
        IMPACT_DURATIONS=".test_durations",
        IMPACT_SHARD_SECONDS="120",
        IMPACT_GRAPH_BASE=graph_base,
        GITHUB_OUTPUT=output.as_posix(),
        GITHUB_STEP_SUMMARY=(tmp_path / "summary.md").as_posix(),
        SHARED_ACTION_PATH=ACTION.parent.resolve().as_posix(),
    )
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run([bash, script.as_posix()], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return repo / EXPLANATION_FILE


def test_the_action_writes_the_explanation_of_the_selection_it_plans(
    repo: Path, config: ImpactConfig, tmp_path: Path, cache: GraphCache
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    pr_base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 1\nfrom app.helper import HELP\n")
    commit(repo)

    explanation_path = run_select_step(repo, config, tmp_path, pr_base, planner_fails=False, graph_base=pr_base)

    report = ImpactReport.model_validate_json((repo / "test-impact-report.json").read_text())
    explanation = SelectionExplanation.model_validate_json(explanation_path.read_text())
    assert explanation.selected == len(report.selected)
    # The action passes the PR base on; the floor this change grew is measured from it.
    assert explanation.graph_base == cache.snapshot(repo, pr_base, config).tree
    assert explanation.floor.added == ["src/app/helper.py"]


def test_a_fallback_plan_uploads_a_marker_that_replaces_any_earlier_explanation(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    base = commit(repo)
    earlier = SelectionExplanation(
        base="old",
        head="old",
        graph_base="old",
        selected=1,
        total=HUB_TESTS,
        floor=FloorChange(share=0.9, before=0, after=0),
    )
    (repo / EXPLANATION_FILE).write_text(earlier.model_dump_json())

    marker = run_select_step(repo, config, tmp_path, base, planner_fails=True)

    assert ExplanationUnavailable.model_validate_json(marker.read_text()).unavailable.endswith(
        "complete suite fallback"
    )


def test_the_explanation_is_uploaded_for_every_plan_and_never_for_warming() -> None:
    upload = next(step for step in action_steps() if step.get("name") == "Upload selection explanation")
    inputs = yaml.safe_load(ACTION.read_text())["inputs"]

    assert inputs["graph-base"]["default"] == "${{ github.event.pull_request.base.sha }}"
    condition = str(upload["if"])
    assert "inputs.warm-only != 'true'" in condition
    assert "inputs.explanation-artifact != ''" in condition
    assert f"hashFiles('{EXPLANATION_FILE}') != ''" in condition
    assert upload["continue-on-error"] is True
    assert upload["with"] == {
        "name": "${{ inputs.explanation-artifact }}",
        "path": EXPLANATION_FILE,
        "overwrite": True,
        "retention-days": 7,
    }


def test_each_changed_file_is_attributed_to_its_direct_users_and_the_hub_the_rest_come_through(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    [leaf] = explained(repo, config, cache, base, head).changes

    assert leaf == ChangedFileReach(
        path="src/app/leaf.py",
        tests=HUB_TESTS + 1,
        direct=1,
        own=HUB_TESTS + 1,
        hub="src/app/hub.py",
        hub_tests=HUB_TESTS,
        hub_kind="import",
    )


def test_a_changed_file_in_the_floor_counts_what_would_still_load_it_without_the_floor(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 2\n")
    head = commit(repo)

    explanation = explained(repo, config, cache, base, head)
    leaf = next(change for change in explanation.changes if change.path == "src/app/leaf.py")

    assert leaf.tests == explanation.total
    # Without the root conftest's import, only the hub's tests and the direct importer load it.
    assert leaf.own == HUB_TESTS + 1
    # The root conftest is a floor entry every test loads: never named as this change's hub.
    assert leaf.hub == "src/app/hub.py"


def run_budget_step(repo: Path, config: ImpactConfig, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the action's floor-budget script in `repo` with the real CLI, as `run_select_step` does."""
    step = next(step for step in action_steps() if step.get("name") == "Check the startup-floor budget")
    config_path = tmp_path / "budget-config.json"
    config_path.write_text(config.model_dump_json())
    python = shlex.quote(Path(sys.executable).as_posix())
    script = tmp_path / "budget.sh"
    script.write_text(
        "set -euo pipefail\n"
        + f'uv() {{ while [ "$1" != python ]; do shift; done; shift; {python} "$@"; }}\n'
        + str(step["run"]),
        newline="\n",
    )
    env = dict(os.environ, IMPACT_CONFIG=config_path.as_posix(), SHARED_ACTION_PATH=ACTION.parent.resolve().as_posix())
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run([bash, script.as_posix()], cwd=repo, env=env, capture_output=True, text=True)


def grow_the_floor(repo: Path, config: ImpactConfig, tmp_path: Path) -> SelectionExplanation:
    """A PR that pulls src/app/helper.py into the floor, planned by the action."""
    write(repo, "tests/conftest.py", "from app.leaf import VALUE\n")
    pr_base = commit(repo)
    write(repo, "src/app/leaf.py", "VALUE = 1\nfrom app.helper import HELP\n")
    commit(repo)
    path = run_select_step(repo, config, tmp_path, pr_base, planner_fails=False, graph_base=pr_base)
    return SelectionExplanation.model_validate_json(path.read_text())


def test_growing_the_floor_past_its_budget_fails_the_plan_and_names_the_way_in(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    floor = grow_the_floor(repo, config, tmp_path).floor
    budgeted = config.model_copy(update={"floor_budget": floor.before})

    result = run_budget_step(repo, budgeted, tmp_path)

    assert result.returncode == 1
    assert f"grows the startup floor to {floor.after} files, over its budget of {floor.before}" in result.stdout
    assert "Joined the floor: src/app/helper.py." in result.stdout
    assert "They enter through tests/conftest.py -> src/app/leaf.py -> src/app/helper.py." in result.stdout


def test_a_floor_under_its_budget_passes_and_says_to_lower_it(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    floor = grow_the_floor(repo, config, tmp_path).floor
    loose = floor.after + 3
    budgeted = config.model_copy(update={"floor_budget": loose})

    result = run_budget_step(repo, budgeted, tmp_path)

    assert result.returncode == 0
    assert f"under its budget of {loose}. Lower floor_budget to {floor.after}" in result.stdout


@pytest.mark.parametrize("budget", [None, 0], ids=["no-budget", "fallback-plan"])
def test_no_budget_or_no_trustworthy_explanation_never_fails_the_plan(
    repo: Path, config: ImpactConfig, tmp_path: Path, budget: int | None
) -> None:
    if budget is None:
        grow_the_floor(repo, config, tmp_path)
    else:
        run_select_step(repo, config, tmp_path, commit(repo), planner_fails=True)
    result = run_budget_step(repo, config.model_copy(update={"floor_budget": budget}), tmp_path)

    assert result.returncode == 0
    assert ("Startup-floor budget not checked" in result.stdout) is (budget is not None)


def test_the_floor_budget_does_not_change_the_cached_graph(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    head = commit(repo)
    cache.snapshot(repo, head, config)
    hits = cache.snapshot_hits

    cache.snapshot(repo, head, config.model_copy(update={"floor_budget": 7}))

    assert cache.snapshot_hits == hits + 1


#: A floor that grew past the files the budget error names one by one.
MANY_JOINED = 12


def budget_check(tmp_path: Path, config: ImpactConfig, explanation: str) -> int:
    config_path, explanation_path = tmp_path / "config.json", tmp_path / EXPLANATION_FILE
    config_path.write_text(config.model_dump_json())
    explanation_path.write_text(explanation)
    return impact_cli.main(["floor-budget", "--config", str(config_path), "--explanation", str(explanation_path)])


def floor_explanation(before: int, after: int, added: list[str]) -> str:
    floor = FloorChange(share=0.9, before=before, after=after, added=added)
    return SelectionExplanation(
        base="b", head="h", graph_base="b", selected=1, total=HUB_TESTS, floor=floor
    ).model_dump_json()


def test_a_large_growth_names_the_first_files_and_counts_the_rest(
    config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    added = [f"src/app/module_{number}.py" for number in range(MANY_JOINED)]
    budgeted = config.model_copy(update={"floor_budget": 1})

    assert budget_check(tmp_path, budgeted, floor_explanation(1, 1 + MANY_JOINED, added)) == 1

    out = capsys.readouterr().out
    assert f"src/app/module_9.py and {MANY_JOINED - 10} more." in out
    assert "They enter through" not in out


def test_a_floor_exactly_at_its_budget_passes_silently(
    config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    budgeted = config.model_copy(update={"floor_budget": 5})

    assert budget_check(tmp_path, budgeted, floor_explanation(5, 5, [])) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("budget", "explanation", "warned"),
    [
        (None, "not json", False),
        (5, ExplanationUnavailable(unavailable="complete suite fallback").model_dump_json(), True),
        (5, "not json", True),
    ],
    ids=["no-budget", "fallback-marker", "unreadable"],
)
def test_the_budget_check_fails_open(
    config: ImpactConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    budget: int | None,
    explanation: str,
    warned: bool,
) -> None:
    assert budget_check(tmp_path, config.model_copy(update={"floor_budget": budget}), explanation) == 0
    assert ("Startup-floor budget not checked" in capsys.readouterr().out) is warned


def test_a_floor_under_its_budget_gets_a_notice_to_lower_it(
    config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    budgeted = config.model_copy(update={"floor_budget": 9})

    assert budget_check(tmp_path, budgeted, floor_explanation(5, 4, [])) == 0
    assert "under its budget of 9. Lower floor_budget to 4" in capsys.readouterr().out
