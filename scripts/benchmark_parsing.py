"""Measure uncached parsing and fingerprint every resulting dependency record.

Run before and after a parser change against the same immutable repository tree.
The digest checks output equivalence; samples include parsing and serialization,
not Git reads, dependency setup, cache hits or pytest execution.
"""

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from pytest_selective.impact_graph import blobs, git, inventory, parse_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tree = inventory(args.repo, args.revision)
    sources = blobs(args.repo, {oid for path, oid in tree.files.items() if path.endswith(".py")})
    samples = []
    digests = []
    for _ in range(args.repeat):
        start = time.perf_counter()
        digest = hashlib.sha256()
        for oid, source in sorted(sources.items()):
            digest.update(oid.encode())
            digest.update(parse_source(source).model_dump_json().encode())
        samples.append(time.perf_counter() - start)
        digests.append(digest.hexdigest())
    assert len(set(digests)) == 1, "parsing changed between identical samples"
    result = {
        "tree": tree.tree,
        "parser_head": git(Path(__file__).resolve().parents[1], "rev-parse", "HEAD").decode().strip(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "python_files": sum(path.endswith(".py") for path in tree.files),
        "unique_blobs": len(sources),
        "source_bytes": sum(map(len, sources.values())),
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "records_sha256": digests[0],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
