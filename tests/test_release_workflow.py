"""Release validation must start before any package or Actions tag is published."""

# gv:test-dependency: .github/workflows/release.yml
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/dry-lint.yml
# gv:test-dependency: .github/workflows/dry-lint-audit.yml

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


LEVELS = {"none": 0, "read": 1, "write": 2}


def workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def requested(called: dict) -> dict[str, str]:
    """The highest level the called workflow asks for, at workflow level or in any job."""
    wanted: dict[str, str] = {}
    for block in [called.get("permissions") or {}, *(job.get("permissions") or {} for job in called["jobs"].values())]:
        for scope, level in block.items():
            if LEVELS[level] > LEVELS[wanted.get(scope, "none")]:
                wanted[scope] = level
    return wanted


def local_calls() -> list[tuple[str, str, dict, dict]]:
    calls = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        caller = workflow(path.name)
        for name, job in caller["jobs"].items():
            if job.get("uses", "").startswith("./.github/workflows/"):
                calls.append((path.name, name, caller, job))
    return calls


@pytest.mark.parametrize("call", local_calls(), ids=lambda call: f"{call[0]}:{call[1]}")
def test_callers_grant_every_permission_their_reusable_workflow_requests(call):
    # GitHub refuses to start a called workflow that asks for more than its caller grants, and the
    # caller's run ends in startup_failure before any job runs: 0.4.3 was tagged but never published.
    source, name, caller, job = call
    granted = job.get("permissions", caller.get("permissions", {}))
    missing = {
        scope: level
        for scope, level in requested(workflow(Path(job["uses"]).name)).items()
        if LEVELS[level] > LEVELS[granted.get(scope, "none")]
    }
    assert missing == {}, f"{source} job {name!r} must grant {missing} to {job['uses']}"


def test_publish_grants_reusable_ci_its_permissions_explicitly():
    # Publish's own workflow-level block is contents: read; the call must not inherit it.
    calls = [job for source, _, _, job in local_calls() if source == "release.yml"]
    assert [job["uses"] for job in calls] == ["./.github/workflows/ci.yml"]
    assert calls[0].get("permissions"), "release.yml's ci.yml call needs its own permissions block"


def test_publishing_keeps_oidc_isolated_and_advances_actions_only_after_pypi():
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    jobs = release["jobs"]
    assert jobs["checks"]["needs"] == "validate-tag"
    assert jobs["publish"]["needs"] == "checks"
    assert jobs["publish"]["environment"]["name"] == "pypi"
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["action-version"]["needs"] == "publish"
    assert not any("checkout@" in step.get("uses", "") for step in jobs["publish"]["steps"])
    for name, job in jobs.items():
        if name != "publish":
            assert job.get("permissions", release.get("permissions", {})).get("id-token", "none") == "none"
