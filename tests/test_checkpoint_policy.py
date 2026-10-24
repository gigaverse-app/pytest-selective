"""Exercise event defaults through both production planners on real Git trees."""

import json

import pytest

from pytest_selective.ci import main as lanes_main
from pytest_selective.impact_cli import main as files_main
from tests.testing.git_repo import commit, init, write


@pytest.mark.parametrize("planner", ["files", "lanes"])
@pytest.mark.parametrize(
    ("event", "attempt", "labels", "policy", "full"),
    [
        ("pull_request", "1", [], "auto", False),
        ("push", "1", [], "auto", False),
        ("pull_request", "2", [], "auto", True),
        ("pull_request", "1", ["test:full"], "auto", True),
        ("workflow_dispatch", "1", [], "auto", True),
        ("workflow_call", "1", [], "auto", True),
        ("schedule", "1", [], "auto", True),
        ("release", "1", [], "auto", True),
        ("unknown", "1", [], "auto", True),
        ("pull_request", "invalid", [], "auto", True),
        ("pull_request", "1", None, "auto", True),
        ("schedule", "2", [], "false", False),
        ("push", "1", [], "true", True),
    ],
)
def test_checkpoint_policy_drives_real_selection(tmp_path, monkeypatch, planner, event, attempt, labels, policy, full):
    init(tmp_path)
    write(tmp_path, "tests/test_example.py", "def test_example(): assert True")
    base = commit(tmp_path)
    write(tmp_path, "README.md", "Documentation only")
    commit(tmp_path)
    graph = {"module_roots": ["."], "test_roots": ["tests"]}
    config = graph if planner == "files" else {"graph": graph, "lanes": {"tests": {"roots": ["tests"]}}}
    write(tmp_path, "config.json", json.dumps(config))
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps({"pull_request": {"labels": [{"name": label} for label in labels]}})
        if labels is not None
        else "invalid"
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    output = tmp_path / "output"
    args = [
        "--repo",
        str(tmp_path),
        "--config",
        str(tmp_path / "config.json"),
        "--base",
        base,
        "--full",
        policy,
        "--github-output",
        str(output),
    ]
    if planner == "files":
        assert files_main(["affected", *args, "--cache", str(tmp_path / "cache.sqlite3")]) == 0
        assert ("mode=full" if full else "mode=none") in output.read_text()
        roots = next(
            line.removeprefix("test_roots_json=")
            for line in output.read_text().splitlines()
            if line.startswith("test_roots_json=")
        )
        assert json.loads(roots) == (["tests"] if full else [])
    else:
        assert lanes_main(args) == 0
        assert f"tests={str(full).lower()}" in output.read_text()


def test_json_output_preserves_selected_paths_with_spaces(tmp_path):
    init(tmp_path)
    test = "tests/test_with spaces.py"
    write(tmp_path, test, "def test_example(): assert True")
    write(tmp_path, "tests/test_unrelated.py", "def test_unrelated(): assert True")
    base = commit(tmp_path)
    write(tmp_path, test, "def test_example(): assert 1 == 1")
    commit(tmp_path)
    write(tmp_path, "config.json", json.dumps({"module_roots": ["."], "test_roots": ["tests"]}))
    output = tmp_path / "output"
    assert (
        files_main(
            [
                "affected",
                "--repo",
                str(tmp_path),
                "--config",
                str(tmp_path / "config.json"),
                "--base",
                base,
                "--github-output",
                str(output),
                "--cache",
                str(tmp_path / "cache.sqlite3"),
            ]
        )
        == 0
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["mode"] == "scoped"
    assert json.loads(values["test_roots_json"]) == [test]
