"""Bounded parallel parsing of immutable blobs; no repository code executes."""

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


def _record(source: bytes) -> str:
    from pytest_selective.impact_graph import parse_source

    return parse_source(source).model_dump_json()


def _worker(sources: list[bytes]) -> list[str]:
    from pytest_selective.impact_graph import _cache_prefix

    payload = json.dumps([base64.b64encode(source).decode("ascii") for source in sources]).encode()
    result = subprocess.run(
        [sys.executable, "-m", "pytest_selective.parse_batch"], input=payload, capture_output=True, check=True
    )
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or response.get("version") != _cache_prefix():
        raise ValueError("parser worker version differs from the parent")
    records = response.get("records")
    if not isinstance(records, list) or len(records) != len(sources) or not all(isinstance(r, str) for r in records):
        raise ValueError("incomplete parser worker response")
    return records


def parse_records(sources: list[bytes], workers: int | None = None) -> list[str]:
    """Return the serial parser's records in input order, with a serial fallback.

    Only large cache misses justify process startup. Dedicated worker modules
    neither inherit SQLite connections nor re-import a caller's main script.
    Startup/resource failures never erase dependencies: discard the incomplete
    batch and parse serially. Threads only coordinate independent subprocesses.
    """
    if workers is None:
        configured = os.environ.get("PYTEST_SELECTIVE_PARSE_WORKERS")
        if configured:
            workers = int(configured)
        elif len(sources) >= 256 and sum(map(len, sources)) >= 1_000_000:
            cpu_count = getattr(os, "process_cpu_count", os.cpu_count)() or 1
            workers = min(4, cpu_count)
        else:
            workers = 1
    if workers < 1:
        raise ValueError("PYTEST_SELECTIVE_PARSE_WORKERS must be at least 1")
    if getattr(sys, "frozen", False):
        workers = 1
    if workers > 1 and len(sources) > 1:
        workers = min(workers, len(sources))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                batches = list(pool.map(_worker, [sources[index::workers] for index in range(workers)]))
            return [batches[index % workers][index // workers] for index in range(len(sources))]
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            # A genuine parsing error also recurs on the serial path and keeps
            # its normal error handling. No partially parsed result is cached.
            pass
    return list(map(_record, sources))


if __name__ == "__main__":
    from pytest_selective.impact_graph import _cache_prefix

    sources = json.load(sys.stdin.buffer)
    records = [_record(base64.b64decode(source, validate=True)) for source in sources]
    sys.stdout.buffer.write(json.dumps({"version": _cache_prefix(), "records": records}).encode())
