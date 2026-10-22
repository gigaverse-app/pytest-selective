import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from pytest_selective.ci import Lane, LaneConfig, main, plan
from pytest_selective.impact_graph import DependencyDeclarationError
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, write


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, LaneConfig, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "src/sample/__init__.py")
    write(tmp_path, "src/sample/value.py", "VALUE = 1")
    write(tmp_path, "tests/unit/test_value.py", "from sample.value import VALUE\ndef test_value(): assert VALUE")
    write(tmp_path, "tests/live/test_other.py", "def test_other(): assert True")
    config = LaneConfig(
        graph=ImpactConfig(module_roots=["src", "."], test_roots=["tests"]),
        lanes={
            "unit": Lane(roots=["tests/unit"]),
            "live": Lane(roots=["tests/live"], inputs=["external/**"]),
        },
    )
    return tmp_path, config, commit(tmp_path)


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        ("src/sample/value.py", "VALUE = 2", {"unit": True, "live": False}),
        ("tests/live/test_other.py", "def test_other(): assert 1", {"unit": False, "live": True}),
        ("external/contract.json", "{}", {"unit": False, "live": True}),
        ("README.md", "documentation", {"unit": False, "live": False}),
        (".github/workflows/ci.yml", "name: CI", {"unit": True, "live": True}),
        ("uv.lock", "", {"unit": True, "live": True}),
    ],
)
def test_changes_select_complete_affected_lanes(repository, path, content, expected):
    repo, config, base = repository
    write(repo, path, content)
    assert plan(repo, config, base, commit(repo)).lanes == expected


def test_missing_base_and_explicit_checkpoints_run_every_lane(repository):
    repo, config, base = repository
    fallback = plan(repo, config, "missing-ref", base)
    assert fallback.lanes == {"unit": True, "live": True}
    assert "fallback" in fallback.reason
    assert plan(repo, config, base, base, full=True).lanes == fallback.lanes


def test_deletions_keep_old_dependents(repository):
    repo, config, base = repository
    (repo / "src/sample/value.py").unlink()
    assert plan(repo, config, base, commit(repo)).lanes == {"unit": True, "live": False}


def test_invalid_dependency_is_not_a_successful_plan(repository):
    repo, config, base = repository
    write(repo, "src/sample/value.py", "# gv:test-dependency: missing.json\nVALUE = 1")
    with pytest.raises(DependencyDeclarationError):
        plan(repo, config, base, commit(repo))


def test_deleted_test_still_runs_lane_completeness_checks(repository):
    repo, config, base = repository
    (repo / "tests/live/test_other.py").unlink()
    assert plan(repo, config, base, commit(repo)).lanes == {"unit": False, "live": True}


def test_cli_writes_boolean_outputs_and_does_not_execute_tests(repository, capsys):
    repo, config, base = repository
    write(repo, "src/sample/value.py", "raise RuntimeError('planning must not import this')")
    head = commit(repo)
    config_path = repo / "lanes.json"
    config_path.write_text(config.model_dump_json())
    output = repo / "outputs"
    assert (
        main(
            [
                "--repo",
                str(repo),
                "--config",
                str(config_path),
                "--base",
                base,
                "--head",
                head,
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert "unit=true\nlive=false\n" in output.read_text()
    assert json.loads(capsys.readouterr().out)["selected"] == ["tests/unit/test_value.py"]


def test_output_names_cannot_inject_github_outputs(repository):
    _, config, _ = repository
    with pytest.raises(ValidationError):
        LaneConfig(graph=config.graph, lanes={"bad\ninjected": Lane(roots=["tests"])})
