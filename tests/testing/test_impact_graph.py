# gv:test-dependency: .github/actions/test-impact/action.yml
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from pytest_selective.impact_cli import main
from pytest_selective.impact_graph import (
    DependencyDeclarationError,
    GraphCache,
    blobs,
    explanation,
    inventory,
    parse_source,
    policy_fingerprints,
    reachable,
)
from pytest_selective.impact_models import DeferredStringsRule, DependencyRule, ImpactConfig
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write
from tests.testing.git_repo import head as head_of


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "src/pkg/__init__.py")
    write(root, "src/pkg/leaf.py", "VALUE = 1")
    write(root, "src/pkg/helper.py", "from .leaf import VALUE")
    write(root, "tests/left/test_one.py", "from pkg.helper import VALUE\ndef test_value(): assert VALUE == 1")
    write(root, "tests/right/test_two.py", "def test_other(): assert True")
    return root


@pytest.fixture
def config() -> ImpactConfig:
    return ImpactConfig(module_roots=["src", "."], test_roots=["tests"])


@pytest.fixture
def cache(tmp_path: Path):
    cache = GraphCache(tmp_path / "cache.sqlite3")
    yield cache
    cache.close()


def test_transitive_imports_select_only_dependents(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    assert report.selected == ["tests/left/test_one.py"]
    assert report.total_files == 2
    snapshot = cache.snapshot(repo, head, config)
    assert explanation(snapshot, "tests/left/test_one.py", "src/pkg/leaf.py") == [
        "tests/left/test_one.py",
        "src/pkg/helper.py",
        "src/pkg/leaf.py",
    ]


@pytest.mark.parametrize("through_conftest", [False, True])
def test_shared_helpers_follow_imports_and_only_conftests_supply_implicit_edges(
    repo: Path, config: ImpactConfig, cache: GraphCache, through_conftest: bool
) -> None:
    write(repo, "tests/helpers.py", "def read_asset(path): return path.read_bytes()")
    importer = "tests/left/conftest.py" if through_conftest else "tests/left/test_one.py"
    write(repo, importer, "from tests.helpers import read_asset")
    write(repo, "tests/left/test_sibling.py", "def test_sibling(): pass")
    write(repo, "tests/right/conftest.py", "def fixture(path): return path.read_bytes()")
    base = commit(repo)
    write(repo, "tests/helpers.py", "def read_asset(path): return path.read_text()")
    head = commit(repo)
    expected = ["tests/left/test_one.py"]
    if through_conftest:
        expected.append("tests/left/test_sibling.py")
    assert affected(repo, base, head, config, cache).selected == expected


def test_unused_conftest_import_reaches_every_descendant_but_not_sibling(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/left/conftest.py", "def unused_fixture():\n    from pkg.helper import VALUE")
    write(repo, "tests/left/deep/test_child.py", "def test_child(): pass")
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    assert report.selected == ["tests/left/deep/test_child.py", "tests/left/test_one.py"]


def test_deleted_dependency_and_removed_import_keep_old_dependents(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    (repo / "src/pkg/leaf.py").unlink()
    write(repo, "src/pkg/helper.py", "VALUE = 3")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_new_previously_unresolved_submodule_updates_unchanged_importer(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/right/test_two.py", "from pkg import future")
    base = commit(repo)
    cache.snapshot(repo, base, config)
    write(repo, "src/pkg/future.py", "VALUE = 1")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/right/test_two.py"]


def test_package_initializer_change_reaches_submodule_importers(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(repo, "src/pkg/__init__.py", "FLAG = True")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_declared_dynamic_import_reaches_reader_and_its_importers(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/loader.py", "import importlib\ndef load(name): return importlib.import_module(name)")
    write(repo, "tests/right/test_two.py", "import loader")
    config.dependencies = [
        DependencyRule(readers=["src/loader.py"], inputs=["src/pkg/helper.py"], kind="import", reason="Dynamic target")
    ]
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


@pytest.mark.parametrize(
    "path",
    [
        "deployment/envs_STG",
        "settings.json",
        ".github/workflows/unused.yml",
        "docs/a.md",
        ".agents/skills/a/SKILL.md",
        "scripts/a.sh",
    ],
)
def test_unreferenced_input_selects_nothing_with_cold_or_warm_cache(
    repo: Path, config: ImpactConfig, cache: GraphCache, path: str
) -> None:
    base = commit(repo)
    write(repo, path, "{}")
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    assert report.mode == "none"
    assert report.selected == []
    assert affected(repo, base, head, config, cache).selected == report.selected


def test_cold_warm_and_incremental_snapshots_agree(
    repo: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    base = commit(repo)
    before = cache.snapshot(repo, base, config)
    parsed_before = cache.parsed_blobs
    assert cache.snapshot(repo, base, config) == before
    assert cache.parsed_blobs == parsed_before
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    incremental = cache.snapshot(repo, head, config)
    assert cache.parsed_blobs == parsed_before + 1
    cold = GraphCache(tmp_path / "cold.sqlite3")
    try:
        assert cold.snapshot(repo, head, config) == incremental
    finally:
        cold.close()


def test_cycles_terminate_and_include_all_dependencies(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "src/pkg/leaf.py", "from . import helper")
    head = commit(repo)
    graph = cache.snapshot(repo, head, config)
    assert {"src/pkg/helper.py", "src/pkg/leaf.py", "src/pkg/__init__.py"} <= reachable(
        graph.edges, {"tests/left/test_one.py"}
    )


def test_content_read_does_not_execute_the_read_files_imports(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo,
        "tests/right/conftest.py",
        "from pathlib import Path\ndef fixture(): return Path('tests/left/test_one.py').read_text()",
    )
    config.dependencies = [
        DependencyRule(
            readers=["tests/right/conftest.py"], inputs=["tests/left/test_one.py"], reason="AST policy reads test text"
        )
    ]
    base = commit(repo)
    config.dependencies[0].reviewed_readers = {
        "tests/right/conftest.py": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD:tests/right/conftest.py"], text=True
        ).strip()
    }
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]
    write(repo, "tests/left/test_one.py", "from pkg.helper import VALUE\ndef test_value(): assert VALUE == 2")
    newer = commit(repo)
    assert affected(repo, head, newer, config, cache).selected == ["tests/left/test_one.py", "tests/right/test_two.py"]


def test_global_hook_dependencies_are_broad_unless_explicitly_scoped(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo, "tests/left/conftest.py", "from pkg.helper import VALUE\ndef pytest_collection_modifyitems(items): pass"
    )
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"
    config.scoped_hooks = {
        "tests/left/conftest.py": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD:tests/left/conftest.py"], text=True
        ).strip()
    }
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_global_module_and_literal_dynamic_import_resolve_transitively(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/bootstrap.py", "import importlib\nvalue = importlib.import_module('pkg.helper')")
    config.global_modules = ["bootstrap"]
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


def test_conftest_move_includes_former_and_new_scope(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "tests/left/conftest.py", "def unused_fixture(): pass")
    base = commit(repo)
    (repo / "tests/left/conftest.py").rename(repo / "tests/right/conftest.py")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


def test_snapshot_cache_damage_rebuilds_identical_graph(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    head = commit(repo)
    expected = cache.snapshot(repo, head, config)
    cache.connection.execute("UPDATE cache SET value = 'broken'")
    assert cache.snapshot(repo, head, config) == expected


def test_invalid_cached_contracts_rebuild_even_with_valid_checksums(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    head = commit(repo)
    expected = cache.snapshot(repo, head, config)
    keys = cache.connection.execute("SELECT key FROM cache").fetchall()
    for (key,) in keys:
        cache.put(key, "{}")
    assert cache.snapshot(repo, head, config) == expected


@pytest.mark.parametrize("change", ["unrelated", "none", "repair"])
def test_parse_failure_is_a_hard_error_even_for_declared_reader(
    repo: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    write(repo, "src/pkg/helper.py", "invalid syntax !!")
    config.dependencies = [DependencyRule(readers=["src/pkg/helper.py"], inputs=[], reason="No extra files")]
    base = commit(repo)
    head = base
    if change == "unrelated":
        write(repo, "src/unrelated.py", "VALUE = 1")
        head = commit(repo)
    elif change == "repair":
        write(repo, "src/pkg/helper.py", "VALUE = 1")
        head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match="src/pkg/helper.py.*cannot parse"):
        affected(repo, base, head, config, cache)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    output = tmp_path / "github-output"
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--base",
                base,
                "--head",
                head,
                "--cache",
                str(tmp_path / "cli-cache.db"),
                "--github-output",
                str(output),
                "--full",
            ]
        )
        == 2
    )
    assert "src/pkg/helper.py" in capsys.readouterr().err
    assert not output.exists()


def test_prior_failure_files_join_selection_even_without_a_source_diff(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    head = commit(repo)
    assert affected(repo, head, head, config, cache, ["tests/right/test_two.py"]).selected == [
        "tests/right/test_two.py"
    ]
    assert affected(repo, head, head, config, cache).mode == "none"


@pytest.mark.parametrize("change", ["edit", "add", "delete", "failure"])
def test_isolated_test_changes_do_not_activate_unchanged_opaque_conftests(
    repo: Path, config: ImpactConfig, cache: GraphCache, change: str
) -> None:
    for scope in ["left", "right"]:
        write(repo, f"tests/{scope}/conftest.py", "def fixture(path): return path.read_bytes()")
    write(repo, "tests/left/test_sibling.py", "def test_sibling(): pass")
    base = commit(repo)
    changed_test = "tests/left/test_one.py"
    extra_files = None
    expected = [changed_test]
    if change == "edit":
        write(repo, changed_test, "def test_changed(): pass")
    elif change == "add":
        changed_test = "tests/left/test_added.py"
        write(repo, changed_test, "def test_added(): pass")
        expected = [changed_test]
    elif change == "delete":
        (repo / changed_test).unlink()
        expected = []
    else:
        extra_files = [changed_test]
    head = base if change == "failure" else commit(repo)
    assert affected(repo, base, head, config, cache, extra_files).selected == expected


def test_changed_opaque_conftest_retains_descendant_dependencies(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/left/conftest.py", "def fixture(path): return path.read_bytes()")
    base = commit(repo)
    write(repo, "tests/left/conftest.py", "def fixture(path): return path.read_text()")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_declared_subprocess_entrypoints_follow_their_imports(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo,
        "tests/right/test_two.py",
        "import subprocess\ndef test_external(): subprocess.run(['python', 'src/pkg/helper.py'])",
    )
    config.dependencies = [
        DependencyRule(
            readers=["tests/right/test_two.py"], inputs=["src/pkg/helper.py"], kind="import", reason="Entrypoint"
        )
    ]
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


@pytest.mark.parametrize("input_kind", ["python", "json", "sidecar", "directory"])
def test_native_pytest_selected_files_catch_the_same_failure_as_full_suite(
    repo: Path, config: ImpactConfig, cache: GraphCache, input_kind: str
) -> None:
    if input_kind != "python":
        write(
            repo,
            "src/pkg/leaf.py",
            "# gv:test-dependency: input.json\nimport json\nfrom pathlib import Path\nVALUE = json.loads(Path('input.json').read_text())",
        )
        write(repo, "input.json", "1")
        if input_kind in {"sidecar", "directory"}:
            write(
                repo,
                "src/pkg/leaf.py",
                "import json\nfrom pathlib import Path\nVALUE = json.loads(Path('input.json').read_text())",
            )
            if input_kind == "sidecar":
                write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies:\n  - inputs: ["//input.json"]\n')
            else:
                write(
                    repo,
                    "src/pkg/.gv-dependencies.yaml",
                    'dependencies: [{readers: ["leaf.py"], inputs: ["//input.json"]}]',
                )
    base = commit(repo)
    write(
        repo,
        "input.json" if input_kind != "python" else "src/pkg/leaf.py",
        "2" if input_kind != "python" else "VALUE = 2",
    )
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    env = dict(os.environ, PYTHONPATH=str(repo / "src"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    assert report.selected == ["tests/left/test_one.py"]
    selected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *report.selected], cwd=repo, env=env, capture_output=True, text=True
    )
    full = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests"], cwd=repo, env=env, capture_output=True, text=True
    )
    assert selected.returncode == full.returncode == 1
    assert "1 failed" in selected.stdout
    assert "1 failed, 1 passed" in full.stdout


def test_cli_writes_reviewable_selection_and_ci_outputs(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "output.txt"
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                base,
                "--head",
                head,
                "--output",
                str(report_path),
                "--github-output",
                str(output_path),
            ]
        )
        == 0
    )
    assert json.loads(report_path.read_text())["selected"] == ["tests/left/test_one.py"]
    assert "mode=scoped" in output_path.read_text()
    assert "test_roots=tests/left/test_one.py" in output_path.read_text()


@pytest.mark.parametrize("command", ["dependencies", "explain", "conftest-impact"])
def test_cli_dependency_inspection(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    write(repo, "tests/conftest.py", "from pkg.helper import VALUE")
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    assert (
        main(
            [
                command,
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--test",
                "tests/left/test_one.py",
                "--source",
                "src/pkg/leaf.py",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    if command == "conftest-impact":
        assert result["tests/conftest.py"] == 2
    else:
        assert "src/pkg/leaf.py" in result


def test_cli_force_full_and_extra_failure_files(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    extra = tmp_path / "failures.txt"
    extra.write_text("tests/left/test_one.py\n")
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                head,
                "--extra-files",
                str(extra),
                "--full",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["mode"] == "full"


def test_cli_unknown_revision_never_emits_an_empty_success(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                "missing-ref",
            ]
        )
        == 1
    )
    assert "planning failed" in capsys.readouterr().err


class MovedMain(BaseModel):
    """A PR tree validated before main moved under it, then merged with that main."""

    main: str
    tested: str
    head: str


def git_in(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", *args], text=True
    ).strip()


@pytest.fixture
def moved_main(repo: Path) -> MovedMain:
    """
    The bump-PR history behind a full-suite rerun of a one-line change.

    main imports a settings module into every test through the root conftest. The PR edits
    one test and is validated. main then edits settings, and the automation merges main
    into the PR. The validated tree differs from the head by the settings change; main
    differs from it only by the PR's own edit.
    """
    write(repo, "src/pkg/settings.py", "DEBUG = False")
    write(repo, "tests/conftest.py", "from pkg.settings import DEBUG")
    commit(repo)
    git_in(repo, "checkout", "-qb", "pr")
    write(repo, "tests/right/test_two.py", "def test_other(): assert 2")
    tested = commit(repo)
    git_in(repo, "checkout", "-q", "-")
    write(repo, "src/pkg/settings.py", "DEBUG = True")
    moved = commit(repo)
    git_in(repo, "checkout", "-q", "pr")
    git_in(repo, "merge", "-q", "--no-edit", moved)
    return MovedMain(main=moved, tested=tested, head=head_of(repo))


class CliResult(BaseModel):
    status: int
    outputs: dict[str, str]
    selected: list[str]


def affected_cli(repo: Path, config: ImpactConfig | Path, tmp_path: Path, *args: str) -> CliResult:
    """Run `affected` with `config` written outside the repo, or with an existing config file."""
    if isinstance(config, Path):
        config_path = config
    else:
        config_path = tmp_path / "config.json"
        config_path.write_text(config.model_dump_json())
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "output.txt"
    output_path.write_text("")
    status = main(
        [
            "affected",
            "--repo",
            str(repo),
            "--config",
            str(config_path),
            "--cache",
            str(tmp_path / "cache.db"),
            "--output",
            str(report_path),
            "--github-output",
            str(output_path),
            *args,
        ]
    )
    return CliResult(
        status=status,
        outputs=dict(line.split("=", 1) for line in output_path.read_text().splitlines()),
        selected=json.loads(report_path.read_text())["selected"] if report_path.exists() else [],
    )


def test_cli_selects_from_the_pr_base_when_main_moved_under_the_validated_tree(
    repo: Path, config: ImpactConfig, tmp_path: Path, moved_main: MovedMain
) -> None:
    """
    INVARIANT: of two proven bases, the selector keeps the one that runs fewer tests.

    Both are sound: the validated tree passed every test it selected, and main is the
    base every PR diff is already trusted against. Merging main into a validated PR
    must not turn main's own change into a rerun of everything that change reaches.
    """
    control = affected_cli(repo, config, tmp_path, "--base", moved_main.tested, "--head", moved_main.head)
    assert control.status == 0
    assert control.outputs["mode"] == "full", "the validated-tree delta alone reaches every test"
    result = affected_cli(
        repo,
        config,
        tmp_path,
        "--base",
        moved_main.tested,
        "--head",
        moved_main.head,
        "--alternate-base",
        moved_main.main,
    )
    assert result.status == 0
    assert result.selected == ["tests/right/test_two.py"]
    assert result.outputs["mode"] == "scoped"
    assert result.outputs["base"] == moved_main.main
    assert f"instead of {moved_main.tested}" in result.outputs["reason"]


def test_cli_keeps_the_validated_tree_when_it_selects_less(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    """An ordinary push: the delta since the validated tree is smaller than the whole PR."""
    main_head = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    tested = commit(repo)
    write(repo, "tests/right/test_two.py", "def test_other(): assert 2")
    head = commit(repo)
    result = affected_cli(repo, config, tmp_path, "--base", tested, "--head", head, "--alternate-base", main_head)
    assert result.status == 0
    assert result.selected == ["tests/right/test_two.py"]
    assert result.outputs["base"] == tested


def test_cli_unreadable_alternate_keeps_the_proven_base(
    repo: Path, config: ImpactConfig, tmp_path: Path, moved_main: MovedMain
) -> None:
    """The alternate can only shrink a sound selection; its failure is not a planning failure."""
    result = affected_cli(
        repo,
        config,
        tmp_path,
        "--base",
        moved_main.tested,
        "--head",
        moved_main.head,
        "--alternate-base",
        "missing-ref",
    )
    assert result.status == 0
    assert result.outputs["mode"] == "full"
    assert result.outputs["base"] == moved_main.tested
    assert "alternate base missing-ref not used" in result.outputs["reason"]


def test_cli_alternate_carries_its_own_failure_canaries(
    repo: Path, config: ImpactConfig, tmp_path: Path, moved_main: MovedMain
) -> None:
    """Unresolved failures must survive the switch: the alternate base gets its own extra files."""
    canaries = tmp_path / "alternate.txt"
    canaries.write_text("tests/left/test_one.py\n")
    result = affected_cli(
        repo,
        config,
        tmp_path,
        "--base",
        moved_main.tested,
        "--head",
        moved_main.head,
        "--alternate-base",
        moved_main.main,
        "--alternate-extra-files",
        str(canaries),
    )
    assert result.status == 0
    assert result.selected == ["tests/left/test_one.py", "tests/right/test_two.py"]


def test_repository_paths_in_config_cannot_escape() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        ImpactConfig(module_roots=["../outside"], test_roots=["tests"])


def test_unreachable_explanation_is_empty(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    head = commit(repo)
    assert explanation(cache.snapshot(repo, head, config), "tests/right/test_two.py", "src/pkg/leaf.py") == []


def test_relative_dynamic_import_can_declare_its_dependency(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/right/test_two.py", "import importlib\nimportlib.import_module('.helper', 'pkg')")
    config.dependencies = [
        DependencyRule(
            readers=["tests/right/test_two.py"], inputs=["src/pkg/helper.py"], kind="import", reason="Dynamic target"
        )
    ]
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


@pytest.mark.parametrize(
    "source",
    [
        "from importlib import import_module as load\nload(module_name)",
        "from subprocess import run as launch\nlaunch(['python', 'entry.py'])",
    ],
)
def test_aliased_dynamic_loaders_without_dependencies_do_not_activate_unrelated_tests(
    repo: Path, config: ImpactConfig, cache: GraphCache, source: str
) -> None:
    write(repo, "tests/right/test_two.py", source)
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_git_symlink_is_rejected_without_needing_windows_symlink_privileges(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    commit(repo)
    blob = (
        subprocess.check_output(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"leaf.py")
        .decode()
        .strip()
    )
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--add", "--cacheinfo", f"120000,{blob},src/pkg/alias.py"], check=True
    )
    tree = subprocess.check_output(["git", "-C", str(repo), "write-tree"], text=True).strip()
    with pytest.raises(ValueError, match="unsupported Git entry"):
        cache.snapshot(repo, tree, config)


def test_cli_module_entrypoint_is_native_and_operational(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest_selective.impact_cli",
            "dependencies",
            "--repo",
            str(repo),
            "--config",
            str(config_path),
            "--cache",
            str(tmp_path / "cache.db"),
            "--test",
            "tests/left/test_one.py",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "src/pkg/leaf.py" in json.loads(result.stdout)


def test_batch_reader_rejects_non_blob_git_objects(repo: Path) -> None:
    commit_id = commit(repo)
    with pytest.raises(ValueError, match="not a blob"):
        blobs(repo, {commit_id})


@pytest.mark.parametrize("invalid_declaration", [False, True])
def test_ci_action_distinguishes_invalid_declarations_from_operational_fallback(
    tmp_path: Path, invalid_declaration: bool
) -> None:
    action = yaml.safe_load(Path(".github/actions/test-impact/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "select")
    output = tmp_path / "github-output"
    script = tmp_path / "action.sh"
    script.write_text(
        "set -euo pipefail\npython3() { "
        + shlex.quote(Path(sys.executable).as_posix())
        + ' "$@"; }\n'
        + ("git() { return 0; }\nuv() { return 2; }\n" if invalid_declaration else "")
        + step["run"],
        newline="\n",
    )
    env = dict(
        os.environ,
        IMPACT_CONFIG="missing.json",
        IMPACT_BASE="base" if invalid_declaration else "",
        IMPACT_HEAD="HEAD",
        IMPACT_FULL="false",
        IMPACT_EXTRA="",
        IMPACT_ROOTS="tests perf",
        IMPACT_SHARDS="6",
        IMPACT_MINIMUM="0",
        # The script runs under `set -u`, so every input the action declares has
        # to arrive here too; an input added without one reads as a broken action.
        IMPACT_DURATIONS=".test_durations",
        IMPACT_SHARD_SECONDS="120",
        GITHUB_OUTPUT=output.as_posix(),
        SHARED_ACTION_PATH=Path(".github/actions/test-impact").resolve().as_posix(),
    )
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run([bash, script.as_posix()], cwd=tmp_path, env=env, capture_output=True, text=True)
    if invalid_declaration:
        assert result.returncode == 2
        assert not output.exists()
        assert "Invalid test dependency" in result.stdout
        return
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert lines["mode"] == "full"
    assert lines["test_roots"] == "tests perf"
    assert json.loads(lines["groups"]) == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    ("alternate", "full", "passed"),
    [("pr-base", "false", True), ("unfetchable", "false", False), ("pr-base", "true", False), ("", "false", False)],
    ids=["fetched", "unfetchable", "full-suite", "absent"],
)
def test_ci_action_offers_a_fetchable_alternate_base(tmp_path: Path, alternate: str, full: str, passed: bool) -> None:
    """The action hands the CLI a second base only when it can be read and a scoped run is allowed."""
    action = yaml.safe_load(Path(".github/actions/test-impact/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "select")
    invocation = tmp_path / "invocation"
    script = tmp_path / "action.sh"
    script.write_text(
        "set -euo pipefail\n"
        + 'git() { [ "${!#}" != unfetchable ]; }\n'
        + 'uv() { printf "%s\\n" "$@" > "$INVOCATION"; return 1; }\n'
        + step["run"],
        newline="\n",
    )
    output = tmp_path / "github-output"
    env = dict(
        os.environ,
        IMPACT_CONFIG="consumer.json",
        IMPACT_BASE="validated-tree",
        IMPACT_HEAD="HEAD",
        IMPACT_FULL=full,
        IMPACT_EXTRA="changed-files.txt",
        IMPACT_ALTERNATE_BASE=alternate,
        IMPACT_ALTERNATE_EXTRA="alternate-changed-files.txt",
        IMPACT_ROOTS="tests",
        IMPACT_SHARDS="2",
        IMPACT_MINIMUM="0",
        IMPACT_DURATIONS=".test_durations",
        IMPACT_SHARD_SECONDS="120",
        GITHUB_OUTPUT=output.as_posix(),
        INVOCATION=invocation.as_posix(),
        SHARED_ACTION_PATH=Path(".github/actions/test-impact").resolve().as_posix(),
    )
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run([bash, script.as_posix()], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = invocation.read_text().splitlines()
    offered = "--alternate-base" in args
    assert offered is passed
    if passed:
        assert args[args.index("--alternate-base") + 1] == alternate
        assert args[args.index("--alternate-extra-files") + 1] == "alternate-changed-files.txt"
    # The operational fallback still names the base it fell back from.
    assert "base=validated-tree" in output.read_text().splitlines()


def test_import_through_directory_symlink_falls_back(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "tests/right/test_two.py", "from linked import helper")
    commit(repo)
    blob = (
        subprocess.check_output(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"src/pkg")
        .decode()
        .strip()
    )
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--add", "--cacheinfo", f"120000,{blob},linked"], check=True
    )
    tree = subprocess.check_output(["git", "-C", str(repo), "write-tree"], text=True).strip()
    with pytest.raises(ValueError, match="unsupported Git symlink"):
        cache.snapshot(repo, tree, config)


def test_module_resolution_unions_windows_case_variants(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "tests/right/test_two.py", "from PKG.leaf import VALUE")
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).mode == "full"


@pytest.mark.parametrize("reader", ["tests/right/test_two.py", "tests/right/conftest.py"])
def test_legacy_ownership_does_not_override_import_dependencies(
    repo: Path,
    config: ImpactConfig,
    cache: GraphCache,
    reader: str,
) -> None:
    write(repo, "src/pkg/service/leaf.py", "VALUE = 1")
    write(repo, "tests/test_service/test_service.py", "from pkg.service.leaf import VALUE")
    write(repo, "tests/left/test_one.py", "from pkg.service.leaf import VALUE")
    write(repo, reader, "import importlib\ndef load(name): return importlib.import_module(name)")
    write(
        repo,
        ".github/ownership.json",
        json.dumps(
            {
                "source_prefix": ["src", "pkg"],
                "service_reference_template": "pkg[./]{service}",
            }
        ),
    )
    write(
        repo,
        ".test_durations",
        json.dumps(
            {
                "tests/test_service/test_service.py::test_service": 1,
                "tests/right/test_two.py::test_other": 100,
            }
        ),
    )
    base = commit(repo)
    write(repo, "src/pkg/service/leaf.py", "VALUE = 2")
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    expected = {"tests/left/test_one.py", "tests/test_service/test_service.py"}
    assert set(report.selected) == expected


def test_changed_reader_invalidates_its_reviewed_opaque_declaration(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    reader = "tests/right/test_two.py"
    write(repo, reader, "import importlib\ndef load(name): return importlib.import_module(name)")
    base = commit(repo)
    oid = subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"HEAD:{reader}"], text=True).strip()
    config.dependencies = [
        DependencyRule(
            readers=[reader], inputs=[], reason="Reviewed external-only input", reviewed_readers={reader: oid}
        )
    ]
    assert reader not in cache.snapshot(repo, base, config).opaque
    write(repo, reader, "import importlib\ndef load(name): return importlib.import_module(name + '.changed')")
    head = commit(repo)
    assert reader in cache.snapshot(repo, head, config).opaque


def test_cache_prunes_old_graphs_without_changing_current_answers(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    cache_path = tmp_path / "bounded.sqlite3"
    local = GraphCache(cache_path)
    for index in range(10):
        write(repo, "src/pkg/leaf.py", f"VALUE = {index}")
        head = commit(repo)
        local.snapshot(repo, head, config)
    local.close()
    restored = GraphCache(cache_path)
    try:
        count = restored.connection.execute("SELECT count(*) FROM cache WHERE key LIKE '%:graph:%'").fetchone()[0]
        assert count == 8
        assert (
            restored.snapshot(repo, "HEAD", config).files["src/pkg/leaf.py"]
            == subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD:src/pkg/leaf.py"], text=True).strip()
        )
    finally:
        restored.close()


def test_cli_pads_a_small_nonempty_selection_for_fixed_shards(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    extra = tmp_path / "changed.txt"
    extra.write_text("tests/left/test_one.py")
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                head,
                "--extra-files",
                str(extra),
                "--minimum-files",
                "2",
            ]
        )
        == 0
    )
    assert len(json.loads(capsys.readouterr().out)["selected"]) == 2


def test_pytest_policy_change_requires_review_but_dependency_pin_change_does_not(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "pyproject.toml", '[project]\nname="example"\nversion="1"\n[tool.pytest.ini_options]\naddopts="-q"')
    base = commit(repo)
    config.pytest_policy = policy_fingerprints(repo, inventory(repo, base))
    cache.snapshot(repo, base, config)
    write(repo, "pyproject.toml", '[project]\nname="example"\nversion="2"\n[tool.pytest.ini_options]\naddopts="-q"')
    head = commit(repo)
    cache.snapshot(repo, head, config)
    write(
        repo,
        "pyproject.toml",
        '[project]\nname="example"\nversion="2"\n[tool.pytest.ini_options]\naddopts="-p custom_plugin"',
    )
    changed = commit(repo)
    with pytest.raises(ValueError, match="pytest configuration changed"):
        cache.snapshot(repo, changed, config)


def test_cli_fingerprints_ini_policy_without_requiring_an_existing_review(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "pytest.ini", "[pytest]\npython_files=test_*.py\n")
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    assert (
        main(["fingerprints", "--repo", str(repo), "--config", str(config_path), "--cache", str(tmp_path / "cache.db")])
        == 0
    )
    fingerprint = json.loads(capsys.readouterr().out)["pytest.ini"]
    assert len(fingerprint) == 64


@pytest.mark.parametrize("mode", ["w", "wb", "a", "x"])
def test_output_only_open_does_not_claim_source_input(mode: str) -> None:
    assert not parse_source(f"open(path, {mode!r})".encode()).opaque
    assert parse_source(f"open(path, {mode + '+'!r})".encode()).opaque
    assert parse_source(b"open(path)").opaque
    assert parse_source(b"client.open(path, 'w')").opaque


@pytest.mark.parametrize(
    "path", [".github/test-impact.json", ".github/workflows/testing.yaml", "pyproject.toml", "config/selection.json"]
)
def test_policy_files_follow_declared_dependencies(
    repo: Path, config: ImpactConfig, cache: GraphCache, path: str
) -> None:
    config.dependencies = [DependencyRule(readers=["tests/left/test_one.py"], inputs=["**"], reason="data reader")]
    write(repo, path, config.model_dump_json() if path == "config/selection.json" else "")
    base = commit(repo)
    config.pytest_policy = policy_fingerprints(repo, inventory(repo, base))
    report = affected(repo, base, base, config, cache, [path], config_path="config/selection.json")
    assert report.selected == ["tests/left/test_one.py"]


@pytest.mark.parametrize("pattern", ["assets/input.json", "assets/*.json", "assets/**/*.json"])
def test_comment_dependency_propagates_from_library_to_test(
    repo: Path, config: ImpactConfig, cache: GraphCache, pattern: str
) -> None:
    write(repo, "src/pkg/leaf.py", f"# gv:test-dependency: {pattern}\nVALUE = 1")
    write(repo, "assets/input.json", "1")
    base = commit(repo)
    write(repo, "assets/input.json", "2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]
    assert explanation(cache.snapshot(repo, head, config), "tests/left/test_one.py", "assets/input.json")[-2:] == [
        "src/pkg/leaf.py",
        "assets/input.json",
    ]


@pytest.mark.parametrize(
    "pattern",
    [
        "missing",
        "assets/*.yaml",
        "",
        "/assets/input.json",
        "../assets/input.json",
        "assets/../input.json",
        "assets/**x",
        "assets/[ab]",
        "assets//input.json",
        "C:/input.json",
        "assets\\input.json",
    ],
)
def test_invalid_comment_dependency_fails_with_location(
    repo: Path, config: ImpactConfig, cache: GraphCache, pattern: str
) -> None:
    write(repo, "src/pkg/leaf.py", f"VALUE = 1\n# gv:test-dependency: {pattern}\n")
    write(repo, "assets/input.json", "1")
    head = commit(repo)
    with pytest.raises(ValueError, match="src/pkg/leaf.py:2"):
        cache.snapshot(repo, head, config)


def test_directive_examples_inside_strings_are_not_dependencies(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/pkg/leaf.py", 'VALUE = """\n# gv:test-dependency: nonexistent\n"""\n')
    head = commit(repo)
    cache.snapshot(repo, head, config)


def test_globs_respect_segments_and_ignored_paths_cannot_hide_dependencies(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    config.ignored_changes = ["docs/**"]
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: docs/*.md\nVALUE = 1")
    write(repo, "docs/a.md", "one")
    write(repo, "docs/deep/a.md", "one")
    base = commit(repo)
    write(repo, "docs/deep/a.md", "two")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == []
    write(repo, "docs/a.md", "two")
    newer = commit(repo)
    assert affected(repo, head, newer, config, cache).selected == ["tests/left/test_one.py"]


def test_removed_declaration_keeps_base_dependents_and_stale_head_is_error(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: input.json\nVALUE = 1")
    write(repo, "input.json", "1")
    base = commit(repo)
    (repo / "input.json").unlink()
    stale = commit(repo)
    with pytest.raises(ValueError, match="input.json"):
        affected(repo, base, stale, config, cache)
    write(repo, "src/pkg/leaf.py", "VALUE = 1")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("declaration", ["inline", "sidecar", "directory"])
def test_invalid_declaration_cli_is_a_hard_error_even_with_full_requested(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str], full: bool, declaration: str
) -> None:
    if declaration == "inline":
        location = "src/pkg/leaf.py:1"
        write(repo, "src/pkg/leaf.py", "# gv:test-dependency: does-not-exist\nVALUE = 1")
    elif declaration == "sidecar":
        location = "src/pkg/leaf.py.gv-dependency.yaml"
        write(repo, location, 'dependencies: [{inputs: ["does-not-exist"]}]')
    else:
        location = "src/pkg/.gv-dependencies.yaml"
        write(repo, location, 'dependencies: [{readers: ["*.py"], inputs: ["does-not-exist"]}]')
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    args = [
        "affected",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--cache",
        str(tmp_path / "cache.db"),
        "--base",
        head,
    ]
    if full:
        args.append("--full")
    assert main(args) == 2
    assert location in capsys.readouterr().err


def test_recursive_glob_re_resolves_added_files_with_cached_reader(
    repo: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: .assets/**/*.json\nVALUE = 1")
    write(repo, ".assets/input.json", "1")
    base = commit(repo)
    cache.snapshot(repo, base, config)
    write(repo, ".assets/deep/new.json", "2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]
    cold = GraphCache(tmp_path / "cold.db")
    try:
        assert cold.snapshot(repo, head, config) == cache.snapshot(repo, head, config)
    finally:
        cold.close()


def test_renamed_input_and_updated_declaration_keep_reader_selected(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: old.json\nVALUE = 1")
    write(repo, "old.json", "1")
    base = commit(repo)
    (repo / "old.json").rename(repo / "new.json")
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: new.json\nVALUE = 1")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_zero_selection_is_not_padded_for_fixed_shards(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = commit(repo)
    write(repo, "unreferenced.env", "A=1")
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                base,
                "--minimum-files",
                "6",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "none"
    assert report["selected"] == []


@pytest.mark.parametrize("policy_in_base", [False, True])
def test_bad_declaration_is_not_hidden_by_collection_policy_fallback(
    repo: Path, config: ImpactConfig, cache: GraphCache, policy_in_base: bool
) -> None:
    if policy_in_base:
        write(repo, "pyproject.toml", '[tool.pytest.ini_options]\naddopts="-q"')
    base = commit(repo)
    write(repo, "pyproject.toml", '[tool.pytest.ini_options]\naddopts="-q"')
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: missing.json\nVALUE = 1")
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match="missing.json"):
        affected(repo, base, head, config, cache)


@pytest.mark.parametrize("owner", ["scripts/render.sh", "config/loader.yaml", "assets/archive.bin"])
def test_sidecars_connect_non_python_readers_to_their_inputs(
    repo: Path, config: ImpactConfig, cache: GraphCache, owner: str
) -> None:
    write(repo, "src/pkg/leaf.py", f"# gv:test-dependency: {owner}\nVALUE = 1")
    write(repo, owner, "not python")
    write(repo, owner + ".gv-dependency.yaml", 'dependencies:\n  - inputs: ["//data/**/*.json"]\n')
    write(repo, "data/deep/input.json", "1")
    base = commit(repo)
    write(repo, "data/deep/input.json", "2")
    head = commit(repo)
    report = affected(repo, base, head, config, cache)
    assert report.selected == ["tests/left/test_one.py"]
    assert explanation(cache.snapshot(repo, head, config), "tests/left/test_one.py", "data/deep/input.json")[-2:] == [
        owner,
        "data/deep/input.json",
    ]
    assert affected(repo, base, head, config, cache).selected == report.selected


@pytest.mark.parametrize("change", ["add", "edit", "remove"])
def test_sidecar_only_changes_select_owner_dependents(
    repo: Path, config: ImpactConfig, cache: GraphCache, change: str
) -> None:
    sidecar = "src/pkg/leaf.py.gv-dependency.yaml"
    if change != "add":
        write(repo, sidecar, "dependencies: []\n# Description\n")
    base = commit(repo)
    if change == "remove":
        (repo / sidecar).unlink()
    else:
        write(repo, sidecar, "dependencies: []\n# Changed description\n")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


@pytest.mark.parametrize("input_path", ["inline.json", "sidecar.json"])
def test_inline_and_sidecar_dependencies_are_additive(
    repo: Path, config: ImpactConfig, cache: GraphCache, input_path: str
) -> None:
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: inline.json\nVALUE = 1")
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies:\n  - inputs: ["//sidecar.json"]\n')
    for path in ["inline.json", "sidecar.json"]:
        write(repo, path, "1")
    base = commit(repo)
    write(repo, input_path, "2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


@pytest.mark.parametrize(
    "contents",
    [
        'dependencies: [{inputs: ["//missing.json"]}]',
        'dependencies: [{inputs: ["//data/*.yaml"]}]',
        'dependencies: [{inputs: ["../escape"]}]',
        "dependencies: [{inputs: []}]",
        'dependencies: [{inputs: ["//src/pkg/leaf.py"], kind: unknown}]',
        'dependencies: [{inputs: ["//src/pkg/leaf.py"], readers: ["*.py"]}]',
        "dependencies: [data.json]",
    ],
)
def test_bad_sidecar_reports_its_own_file(repo: Path, config: ImpactConfig, cache: GraphCache, contents: str) -> None:
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", "# explanatory comment\n" + contents)
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match=r"src/pkg/leaf.py.gv-dependency.yaml"):
        cache.snapshot(repo, head, config)


@pytest.mark.parametrize("owner", ["missing.sh", "src/pkg/leaf.py.gv-dependency.yaml"])
def test_orphan_and_nested_sidecars_are_errors(repo: Path, config: ImpactConfig, cache: GraphCache, owner: str) -> None:
    write(repo, owner + ".gv-dependency.yaml", "dependencies: []")
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match="sidecar"):
        cache.snapshot(repo, head, config)


def test_unreferenced_sidecar_does_not_activate_tests(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "unused.sh", "#!/bin/sh\n")
    base = commit(repo)
    write(repo, "unused.sh.gv-dependency.yaml", 'dependencies:\n  - inputs: ["src/pkg/leaf.py"]\n')
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == []


@pytest.mark.parametrize("change", ["delete_owner", "delete_all", "rename"])
def test_sidecar_owner_lifecycle_preserves_old_dependents(
    repo: Path, config: ImpactConfig, cache: GraphCache, change: str
) -> None:
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies:\n  - inputs: ["//data.json"]\n')
    write(repo, "data.json", "1")
    base = commit(repo)
    if change == "rename":
        (repo / "src/pkg/leaf.py").rename(repo / "src/pkg/moved.py")
        (repo / "src/pkg/leaf.py.gv-dependency.yaml").rename(repo / "src/pkg/moved.py.gv-dependency.yaml")
    else:
        (repo / "src/pkg/leaf.py").unlink()
        if change == "delete_all":
            (repo / "src/pkg/leaf.py.gv-dependency.yaml").unlink()
            (repo / "data.json").unlink()
    head = commit(repo)
    if change == "delete_owner":
        with pytest.raises(DependencyDeclarationError, match="sidecar"):
            affected(repo, base, head, config, cache)
    else:
        assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]


def test_sidecar_cache_re_resolves_globs_and_agrees_with_cold_graph(
    repo: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies:\n  - inputs: ["//data/*.json"]\n')
    write(repo, "data/a.json", "1")
    base = commit(repo)
    cache.snapshot(repo, base, config)
    write(repo, "data/b.json", "2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]
    cold = GraphCache(tmp_path / "cold-sidecar.db")
    try:
        assert cold.snapshot(repo, head, config) == cache.snapshot(repo, head, config)
    finally:
        cold.close()


@pytest.mark.parametrize("kind,selected", [("content", []), ("import", ["tests/right/test_two.py"])])
def test_directory_rules_distinguish_reading_source_from_executing_it(
    repo: Path, config: ImpactConfig, cache: GraphCache, kind: str, selected: list[str]
) -> None:
    write(
        repo,
        "tests/.gv-dependencies.yaml",
        f"""dependencies:
  - readers: ["right/**/*.py"]
    inputs: ["//src/pkg/helper.py"]
    kind: {kind}
""",
    )
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "VALUE = 2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == sorted(["tests/left/test_one.py", *selected])
    write(repo, "src/pkg/helper.py", "from .leaf import VALUE\n# changed bytes")
    newer = commit(repo)
    assert affected(repo, head, newer, config, cache).selected == ["tests/left/test_one.py", "tests/right/test_two.py"]


@pytest.mark.parametrize("change", ["add", "edit", "remove", "narrow"])
def test_directory_declaration_changes_keep_old_and_new_readers(
    repo: Path, config: ImpactConfig, cache: GraphCache, change: str
) -> None:
    path = "tests/.gv-dependencies.yaml"
    manifest = 'dependencies: [{readers: ["**/test_*.py"], inputs: ["//data.json"]}]'
    write(repo, "data.json", "1")
    if change != "add":
        write(repo, path, manifest)
    base = commit(repo)
    if change == "remove":
        (repo / path).unlink()
    else:
        write(
            repo, path, manifest.replace("**/test_*.py", "left/*.py") if change == "narrow" else manifest + "\n# reason"
        )
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py", "tests/right/test_two.py"]


def test_nested_manifests_are_additive_and_exclude_metadata_readers(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/.gv-dependencies.yaml", 'dependencies: [{readers: ["**/*"], inputs: ["//data.json"]}]')
    write(repo, "tests/left/.gv-dependencies.yaml", 'dependencies: [{readers: ["*.py"], inputs: ["local.json"]}]')
    write(repo, "tests/left/test_one.py.gv-dependency.yaml", "dependencies: []")
    write(repo, "tests/left/local.json", "1")
    write(repo, "data.json", "1")
    base = commit(repo)
    graph = cache.snapshot(repo, base, config)
    assert "tests/.gv-dependencies.yaml" not in graph.edges
    assert "tests/left/.gv-dependencies.yaml" not in graph.edges
    assert "tests/left/test_one.py.gv-dependency.yaml" not in graph.edges
    write(repo, "tests/left/local.json", "2")
    head = commit(repo)
    assert affected(repo, base, head, config, cache).selected == ["tests/left/test_one.py"]
    write(repo, "data.json", "2")
    newer = commit(repo)
    assert affected(repo, head, newer, config, cache).selected == ["tests/left/test_one.py", "tests/right/test_two.py"]


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "# only a comment",
        "dependencies: null",
        "unknown: []",
        'dependencies: [{inputs: ["//src/pkg/leaf.py"]}]',
        'dependencies: [{readers: [], inputs: ["//src/pkg/leaf.py"]}]',
        'dependencies: [{readers: ["**/*.py", "missing*.py"], inputs: ["//src/pkg/leaf.py"]}]',
        'dependencies: [{readers: ["**/*.py"], inputs: ["//src/pkg/leaf.py", "missing*"]}]',
        'dependencies: [{readers: ["../*.py"], inputs: ["//src/pkg/leaf.py"]}]',
        'dependencies: [{readers: ["**/*.py"], inputs: ["/src/pkg/leaf.py"]}]',
        'dependencies: [{readers: ["**/*.py"], inputs: ["//src/pkg/leaf.py"], expensive: true}]',
        "dependencies: []\ndependencies: []",
        'dependencies: [{readers: &paths ["**/*.py"], inputs: *paths}]',
    ],
)
def test_directory_manifest_errors_are_never_silently_ignored(
    repo: Path, config: ImpactConfig, cache: GraphCache, contents: str
) -> None:
    write(repo, "tests/.gv-dependencies.yaml", contents)
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match=r"tests/\.gv-dependencies.yaml"):
        cache.snapshot(repo, head, config)


def test_directory_reader_glob_expands_new_files_with_cached_manifest(
    repo: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    write(repo, "tests/.gv-dependencies.yaml", 'dependencies: [{readers: ["right/**/*.py"], inputs: ["//data.json"]}]')
    write(repo, "data.json", "1")
    base = commit(repo)
    cache.snapshot(repo, base, config)
    write(repo, "tests/right/deep/test_new.py", "def test_new(): pass")
    head = commit(repo)
    expected = ["tests/right/deep/test_new.py", "tests/right/test_two.py"]
    assert affected(repo, head, head, config, cache, ["data.json"]).selected == expected
    cold = GraphCache(tmp_path / "directory-cold.db")
    try:
        assert cold.snapshot(repo, head, config) == cache.snapshot(repo, head, config)
    finally:
        cold.close()


def test_explain_accepts_real_paths_for_content_dependencies(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies: [{inputs: ["//input.json"], kind: content}]')
    write(repo, "input.json", "1")
    head = commit(repo)
    assert explanation(cache.snapshot(repo, head, config), "tests/left/test_one.py", "input.json") == [
        "tests/left/test_one.py",
        "src/pkg/helper.py",
        "src/pkg/leaf.py",
        "input.json",
    ]


def test_warm_builds_only_head_and_reuses_it_after_restart(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    cache_path = tmp_path / "warm.sqlite3"
    arguments = [
        "warm",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--cache",
        str(cache_path),
        "--head",
        head,
    ]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["total_files"] == 2
    assert first["parsed_blobs"] > 0
    assert main(arguments) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["head"] == first["head"]
    assert second["parsed_blobs"] == 0
    assert second["snapshot_hits"] == 1


@pytest.mark.timeout(60)
def test_isolated_warm_action_loads_sidecars(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    """Run the shipped action with real uv: installed project dependencies cannot hide missing CLI packages."""
    write(repo, "src/pkg/leaf.py.gv-dependency.yaml", 'dependencies: [{inputs: ["//input.json"]}]')
    write(repo, "input.json", "1")
    write(repo, "config.json", config.model_dump_json())
    commit(repo)
    action = yaml.safe_load(Path(".github/actions/test-impact/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "select")
    summary = tmp_path / "summary"
    output = tmp_path / "output"
    env = dict(
        os.environ,
        IMPACT_WARM_ONLY="true",
        IMPACT_CONFIG="config.json",
        IMPACT_HEAD="HEAD",
        GITHUB_STEP_SUMMARY=summary.as_posix(),
        GITHUB_OUTPUT=output.as_posix(),
        SHARED_ACTION_PATH=Path(".github/actions/test-impact").resolve().as_posix(),
    )
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    # Resolve PATH explicitly: Windows' bare executable lookup may choose the
    # WSL launcher in System32 instead of the Git Bash available on PATH.
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-euo", "pipefail", "-c", step["run"]],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=50,
    )
    assert result.returncode == 0, result.stderr
    assert summary.exists(), result.stdout + result.stderr
    assert "cache is ready" in summary.read_text()
    assert not output.exists()
    warmed = GraphCache(repo / ".test-impact/cache.sqlite3")
    try:
        snapshot = warmed.snapshot(repo, "HEAD", config)
        # The action uses Python 3.14. Older local parsers must rebuild rather
        # than trust a graph parsed under a different syntax version.
        assert warmed.snapshot_hits == int(sys.version_info[:2] == (3, 14))
        assert explanation(snapshot, "tests/left/test_one.py", "input.json")[-1:] == ["input.json"]
    finally:
        warmed.close()


@pytest.mark.parametrize("succeeds", [True, False])
def test_cache_warming_never_selects_tests_or_fetches_a_base(tmp_path: Path, succeeds: bool) -> None:
    action = yaml.safe_load(Path(".github/actions/test-impact/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "select")
    output = tmp_path / "github-output"
    summary = tmp_path / "summary"
    invocation = tmp_path / "invocation"
    script = tmp_path / "warm.sh"
    # The real CLI's persistent graph behavior is exercised above. Here the
    # process boundary records the action's invocation and simulates failure.
    script.write_text(
        "set -euo pipefail\n"
        + "git() { echo 'warming must not fetch a base' >&2; exit 90; }\n"
        + 'uv() { printf "%s\\n" "$@" > "$INVOCATION"; return '
        + ("0" if succeeds else "1")
        + "; }\n"
        + step["run"],
        newline="\n",
    )
    env = dict(
        os.environ,
        IMPACT_WARM_ONLY="true",
        IMPACT_CONFIG="consumer.json",
        IMPACT_HEAD="merged-head",
        GITHUB_OUTPUT=output.as_posix(),
        GITHUB_STEP_SUMMARY=summary.as_posix(),
        INVOCATION=invocation.as_posix(),
        SHARED_ACTION_PATH=Path(".github/actions/test-impact").resolve().as_posix(),
    )
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run([bash, script.as_posix()], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert invocation.read_text().splitlines()[-5:] == ["warm", "--config", "consumer.json", "--head", "merged-head"]
    assert not output.exists()
    if succeeds:
        assert "cache is ready" in summary.read_text()
    else:
        assert "::warning::" in result.stdout
        assert not summary.exists()


@pytest.mark.parametrize(
    "changed,expected",
    [
        ("assets/inline.json", ["tests/left/test_one.py"]),
        ("assets/file-new.json", ["tests/left/test_one.py"]),
        ("assets/directory-new.json", ["tests/right/test_two.py"]),
        ("src/pkg/helper.py.gv-dependency.yaml", ["tests/left/test_one.py"]),
        ("tests/right/.gv-dependencies.yaml", ["tests/right/test_two.py"]),
        ("undeclared.env", []),
    ],
)
def test_warm_cli_preserves_declaration_selection(
    repo: Path, config: ImpactConfig, tmp_path: Path, changed: str, expected: list[str]
) -> None:
    write(repo, "src/pkg/leaf.py", "# gv:test-dependency: assets/inline.json\nVALUE = 1")
    write(
        repo, "src/pkg/helper.py.gv-dependency.yaml", 'dependencies: [{inputs: ["//assets/file*.json"], kind: content}]'
    )
    write(
        repo,
        "tests/right/.gv-dependencies.yaml",
        'dependencies: [{readers: ["*.py"], inputs: ["//assets/directory*.json"]}]',
    )
    for name in ["inline", "file", "directory"]:
        write(repo, f"assets/{name}.json", "1")
    base = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    warm_path = tmp_path / "warmed.sqlite3"
    arguments = ["warm", "--repo", str(repo), "--config", str(config_path), "--cache", str(warm_path)]
    assert main(arguments) == 0
    if changed.endswith(".yaml"):
        write(repo, changed, (repo / changed).read_text() + "\n# Updated declaration rationale\n")
    else:
        write(repo, changed, "2")
    head = commit(repo)
    assert main(arguments) == 0
    warmed = GraphCache(warm_path)
    cold = GraphCache(tmp_path / "cold.sqlite3")
    try:
        warm_report = affected(repo, base, head, config, warmed)
        cold_report = affected(repo, base, head, config, cold)
        assert warm_report.selected == cold_report.selected == expected
        assert warm_report.mode == cold_report.mode
        assert warm_report.reasons == cold_report.reasons
        assert warmed.parsed_blobs == 0
        assert warmed.snapshot_hits == 2
    finally:
        warmed.close()
        cold.close()


@pytest.mark.parametrize(
    "declaration", ["src/pkg/leaf.py", "src/pkg/leaf.py.gv-dependency.yaml", "tests/.gv-dependencies.yaml"]
)
def test_warm_cli_rejects_invalid_declarations_on_repeated_attempts(
    repo: Path, config: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str], declaration: str
) -> None:
    if declaration.endswith(".py"):
        content = "# gv:test-dependency: missing.env"
    elif declaration.endswith(".gv-dependencies.yaml"):
        content = 'dependencies: [{readers: ["**/*.py"], inputs: ["//missing*.env"]}]'
    else:
        content = 'dependencies: [{inputs: ["//missing.env"]}]'
    write(repo, declaration, content)
    commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    for _ in range(2):
        assert (
            main(["warm", "--repo", str(repo), "--config", str(config_path), "--cache", str(tmp_path / "warm.db")]) == 2
        )
        assert declaration in capsys.readouterr().err


@pytest.fixture
def django_graph(repo: Path, config: ImpactConfig) -> ImpactConfig:
    write(repo, "src/pkg/settings.py", "ROOT_URLCONF = 'pkg.urls'\nSECRET_KEY = 'test'\n")
    write(
        repo, "src/pkg/views.py", "from django.http import HttpResponse\ndef home(request): return HttpResponse('ok')\n"
    )
    write(
        repo,
        "src/pkg/urls.py",
        "from django.urls import path\nfrom .views import home\nurlpatterns = [path('home/', home)]\n",
    )
    write(repo, "tests/http/test_home.py", "def test_http_only(): pass\n")
    write(repo, "tests/startup/test_urls.py", "def test_startup(): pass\n")
    return ImpactConfig.model_validate(
        {
            **config.model_dump(),
            "global_modules": ["pkg.settings"],
            "django_urlconf": {
                "settings_file": "src/pkg/settings.py",
                "http_tests": ["tests/http/**"],
                "startup_tests": ["tests/startup/test_urls.py"],
            },
        }
    )


def test_django_registration_keeps_http_only_callers_and_startup_checks(
    repo: Path,
    django_graph: ImpactConfig,
    cache: GraphCache,
) -> None:
    base = commit(repo)
    write(repo, "src/pkg/views.py", "raise RuntimeError('broken startup')\n")
    head = commit(repo)
    report = affected(repo, base, head, django_graph, cache)
    assert report.selected == ["tests/http/test_home.py", "tests/startup/test_urls.py"]
    assert cache.snapshot(repo, head, django_graph) == cache.snapshot(repo, head, django_graph)
    # Settings themselves remain invocation-wide, including non-HTTP tests.
    assert affected(repo, head, head, django_graph, cache, extra_files=["src/pkg/settings.py"]).mode == "full"


def test_django_default_remains_conservative(repo: Path, django_graph: ImpactConfig, cache: GraphCache) -> None:
    baseline = django_graph.model_copy(update={"django_urlconf": None})
    head = commit(repo)
    assert affected(repo, head, head, baseline, cache, extra_files=["src/pkg/views.py"]).mode == "full"


@pytest.mark.parametrize("settings", ["ROOT_URLCONF = get_urlconf()", "ROOT_URLCONF = 'pkg.missing'", ""])
def test_django_registration_requires_resolvable_literal(
    repo: Path,
    django_graph: ImpactConfig,
    cache: GraphCache,
    settings: str,
) -> None:
    write(repo, "src/pkg/settings.py", settings)
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match="ROOT_URLCONF"):
        cache.snapshot(repo, head, django_graph)


def test_django_explicit_import_is_never_cut(repo: Path, django_graph: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "src/pkg/settings.py", "from . import urls\nROOT_URLCONF = 'pkg.urls'\n")
    head = commit(repo)
    assert affected(repo, head, head, django_graph, cache, extra_files=["src/pkg/views.py"]).mode == "full"


def test_django_route_removal_preserves_old_dependents(
    repo: Path,
    django_graph: ImpactConfig,
    cache: GraphCache,
) -> None:
    base = commit(repo)
    write(repo, "src/pkg/urls.py", "urlpatterns = []\n")
    (repo / "src/pkg/views.py").unlink()
    head = commit(repo)
    assert affected(repo, base, head, django_graph, cache).selected == [
        "tests/http/test_home.py",
        "tests/startup/test_urls.py",
    ]


def test_django_missing_consumers_fail_planning(repo: Path, django_graph: ImpactConfig, cache: GraphCache) -> None:
    (repo / "tests/startup/test_urls.py").unlink()
    head = commit(repo)
    with pytest.raises(DependencyDeclarationError, match="matches no"):
        cache.snapshot(repo, head, django_graph)


def test_django_adoption_retains_old_global_edges_until_after_merge(
    repo: Path,
    config: ImpactConfig,
    django_graph: ImpactConfig,
    cache: GraphCache,
) -> None:
    old_config = django_graph.model_copy(update={"django_urlconf": None})
    (repo / "tests/startup/test_urls.py").unlink()
    write(repo, "selection.json", old_config.model_dump_json())
    base = commit(repo)
    write(repo, "tests/startup/test_urls.py", "def test_startup(): pass")
    write(repo, "selection.json", django_graph.model_dump_json())
    write(repo, "src/pkg/views.py", "raise RuntimeError('broken')")
    head = commit(repo)
    report = affected(repo, base, head, django_graph, cache, config_path="selection.json")
    assert report.mode == "full"


#: A Celery-style setting: modules the framework imports only when a worker starts.
WORKER_MARKERS = ["start_worker(", "init_worker("]


@pytest.fixture
def deferred_graph(repo: Path, config: ImpactConfig) -> ImpactConfig:
    write(repo, "src/pkg/settings.py", "CELERY_IMPORTS = ('pkg.tasks',)\nSECRET_KEY = 'test'\n")
    write(repo, "src/pkg/tasks.py", "from pkg.billing import charge\ndef nightly(): charge()\n")
    write(repo, "src/pkg/billing.py", "def charge(): pass\n")
    write(repo, "tests/worker/test_worker.py", "from celery.contrib.testing.worker import start_worker\n")
    write(repo, "tests/plain/test_plain.py", "def test_plain(): pass\n")
    rule = {
        "file": "src/pkg/settings.py",
        "assignment": "CELERY_IMPORTS",
        "consumers": ["tests/worker/**"],
        "consumer_markers": WORKER_MARKERS,
        "reason": "Celery imports CELERY_IMPORTS only when a worker starts.",
    }
    return ImpactConfig.model_validate(
        {**config.model_dump(), "global_modules": ["pkg.settings"], "deferred_strings": [rule]}
    )


def test_deferred_names_reach_their_consumers_not_every_user_of_the_file_naming_them(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    base = commit(repo)
    write(repo, "src/pkg/billing.py", "def charge(): raise RuntimeError('broken')\n")
    head = commit(repo)

    assert affected(repo, base, head, deferred_graph, cache).selected == ["tests/worker/test_worker.py"]
    # The file holding the names still reaches every test.
    assert affected(repo, head, head, deferred_graph, cache, extra_files=["src/pkg/settings.py"]).mode == "full"


def test_without_a_rule_names_in_a_global_module_stay_global(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    baseline = deferred_graph.model_copy(update={"deferred_strings": []})
    head = commit(repo)

    assert affected(repo, head, head, baseline, cache, extra_files=["src/pkg/billing.py"]).mode == "full"


@pytest.mark.parametrize("marker", WORKER_MARKERS)
def test_a_file_with_a_consumer_marker_that_is_not_a_consumer_fails_planning(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache, marker: str
) -> None:
    write(repo, "tests/plain/test_plain.py", f"def test_plain(app):\n    app.{marker})\n")
    head = commit(repo)

    with pytest.raises(DependencyDeclarationError, match="tests/plain/test_plain.py"):
        cache.snapshot(repo, head, deferred_graph)


@pytest.mark.parametrize(
    "settings",
    [
        "CELERY_IMPORTS = computed()",
        "CELERY_IMPORTS = ('pkg.tasks',)\nCELERY_IMPORTS += ('pkg.billing',)",
        "SECRET_KEY = 'test'",
        "CELERY_IMPORTS = (",
    ],
    ids=["computed", "reassigned", "missing", "unparseable"],
)
def test_a_deferred_assignment_must_be_one_top_level_assignment_naming_modules(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache, settings: str
) -> None:
    write(repo, "src/pkg/settings.py", settings)
    head = commit(repo)

    with pytest.raises(DependencyDeclarationError, match="CELERY_IMPORTS"):
        cache.snapshot(repo, head, deferred_graph)


def test_a_deferred_name_used_elsewhere_in_its_file_stays_an_edge(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/pkg/settings.py", "CELERY_IMPORTS = ('pkg.tasks',)\nHANDLER = 'pkg.tasks'\n")
    head = commit(repo)

    assert affected(repo, head, head, deferred_graph, cache, extra_files=["src/pkg/billing.py"]).mode == "full"


def test_two_rules_deferring_different_assignments_of_one_file_both_apply(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo, "src/pkg/settings.py", "CELERY_IMPORTS = ('pkg.tasks',)\nSCHEDULE = {'nightly': 'pkg.billing.charge'}\n"
    )
    [imports] = deferred_graph.deferred_strings
    schedule = imports.model_copy(update={"assignments": ["SCHEDULE"]})
    config = deferred_graph.model_copy(update={"deferred_strings": [imports, schedule]})
    base = commit(repo)
    write(repo, "src/pkg/billing.py", "def charge(): raise RuntimeError('broken')\n")
    head = commit(repo)

    # Neither name stays an edge of settings, so only the consumer selects the changed module.
    assert affected(repo, base, head, config, cache).selected == ["tests/worker/test_worker.py"]


def test_a_name_two_deferred_assignments_of_one_file_share_is_deferred_by_both(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo,
        "src/pkg/settings.py",
        "CELERY_IMPORTS = ('pkg.tasks',)\n"
        "ROUTES = {'pkg.billing.charge': 'billing'}\n"
        "SCHEDULE = {'nightly': 'pkg.billing.charge'}\n",
    )
    [imports] = deferred_graph.deferred_strings
    routes, schedule = (imports.model_copy(update={"assignments": [name]}) for name in ("ROUTES", "SCHEDULE"))
    config = deferred_graph.model_copy(update={"deferred_strings": [imports, routes, schedule]})
    base = commit(repo)
    write(repo, "src/pkg/billing.py", "def charge(): raise RuntimeError('broken')\n")
    head = commit(repo)

    # A task routed and scheduled is named in both, and neither copy is an edge of settings.
    assert affected(repo, base, head, config, cache).selected == ["tests/worker/test_worker.py"]


def test_one_rule_can_defer_several_assignments_to_one_consumer_list(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo,
        "src/pkg/settings.py",
        "CELERY_IMPORTS = ('pkg.tasks',)\n"
        "ROUTES = {'pkg.billing.charge': 'billing'}\n"
        "SCHEDULE = {'nightly': 'pkg.billing.charge'}\n",
    )
    [imports] = deferred_graph.deferred_strings
    celery = DeferredStringsRule.model_validate(
        {**imports.model_dump(exclude={"assignments"}), "assignments": ["CELERY_IMPORTS", "ROUTES", "SCHEDULE"]}
    )
    config = deferred_graph.model_copy(update={"deferred_strings": [celery]})
    base = commit(repo)
    write(repo, "src/pkg/billing.py", "def charge(): raise RuntimeError('broken')\n")
    head = commit(repo)

    # The same result as one rule per assignment, with the consumer list written once.
    assert affected(repo, base, head, config, cache).selected == ["tests/worker/test_worker.py"]


def test_each_of_a_rules_assignments_must_be_one_top_level_assignment_naming_modules(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    [imports] = deferred_graph.deferred_strings
    celery = imports.model_copy(update={"assignments": ["CELERY_IMPORTS", "SCHEDULE"]})
    config = deferred_graph.model_copy(update={"deferred_strings": [celery]})
    head = commit(repo)

    with pytest.raises(DependencyDeclarationError, match="needs one top-level SCHEDULE assignment"):
        cache.snapshot(repo, head, config)


DEFERRED_RULE = {"file": "settings.py", "consumers": ["tests/**"], "reason": "a worker loads them"}


@pytest.mark.parametrize(
    ("spelling", "assignments"),
    [({"assignment": "A"}, ["A"]), ({"assignments": ["A", "B"]}, ["A", "B"])],
    ids=["one, as existing configs write it", "several"],
)
def test_a_rule_names_its_assignments_in_either_spelling(spelling: dict[str, object], assignments: list[str]) -> None:
    rule = DeferredStringsRule.model_validate({**DEFERRED_RULE, **spelling})

    assert rule.assignments == assignments
    # The graph cache stores the dumped configuration; it must read back as the same rule.
    assert DeferredStringsRule.model_validate(rule.model_dump()) == rule


@pytest.mark.parametrize(
    "spelling",
    [
        {"assignment": "A", "assignments": ["B"]},
        {"assignments": []},
        {"assignments": ["A", "A"]},
        {"assignments": "CELERY_IMPORTS"},
        {"assignment": ["A"]},
        {},
    ],
    ids=["both spellings", "empty", "repeated", "a string, not a list", "a list under the singular key", "neither"],
)
def test_a_rule_without_exactly_one_list_of_distinct_assignments_is_rejected(spelling: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DeferredStringsRule.model_validate({**DEFERRED_RULE, **spelling})


def test_a_consumer_pattern_that_matches_nothing_fails_planning(
    repo: Path, deferred_graph: ImpactConfig, cache: GraphCache
) -> None:
    (repo / "tests/worker/test_worker.py").unlink()
    head = commit(repo)

    with pytest.raises(DependencyDeclarationError, match="matches no"):
        cache.snapshot(repo, head, deferred_graph)


# --- A base the configuration cannot describe is an unavailable proof, never an authoring error ---
#
# Exit 2 means "fix a declaration in this PR"; a PR cannot edit its base. When the base had no
# configuration of its own at the config's path (moved, kept outside the repo, adopted here) the
# head's declarations were validated against the base tree, and a rename in the same PR turned
# that mismatch into a hard CI failure with no full-suite fallback.

SETTINGS = "src/pkg/settings.py"
RENAMED_SETTINGS = "src/pkg/settings_base.py"
CONFIG = ".github/test-impact.json"
MOVED_CONFIG = ".github/impact.json"


def with_settings(django_graph: ImpactConfig, settings_file: str) -> ImpactConfig:
    """The Django policy pointed at `settings_file`, which every test also loads."""
    assert django_graph.django_urlconf is not None
    module = settings_file.removeprefix("src/").removesuffix(".py").replace("/", ".")
    policy = django_graph.django_urlconf.model_copy(update={"settings_file": settings_file})
    return django_graph.model_copy(update={"django_urlconf": policy, "global_modules": [module]})


def rename_settings(repo: Path) -> None:
    (repo / SETTINGS).rename(repo / RENAMED_SETTINGS)


def config_moved_with_the_settings_it_names(repo: Path, django_graph: ImpactConfig, tmp_path: Path) -> Path:
    write(repo, CONFIG, django_graph.model_dump_json())
    commit(repo)
    rename_settings(repo)
    (repo / CONFIG).unlink()
    write(repo, MOVED_CONFIG, with_settings(django_graph, RENAMED_SETTINGS).model_dump_json())
    return repo / MOVED_CONFIG


def config_outside_the_repo(repo: Path, django_graph: ImpactConfig, tmp_path: Path) -> Path:
    commit(repo)
    rename_settings(repo)
    outside = tmp_path / "outside.json"
    outside.write_text(with_settings(django_graph, RENAMED_SETTINGS).model_dump_json())
    return outside


def config_adopted_with_its_startup_check(repo: Path, django_graph: ImpactConfig, tmp_path: Path) -> Path:
    (repo / "tests/startup/test_urls.py").unlink()
    commit(repo)
    write(repo, "tests/startup/test_urls.py", "def test_startup(): pass\n")
    write(repo, CONFIG, django_graph.model_dump_json())
    return repo / CONFIG


def config_this_version_rejects_at_the_base(repo: Path, django_graph: ImpactConfig, tmp_path: Path) -> Path:
    write(repo, CONFIG, json.dumps({**json.loads(django_graph.model_dump_json()), "retired_option": True}))
    commit(repo)
    write(repo, CONFIG, django_graph.model_dump_json())
    return repo / CONFIG


@pytest.mark.parametrize(
    "history",
    [
        config_moved_with_the_settings_it_names,
        config_outside_the_repo,
        config_adopted_with_its_startup_check,
        config_this_version_rejects_at_the_base,
    ],
)
def test_undescribable_base_falls_back_to_the_complete_suite(
    repo: Path,
    django_graph: ImpactConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    history: Callable[[Path, ImpactConfig, Path], Path],
) -> None:
    """INVARIANT: only the head can fail planning with exit 2; a base problem is exit 1 (complete suite)."""
    config_file = history(repo, django_graph, tmp_path)
    base = head_of(repo)
    head = commit(repo)
    result = affected_cli(repo, config_file, tmp_path, "--base", base, "--head", head)
    error = capsys.readouterr().err
    assert result.status == 1, error
    assert "planning failed" in error
    assert base in error


def test_undescribable_alternate_base_keeps_the_proven_selection(
    repo: Path, django_graph: ImpactConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = config_this_version_rejects_at_the_base(repo, django_graph, tmp_path)
    alternate = head_of(repo)
    base = commit(repo)
    write(repo, "tests/right/test_two.py", "def test_other(): assert 2")
    head = commit(repo)
    result = affected_cli(repo, config_file, tmp_path, "--base", base, "--head", head, "--alternate-base", alternate)
    assert result.status == 0, capsys.readouterr().err
    assert result.outputs["base"] == base
    assert result.selected == ["tests/right/test_two.py"]


def test_cli_sizes_shards_from_measured_duration_not_file_count(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    """
    INVARIANT: the published shard_count follows the selected work.

    Two selected files are one shard by file count. When the manifest says they
    hold five minutes of work, the default gate must plan more than one shard
    rather than run a scoped selection for as long as a complete suite.
    """
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    extra = tmp_path / "changed.txt"
    extra.write_text("tests/left/test_one.py\ntests/right/test_two.py")
    durations = tmp_path / "durations.json"
    durations.write_text(
        json.dumps({"tests/left/test_one.py::test_value": 150.0, "tests/right/test_two.py::test_other": 150.0})
    )
    output = tmp_path / "github-output"

    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                head,
                "--extra-files",
                str(extra),
                "--durations",
                str(durations),
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert "shard_count=2" in output.read_text()


def test_cli_shard_sizing_survives_a_missing_duration_manifest(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    """
    CONTROL: the same selection without timings still plans, at the file-count shape.

    The manifest is restored from cache and is routinely absent; an unreadable
    one must not fail planning or publish an empty shard count.
    """
    head = commit(repo)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    extra = tmp_path / "changed.txt"
    extra.write_text("tests/left/test_one.py\ntests/right/test_two.py")
    output = tmp_path / "github-output"

    assert (
        main(
            [
                "affected",
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cache.db"),
                "--base",
                head,
                "--extra-files",
                str(extra),
                "--durations",
                str(tmp_path / "absent-durations.json"),
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert "shard_count=1" in output.read_text()


@pytest.mark.parametrize(
    "path, source",
    [
        ("pytest.toml", '[pytest]\naddopts = "-q"\n'),
        (".pytest.toml", '[pytest]\naddopts = "-q"\n'),
        (".pytest.ini", "[pytest]\naddopts = -q\n"),
        ("tests/pytest.toml", '[pytest]\naddopts = "-q"\n'),
        ("pytest.ini", "[pytest]\naddopts = -q\n"),
        ("tox.ini", "[pytest]\naddopts = -q\n"),
        ("setup.cfg", "[tool:pytest]\naddopts = -q\n"),
        ("pyproject.toml", '[tool.pytest]\naddopts = "-q"\n'),
    ],
)
def test_collection_config_add_edit_delete_requires_review(
    repo: Path,
    config: ImpactConfig,
    cache: GraphCache,
    path: str,
    source: str,
) -> None:
    """Every pytest config spelling affects collection, including addition and deletion."""
    base = commit(repo)
    write(repo, path, source)
    added = commit(repo)
    with pytest.raises(ValueError, match="pytest configuration changed"):
        affected(repo, base, added, config, cache)
    config.pytest_policy = policy_fingerprints(repo, inventory(repo, added))
    cache.snapshot(repo, added, config)
    write(repo, path, source.replace("-q", "-x"))
    edited = commit(repo)
    with pytest.raises(ValueError, match="pytest configuration changed"):
        affected(repo, added, edited, config, cache)
    (repo / path).unlink()
    deleted = commit(repo)
    with pytest.raises(ValueError, match="pytest configuration changed"):
        affected(repo, added, deleted, config, cache)


def test_explicit_pytest_config_is_fingerprinted_and_cannot_skip_collection_changes(
    repo: Path,
    config: ImpactConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A config supplied to pytest -c must also be part of planning and cache identity."""
    config = ImpactConfig.model_validate({**config.model_dump(), "pytest_config_files": ["ci/custom.conf"]})
    write(repo, "ci/custom.conf", "[pytest]\npython_files=test_*.py\n")
    base = commit(repo)
    config_path = tmp_path / "selection.json"
    config_path.write_text(config.model_dump_json())
    args = ["--repo", str(repo), "--config", str(config_path), "--cache", str(tmp_path / "cache.db")]
    assert main(["fingerprints", *args]) == 0
    config.pytest_policy = json.loads(capsys.readouterr().out)
    assert "ci/custom.conf" in config.pytest_policy
    config_path.write_text(config.model_dump_json())
    assert main(["warm", *args]) == 0
    capsys.readouterr()
    write(repo, "ci/custom.conf", "[pytest]\npython_files=check_*.py\n")
    commit(repo)
    assert main(["affected", "--base", base, *args]) == 1
    assert "pytest configuration changed" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["/tmp/pytest.ini", "../pytest.ini", "ci/*.ini", "C:/pytest.ini", "ci//pytest.ini"])
def test_custom_collection_config_requires_literal_repository_path(path: str) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        ImpactConfig(test_roots=["tests"], pytest_config_files=[path])


def test_missing_custom_collection_config_cannot_prove_selection(
    repo: Path,
    config: ImpactConfig,
    cache: GraphCache,
) -> None:
    config.pytest_config_files = ["missing.ini"]
    head = commit(repo)
    with pytest.raises(ValueError, match="configuration missing"):
        affected(repo, head, head, config, cache)


def counted_git(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from pytest_selective import impact_graph

    calls: list[str] = []
    original = impact_graph.git

    def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
        calls.append(args[0])
        return original(repo, *args, data=data)

    monkeypatch.setattr(impact_graph, "git", git)
    return calls


def test_inventory_reuses_listings_of_known_commits(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Fixture trees repeat across tests; a unique file keeps this listing uncached.
    write(repo, "unique.txt", str(repo))
    base = commit(repo)
    calls = counted_git(monkeypatch)
    first = inventory(repo, base)
    assert inventory(repo, base) == first
    assert calls == ["rev-parse", "ls-tree"]


def test_inventory_re_resolves_moving_revisions(repo: Path) -> None:
    commit(repo)
    before = inventory(repo, "HEAD")
    write(repo, "src/pkg/new.py", "NEW = 1")
    commit(repo)
    after = inventory(repo, "HEAD")
    assert "src/pkg/new.py" in after.files
    assert after.tree != before.tree


def test_inventory_does_not_lend_one_repository_s_commits_to_another(repo: Path, tmp_path: Path) -> None:
    known = commit(repo)
    inventory(repo, known)
    other = tmp_path / "other"
    init(other)
    write(other, "README.md", "other")
    commit(other)
    with pytest.raises(subprocess.CalledProcessError):
        inventory(other, known)
