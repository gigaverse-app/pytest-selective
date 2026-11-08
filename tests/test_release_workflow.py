"""Release validation must start before any package or Actions tag is published."""

# gv:test-dependency: .github/workflows/release.yml
# gv:test-dependency: .github/workflows/ci.yml

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_caller_can_grant_every_permission_requested_by_reusable_ci():
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    caller = release["jobs"]["checks"]
    granted = caller.get("permissions", release.get("permissions", {}))
    levels = {"none": 0, "read": 1, "write": 2}
    for name, job in ci["jobs"].items():
        requested = job.get("permissions", ci.get("permissions", {}))
        for scope, level in requested.items():
            assert levels[granted.get(scope, "none")] >= levels[level], (name, scope, level)


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
