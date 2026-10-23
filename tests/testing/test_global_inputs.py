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
