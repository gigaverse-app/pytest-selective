"""Every runtime test command must be admitted by dependency selection."""
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/public-actions.yml

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (
    "pytest ",
    "-m unittest",
    "node --test",
    "run_ci_tests.py",
    "smoke_distribution.py",
    "check_wheel.py",
    "check_core_is_framework_free.py",
    "scripts/tutorial.py",
    "ci-esta-pytest",
)


def test_runtime_commands_have_selection_and_failure_fallback():
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        # Release/full checkpoints deliberately execute everything.
        if path.name not in {"ci.yml", "public-actions.yml"}:
            continue
        jobs = yaml.safe_load(path.read_text())["jobs"]
        for name, job in jobs.items():
            for step in job.get("steps", []):
                command = step.get("run", "")
                if not any(marker in command for marker in RUNTIME):
                    continue
                admission = job.get("if", "") + " " + step.get("if", "")
                assert "needs." in admission and "result != 'success'" in admission, (path.name, name, command)
                assert "lanes" in admission, (path.name, name, command)


def test_public_smoke_is_selected_and_requires_successful_planning():
    path = ROOT / ".github/workflows/public-actions.yml"
    if not path.exists():
        return
    jobs = yaml.safe_load(path.read_text())["jobs"]
    smoke = jobs["public-actions"]
    assert smoke["needs"] == "select-tests"
    assert "needs.select-tests.result != 'success'" in smoke["if"]
    assert "lanes" in smoke["if"]
    assert any(
        "exit 1" in step.get("run", "") and "needs.select-tests.result" in step.get("if", "") for step in smoke["steps"]
    )


def test_ordinary_pushes_do_not_force_full_tests():
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        jobs = yaml.safe_load(path.read_text()).get("jobs", {})
        for job in jobs.values():
            # A selected smoke job deliberately exercises the full-plan action API.
            if job.get("needs") == "select-tests":
                continue
            for step in job.get("steps", []):
                if "plan-lanes" in step.get("uses", "") or step.get("id") == "files":
                    full = step.get("with", {}).get("full", "")
                    assert "github.event_name != 'pull_request'" not in str(full), path
                    assert "workflow_dispatch" in str(full), path
