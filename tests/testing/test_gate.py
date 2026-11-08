"""The aggregate gate accepts a skip only when a successful plan said the job's lanes were unaffected."""

# gv:test-dependency: actions/validation-gate/action.yml

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from pytest_selective.gate import GateError, admissions, failures, main

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "src/pytest_selective/gate.py"


def passes(needs, lane_jobs, lanes=None, planner="select-tests"):
    return not failures(needs, admissions(needs, planner, lane_jobs, lanes))


def plan(result="success", lanes='{"tests": false, "package": true}'):
    return {"result": result, "outputs": {"lanes": lanes} if result == "success" else {}}


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "", "neutral"])
@pytest.mark.parametrize("lane", [True, False])
def test_a_lane_job_passes_on_success_or_a_skip_its_false_lane_allows(result, lane):
    needs = {"select-tests": plan(lanes=json.dumps({"tests": lane})), "tests": {"result": result}}
    assert passes(needs, {"tests": ["tests"]}) == (result == "success" or (result == "skipped" and not lane))


@pytest.mark.parametrize("planner", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize("tests", ["success", "skipped"])
def test_an_unsuccessful_planner_fails_the_gate_even_when_fallback_jobs_pass(planner, tests):
    needs = {"select-tests": plan(planner), "tests": {"result": tests}}
    assert not passes(needs, {"tests": ["tests"]})


@pytest.mark.parametrize("decision", [None, "false", 0, True])
def test_only_a_literal_false_lane_makes_a_job_skippable(decision):
    lanes = json.dumps({} if decision is None else {"tests": decision})
    needs = {"select-tests": plan(lanes=lanes), "tests": {"result": "skipped"}}
    assert not passes(needs, {"tests": ["tests"]})


def test_a_job_on_several_lanes_is_skippable_only_when_all_are_false():
    needs = {"select-tests": plan(), "build": {"result": "skipped"}}
    assert not passes(needs, {"build": ["tests", "package"]})
    assert passes(needs, {"build": ["tests"]})


def test_unmapped_jobs_must_succeed():
    needs = {"select-tests": plan(), "tests": {"result": "skipped"}, "lint": {"result": "skipped"}}
    assert failures(needs, admissions(needs, "select-tests", {"tests": ["tests"]})) == ["lint: skipped (required)"]


@pytest.mark.parametrize("lanes", ["not json", "[]", ""])
def test_an_unreadable_plan_requires_every_mapped_job(lanes):
    needs = {"select-tests": plan(lanes=lanes), "tests": {"result": "skipped"}}
    assert not passes(needs, {"tests": ["tests"]})


def test_an_explicit_lane_map_overrides_the_planner_output():
    needs = {"select-tests": plan(lanes='{"tests": true}'), "tests": {"result": "skipped"}}
    assert passes(needs, {"tests": ["tests"]}, lanes={"tests": False})


@pytest.mark.parametrize(
    "needs, lane_jobs",
    [
        ({"tests": {"result": "success"}}, {}),
        ({"select-tests": plan()}, {"tests": ["tests"]}),
        ({"select-tests": plan(), "tests": {"result": "skipped"}}, {"select-tests": ["tests"]}),
        ({"select-tests": plan(), "tests": {"result": "skipped"}}, {"tests": []}),
        ({"select-tests": plan(), "tests": {"result": "skipped"}}, {"tests": "tests"}),
        ({"select-tests": plan(), "tests": {"result": "skipped"}}, ["tests"]),
    ],
)
def test_inputs_that_cannot_support_a_decision_are_errors(needs, lane_jobs):
    with pytest.raises(GateError):
        admissions(needs, "select-tests", lane_jobs)


def test_the_cli_exit_status_separates_failures_from_invalid_inputs(capsys):
    needs = {"select-tests": plan(), "tests": {"result": "skipped"}, "build": {"result": "success"}}
    lane_jobs = json.dumps({"tests": ["tests"], "build": ["package"]})
    assert main(["--needs", json.dumps(needs), "--lane-jobs", lane_jobs]) == 0
    assert "tests: skipped (skippable)" in capsys.readouterr().out
    needs["build"]["result"] = "failure"
    assert main(["--needs", json.dumps(needs), "--lane-jobs", lane_jobs]) == 1
    assert main(["--needs", "{}", "--lane-jobs", lane_jobs]) == 2


def test_the_action_runs_the_file_without_the_package_installed(tmp_path):
    needs = {"plan": plan(), "tests": {"result": "skipped"}}
    environment = {
        **os.environ,
        "VALIDATION_NEEDS": json.dumps(needs),
        "VALIDATION_PLANNER": "plan",
        "VALIDATION_LANE_JOBS": '{"tests": ["tests"]}',
        "VALIDATION_LANES": "",
    }
    # Isolated mode and an unrelated working directory: only the standard library is importable.
    result = subprocess.run(
        [sys.executable, "-I", str(GATE)], cwd=tmp_path, env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    environment["VALIDATION_LANES"] = '{"tests": true}'
    result = subprocess.run([sys.executable, "-I", str(GATE)], cwd=tmp_path, env=environment, capture_output=True)
    assert result.returncode == 1


def test_the_action_forwards_every_input_to_this_file():
    action = yaml.safe_load((ROOT / "actions/validation-gate/action.yml").read_text(encoding="utf-8"))
    (step,) = action["runs"]["steps"]
    assert step["env"]["GATE"] == "${{ github.action_path }}/../../src/pytest_selective/gate.py"
    forwarded = {name: value for name, value in step["env"].items() if name.startswith("VALIDATION_")}
    assert forwarded == {
        f"VALIDATION_{key.upper().replace('-', '_')}": "${{ inputs." + key + " }}" for key in action["inputs"]
    }
