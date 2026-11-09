"""Dependency installers invalidate tests even without a Python import edge."""

from pathlib import Path

import pytest

from pytest_selective.ci import Lane, LaneConfig, plan
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write


@pytest.mark.parametrize(
    "path", ["requirements.txt", "requirements/dev.txt", "poetry.lock", "Pipfile.lock", "pdm.lock", "setup.py"]
)
@pytest.mark.parametrize("operation", ["added", "modified", "deleted"])
def test_dependency_file_changes_select_files_and_complete_lanes(tmp_path: Path, path: str, operation: str) -> None:
    init(tmp_path)
    write(tmp_path, "tests/a/test_a.py", "def test_a(): pass")
    write(tmp_path, "tests/b/test_b.py", "def test_b(): pass")
    if operation != "added":
        write(tmp_path, path, "# dependency version 1\n")
    base = commit(tmp_path)
    if operation == "deleted":
        (tmp_path / path).unlink()
    else:
        write(tmp_path, path, "# dependency version 2\n")
    head = commit(tmp_path)
    config = ImpactConfig(test_roots=["tests"])
    cache = GraphCache(tmp_path / ".test-impact/cache.sqlite3")
    try:
        report = affected(tmp_path, base, head, config, cache)
        assert report.selected == ["tests/a/test_a.py", "tests/b/test_b.py"]
        assert any(path in reason for reason in report.reasons)
    finally:
        cache.close()
    lanes = LaneConfig(graph=config, lanes={"a": Lane(roots=["tests/a"]), "b": Lane(roots=["tests/b"])})
    assert plan(tmp_path, lanes, base, head).lanes == {"a": True, "b": True}


def test_environment_inputs_reach_lanes_without_python_test_files(tmp_path: Path) -> None:
    init(tmp_path)
    write(tmp_path, "scripts/check.sh", "true\n")
    base = commit(tmp_path)
    write(tmp_path, "requirements.txt", "example==1\n")
    head = commit(tmp_path)
    config = LaneConfig(
        graph=ImpactConfig(test_roots=[]), lanes={"external": Lane(inputs=["scripts/**"])}, global_inputs=[]
    )
    assert plan(tmp_path, config, base, head).lanes == {"external": True}


def _docs_requirements_plan(tmp_path: Path, path: str, graph_inputs: list[str] | None, lane_inputs: list[str] | None):
    init(tmp_path)
    write(tmp_path, "src/pkg/a.py", "X = 1")
    write(tmp_path, "tests/test_a.py", "from pkg.a import X\ndef test_a(): assert X")
    base = commit(tmp_path)
    write(tmp_path, path, "# changed\n")
    head = commit(tmp_path)
    graph = ImpactConfig(module_roots=["src", "."], test_roots=["tests"])
    if graph_inputs is not None:
        graph.global_inputs = graph_inputs
    config = LaneConfig(graph=graph, lanes={"tests": Lane(roots=["tests"])}, global_inputs=lane_inputs)
    return plan(tmp_path, config, base, head)


@pytest.mark.parametrize(
    ("graph_inputs", "lane_inputs", "admitted"),
    [
        # The built-in environment policy matches *requirements*.txt anywhere.
        (None, None, True),
        # The graph's list is the environment authority: narrowing it alone is enough.
        (["pyproject.toml", "uv.lock"], None, False),
        # An explicit CI-input list does not narrow the graph's environment files.
        (None, ["pyproject.toml"], True),
        (["pyproject.toml", "uv.lock"], ["pyproject.toml"], False),
    ],
)
def test_graph_global_inputs_own_environment_files_for_lanes(
    tmp_path: Path, graph_inputs: list[str] | None, lane_inputs: list[str] | None, admitted: bool
) -> None:
    result = _docs_requirements_plan(tmp_path, "documentation/requirements.txt", graph_inputs, lane_inputs)
    assert result.lanes == {"tests": admitted}, result.reason
    if admitted:
        assert "documentation/requirements.txt" in " ".join([result.reason, *result.lane_reasons["tests"]])


def test_narrowed_graph_inputs_keep_builtin_ci_execution_inputs(tmp_path: Path) -> None:
    result = _docs_requirements_plan(tmp_path, ".github/workflows/ci.yml", ["pyproject.toml"], None)
    assert result.lanes == {"tests": True}
    assert result.lane_reasons["tests"] == ["global input: .github/workflows/ci.yml"]
