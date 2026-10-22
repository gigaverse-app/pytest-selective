import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pytest_selective.ci import Lane, LaneConfig, main, plan
from pytest_selective.impact_graph import DependencyDeclarationError
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, init, write


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, LaneConfig, str]:
    init(tmp_path)
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


@pytest.mark.parametrize("deleted", [False, True])
def test_unmapped_test_cannot_silently_skip_every_lane(repository, deleted):
    repo, config, base = repository
    path = "tests/new_group/test_unmapped.py"
    write(repo, path, "def test_new(): assert True")
    if deleted:
        base = commit(repo)
        (repo / path).unlink()
    result = plan(repo, config, base, commit(repo))
    assert result.lanes == {"unit": True, "live": True}
    assert path in result.reason
    assert "unmapped" in result.reason


def test_lane_evidence_explains_selected_and_skipped_jobs(repository):
    repo, config, base = repository
    write(repo, "src/sample/value.py", "VALUE = 2")
    result = plan(repo, config, base, commit(repo))
    assert result.lane_reasons == {
        "unit": ["affected test: tests/unit/test_value.py"],
        "live": ["no affected tests or changed inputs"],
    }


@pytest.mark.parametrize("full", [False, True])
def test_full_suite_evidence_names_its_cause(repository, full):
    repo, config, base = repository
    write(repo, "uv.lock", "")
    result = plan(repo, config, base, commit(repo), full=full)
    expected = "explicit full-suite checkpoint" if full else "global input: uv.lock"
    assert all(expected in reasons for reasons in result.lane_reasons.values())


WORKFLOW = """\
name: CI
on: [pull_request]
env:
  LEVEL: info
jobs:
  select-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: example/plan-lanes@1111111
  tests:
    needs: select-tests
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests/unit
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check
"""


@pytest.fixture
def workflow_repository(tmp_path: Path) -> tuple[Path, LaneConfig, str]:
    init(tmp_path)
    write(tmp_path, "src/sample/__init__.py")
    write(tmp_path, "tests/unit/test_value.py", "def test_value(): assert True")
    write(tmp_path, "tests/live/test_other.py", "def test_other(): assert True")
    write(tmp_path, ".github/workflows/ci.yml", WORKFLOW)
    config = LaneConfig(
        graph=ImpactConfig(module_roots=["src", "."], test_roots=["tests"]),
        lanes={
            "unit": Lane(roots=["tests/unit"], inputs=[".github/workflows/ci.yml#tests"]),
            "live": Lane(roots=["tests/live"], inputs=[".github/workflows/ci.yml#lint"]),
        },
        global_inputs=["uv.lock"],
    )
    return tmp_path, config, commit(tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("example/plan-lanes@1111111", "example/plan-lanes@2222222", {"unit": False, "live": False}),
        ("pytest tests/unit", "pytest -x tests/unit", {"unit": True, "live": False}),
        ("ruff check", "ruff check --fix", {"unit": False, "live": True}),
        ("LEVEL: info", "LEVEL: debug", {"unit": True, "live": True}),
        ("on: [pull_request]", "on: [pull_request, push]", {"unit": True, "live": True}),
        ("name: CI\n", "# Comments and layout are not behavior.\nname:   CI\n", {"unit": False, "live": False}),
    ],
)
def test_job_inputs_select_only_lanes_whose_job_or_shared_settings_changed(workflow_repository, old, new, expected):
    repo, config, base = workflow_repository
    write(repo, ".github/workflows/ci.yml", WORKFLOW.replace(old, new))
    assert plan(repo, config, base, commit(repo)).lanes == expected


def test_job_input_evidence_names_the_job(workflow_repository):
    repo, config, base = workflow_repository
    write(repo, ".github/workflows/ci.yml", WORKFLOW.replace("pytest tests/unit", "pytest -x tests/unit"))
    head = commit(repo)
    result = plan(repo, config, base, head)
    assert result.lane_reasons["unit"] == ["explicit input: .github/workflows/ci.yml#tests"]
    assert result.lane_reasons["live"] == ["unchanged job: .github/workflows/ci.yml#lint"]
    write(repo, "README.md", "documentation")
    assert plan(repo, config, head, commit(repo)).lane_reasons["live"] == ["no affected tests or changed inputs"]


def test_removing_the_workflow_or_the_job_selects_its_lane(workflow_repository):
    repo, config, base = workflow_repository
    write(repo, ".github/workflows/ci.yml", WORKFLOW.split("  lint:")[0])
    assert plan(repo, config, base, commit(repo)).lanes == {"unit": False, "live": True}
    (repo / ".github/workflows/ci.yml").unlink()
    assert plan(repo, config, base, commit(repo)).lanes == {"unit": True, "live": True}


@pytest.mark.parametrize("workflow_changed", [False, True])
def test_a_misspelled_job_is_a_declaration_error(workflow_repository, workflow_changed):
    repo, config, base = workflow_repository
    config.lanes["unit"] = Lane(roots=["tests/unit"], inputs=[".github/workflows/ci.yml#test"])
    if workflow_changed:
        write(repo, ".github/workflows/ci.yml", WORKFLOW.replace("ruff check", "ruff check --fix"))
    else:
        write(repo, "README.md", "documentation")
    with pytest.raises(DependencyDeclarationError, match="no job 'test'"):
        plan(repo, config, base, commit(repo))


@pytest.mark.parametrize("content", ["jobs: [unclosed", "name: not a workflow"])
def test_an_unreadable_workflow_runs_every_lane(workflow_repository, content):
    repo, config, base = workflow_repository
    write(repo, ".github/workflows/ci.yml", content)
    result = plan(repo, config, base, commit(repo))
    assert result.lanes == {"unit": True, "live": True}
    assert "fallback" in result.reason


@pytest.mark.parametrize(
    ("inputs", "global_inputs", "message"),
    [
        ([".github/workflows/*.yml#tests"], ["uv.lock"], "without wildcards"),
        ([".github/workflows/ci.yml#"], ["uv.lock"], "without wildcards"),
        ([".github/workflows/ci.yml#tests"], None, "matches a global input"),
    ],
)
def test_job_inputs_that_cannot_narrow_are_rejected(inputs, global_inputs, message):
    settings = {} if global_inputs is None else {"global_inputs": global_inputs}
    with pytest.raises(ValidationError, match=message):
        LaneConfig(
            graph=ImpactConfig(module_roots=["."], test_roots=["tests"]),
            lanes={"unit": {"roots": ["tests"], "inputs": inputs}},
            **settings,
        )
