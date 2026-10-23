"""The accelerated path must retain every fact, encoding and error of serial analysis."""

import subprocess

import pytest

from pytest_selective.impact_graph import parse_source
from pytest_selective.parse_batch import parse_records

SOURCES = [
    b"from . import relative\n",
    b'# coding: latin-1\nimport application\nlabel="caf\xe9"\n',
    b'pytest_plugins = "support,other"\n',
    b"import application\ndef broken(:",
    b'# gv:test-dependency: //fixture.json\nfrom pathlib import Path\nPath("fixture.json").read_bytes()\n',
    b'import subprocess\nsubprocess.run(["do-not-execute"])\n',
]


@pytest.mark.parametrize("workers", [1, 2])
def test_batch_preserves_complete_records_and_order(workers: int) -> None:
    # Repeated inputs exercise ordering across independent worker processes.
    sources = SOURCES * 12
    assert parse_records(sources, workers) == [parse_source(source).model_dump_json() for source in sources]


def test_unavailable_process_pool_preserves_serial_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(**kwargs):
        raise OSError("process resources unavailable")

    monkeypatch.setattr("pytest_selective.parse_batch.ThreadPoolExecutor", unavailable)
    assert parse_records(SOURCES, 2) == [parse_source(source).model_dump_json() for source in SOURCES]


@pytest.mark.parametrize("response", [b'{"version":"old", "records":[]}', b"truncated output"])
def test_untrustworthy_worker_output_retries_the_complete_batch(
    monkeypatch: pytest.MonkeyPatch, response: bytes
) -> None:
    def worker_output(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=response)

    monkeypatch.setattr("pytest_selective.parse_batch.subprocess.run", worker_output)
    assert parse_records(SOURCES, 2) == [parse_source(source).model_dump_json() for source in SOURCES]
