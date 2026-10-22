"""
Scope a type check to what a change can affect, from the test-impact import graph.

A checker's verdict on a file depends only on that file, the files it imports transitively,
and global inputs (configuration, stubs, installed packages). From a base that is known to
check clean, only files whose import closure contains a change can gain a diagnostic.
"""

import json
from pathlib import Path

import pytest

from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.typecheck_scope import PyrightSelection, UnsupportedPattern, scope
from tests.testing.git_repo import commit, init, write

GLOBAL = ["pyrightconfig.json", "pyproject.toml", "uv.lock", "**/*.pyi", "deployment/**"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "src/pkg/__init__.py")
    write(root, "src/pkg/leaf.py", "def value() -> int:\n    return 1\n")
    write(root, "src/pkg/middle.py", "from pkg.leaf import value\n\ndef twice() -> int:\n    return value() * 2\n")
    write(root, "src/pkg/top.py", "from pkg.middle import twice\n")
    write(root, "src/pkg/other.py", "X = 1\n")
    write(root, "src/pkg/generated/big.py", "from pkg.leaf import value\n")
    write(root, "tests/test_top.py", "from pkg.top import twice\n")
    write(
        root,
        "pyrightconfig.json",
        json.dumps({"include": ["src/pkg", "tests/test_top.py"], "exclude": ["**/__pycache__", "src/pkg/generated"]}),
    )
    return root


@pytest.fixture
def config() -> ImpactConfig:
    return ImpactConfig(module_roots=["src", "."], test_roots=["tests"])


def run(repo: Path, config: ImpactConfig, tmp_path: Path, base: str, head: str, max_fraction: float = 1.0):
    cache = GraphCache(tmp_path / "cache.sqlite3")
    try:
        return scope(repo, base, head, config, cache, "pyrightconfig.json", GLOBAL, max_fraction)
    finally:
        cache.close()


def test_a_change_scopes_the_check_to_itself_and_everything_importing_it(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    """INVARIANT: every included file whose import closure contains a change is checked."""
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "def value() -> str:\n    return '1'\n")
    head = commit(repo)
    result = run(repo, config, tmp_path, base, head)
    assert result.mode == "scoped"
    # other.py cannot have changed verdict; generated/ is excluded by the checker's own config.
    assert result.files == ["src/pkg/leaf.py", "src/pkg/middle.py", "src/pkg/top.py", "tests/test_top.py"]


def test_a_deleted_module_still_checks_its_former_importers(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    """A removed import target breaks its importers, which only the base graph still names."""
    base = commit(repo)
    (repo / "src/pkg/leaf.py").unlink()
    head = commit(repo)
    result = run(repo, config, tmp_path, base, head)
    assert result.mode == "scoped"
    assert "src/pkg/middle.py" in result.files and "src/pkg/top.py" in result.files
    assert "src/pkg/leaf.py" not in result.files, "a deleted file cannot be checked"


@pytest.mark.parametrize("path", ["pyrightconfig.json", "uv.lock", "src/pkg/stub.pyi", "deployment/tool.py"])
def test_a_global_input_forces_the_full_check(repo: Path, config: ImpactConfig, tmp_path: Path, path: str) -> None:
    """Configuration, stubs, installed packages and paths the graph cannot resolve change every verdict."""
    base = commit(repo)
    write(repo, path, "{}" if path.endswith(".json") else "changed = 1\n")
    head = commit(repo)
    result = run(repo, config, tmp_path, base, head)
    assert result.mode == "full"
    assert path in result.reason


def test_a_change_no_included_file_reaches_needs_no_check(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    base = commit(repo)
    write(repo, "src/pkg/generated/big.py", "from pkg.leaf import value\nY = 2\n")
    write(repo, "docs/notes.md", "text")
    head = commit(repo)
    result = run(repo, config, tmp_path, base, head)
    assert result.mode == "none"
    assert result.files == []


def test_a_scope_nearly_as_large_as_the_project_runs_the_full_check(
    repo: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    """Listing most files costs as much as the full check and gains nothing."""
    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "def value() -> str:\n    return '1'\n")
    head = commit(repo)
    result = run(repo, config, tmp_path, base, head, max_fraction=0.5)
    assert result.mode == "full"
    assert "of the checked files" in result.reason


@pytest.mark.parametrize(
    ("include", "exclude", "path", "checked"),
    [
        (["src/pkg"], [], "src/pkg/a.py", True),
        (["src/pkg/"], [], "src/pkg/sub/a.py", True),
        (["src/pkg"], [], "src/pkgextra/a.py", False),
        (["src/pkg/a.py"], [], "src/pkg/a.py", True),
        (["src"], ["**/__pycache__"], "src/x/__pycache__/a.py", False),
        (["src"], ["src/x/scripts"], "src/x/scripts/a.py", False),
        (["src"], ["src/x/scripts"], "src/x/scripts_other/a.py", True),
    ],
)
def test_the_checker_config_selects_files_as_the_checker_does(
    include: list[str], exclude: list[str], path: str, checked: bool
) -> None:
    assert PyrightSelection(include=include, exclude=exclude).checks(path) is checked


@pytest.mark.parametrize("pattern", ["src/*/api.py", "src/pkg?", "src/[ab]"])
def test_a_pattern_the_scope_cannot_interpret_is_refused(pattern: str) -> None:
    """Guessing at glob semantics could drop a file the checker would check; refuse instead."""
    with pytest.raises(UnsupportedPattern):
        PyrightSelection(include=[pattern], exclude=[])


def test_the_cli_writes_the_scope_and_its_ci_outputs(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    from pytest_selective.impact_cli import main

    base = commit(repo)
    write(repo, "src/pkg/leaf.py", "def value() -> str:\n    return '1'\n")
    head = commit(repo)
    config_path = tmp_path / "impact.json"
    config_path.write_text(config.model_dump_json())
    files, outputs = tmp_path / "scope.txt", tmp_path / "outputs.txt"
    args = ["typecheck-scope", "--repo", str(repo), "--config", str(config_path), "--cache", str(tmp_path / "c.db")]
    args += ["--base", base, "--head", head, "--checker-config", "pyrightconfig.json", "--max-fraction", "1"]
    args += [arg for pattern in GLOBAL for arg in ("--global-input", pattern)]
    assert main([*args, "--output", str(files), "--github-output", str(outputs)]) == 0
    assert files.read_text().split() == ["src/pkg/leaf.py", "src/pkg/middle.py", "src/pkg/top.py", "tests/test_top.py"]
    lines = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    assert lines["mode"] == "scoped"
    assert lines["files"] == "4"


def test_a_failed_scope_computation_is_the_full_check(repo: Path, config: ImpactConfig, tmp_path: Path) -> None:
    """Every doubt widens to the full check; the command never reports an empty scope on error."""
    from pytest_selective.impact_cli import main

    commit(repo)
    config_path = tmp_path / "impact.json"
    config_path.write_text(config.model_dump_json())
    outputs = tmp_path / "outputs.txt"
    args = ["typecheck-scope", "--repo", str(repo), "--config", str(config_path), "--cache", str(tmp_path / "c.db")]
    assert (
        main([*args, "--base", "missing-ref", "--output", str(tmp_path / "s.txt"), "--github-output", str(outputs)])
        == 0
    )
    assert "mode=full" in outputs.read_text()
