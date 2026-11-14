"""Read historical blobs through a real promisor remote, without one fetch per file."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from pytest_selective.git_operations import git
from pytest_selective.impact_graph import blobs, inventory
from tests.testing.git_repo import commit, init, write


def test_missing_blobs_are_fetched_together_and_unrequested_objects_stay_lazy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    init(source)
    for number in range(8):
        write(source, f"file_{number}.py", f"old = {number}\n")
    base = commit(source)
    original = inventory(source, base).files
    for number in range(8):
        write(source, f"file_{number}.py", f"new = {number}\n")
    commit(source)
    git(source, "config", "uploadpack.allowFilter", "true")
    git(source, "config", "uploadpack.allowAnySHA1InWant", "true")
    clone = tmp_path / "partial"
    git(
        tmp_path,
        "clone",
        "--quiet",
        "--filter=blob:none",
        "--no-checkout",
        "--origin",
        "source",
        source.as_uri(),
        str(clone),
    )
    git(clone, "checkout", "--quiet", "HEAD")
    ids = {original[f"file_{number}.py"] for number in range(7)}
    expected = blobs(source, ids)
    trace = tmp_path / "trace.json"
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))

    assert blobs(clone, ids) == expected
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    fetches = [event for event in events if event.get("event") == "start" and "fetch" in event.get("argv", [])]
    assert len(fetches) <= 1, f"Historical blob reads spawned {len(fetches)} separate fetches"
    trace.unlink()
    assert blobs(clone, ids) == expected
    assert not any(
        event.get("event") == "start" and "fetch" in event.get("argv", [])
        for event in (json.loads(line) for line in trace.read_text().splitlines())
    )
    probe = subprocess.run(
        ["git", "-C", str(clone), "cat-file", "-e", original["file_7.py"]],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
    )
    assert probe.returncode != 0, "Reading selected blobs must not download unrelated history"

    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "1")
    with pytest.raises(ValueError, match="Git blobs unavailable"):
        blobs(clone, {original["file_7.py"]})
    monkeypatch.delenv("GIT_NO_LAZY_FETCH")
    git(clone, "remote", "set-url", "source", (tmp_path / "unavailable").as_uri())
    git(clone, "remote", "add", "backup", source.as_uri())
    git(clone, "config", "remote.backup.promisor", "true")
    assert blobs(clone, {original["file_7.py"]}) == {original["file_7.py"]: b"old = 7\n"}


def test_local_blob_reads_preserve_binary_content_and_reject_non_blobs(tmp_path: Path) -> None:
    init(tmp_path)
    content = b"\0binary\ncontent\xff\r\n"
    (tmp_path / "binary").write_bytes(content)
    revision = commit(tmp_path)
    oid = inventory(tmp_path, revision).files["binary"]
    assert blobs(tmp_path, {oid}) == {oid: content}
    assert blobs(tmp_path, set()) == {}
    with pytest.raises(ValueError, match="not a blob"):
        blobs(tmp_path, {revision})
    with pytest.raises(ValueError, match="Git blobs unavailable"):
        blobs(tmp_path, {"0" * 40})
