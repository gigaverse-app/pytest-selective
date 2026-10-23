"""Measure cold, warm and incremental graph construction on fixed Git revisions.

The benchmark refreshes collection-policy fingerprints in memory so historical
trees can be measured with the current analyzer. It never changes the repository
or runs selected tests. Do not use its refreshed policy as adoption approval.
"""

import argparse
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path

from pytest_selective import impact_graph
from pytest_selective.impact_graph import GraphCache, blobs, git, inventory, policy_fingerprints
from pytest_selective.impact_models import ImpactConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--config", default=".github/test-impact.json")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tree = inventory(args.repo, args.base)
    oid = tree.files[args.config]
    config = ImpactConfig.model_validate_json(blobs(args.repo, {oid})[oid])
    config.pytest_policy = policy_fingerprints(args.repo, tree, tuple(config.pytest_config_files))
    samples = []
    for _ in range(args.repeat):
        with tempfile.TemporaryDirectory(prefix="selective-benchmark-") as folder:
            cache = GraphCache(Path(folder) / "cache.db")
            try:
                sample = {}
                for label, revision in (("cold", args.base), ("warm", args.base), ("incremental", args.head)):
                    start = time.perf_counter()
                    snapshot = cache.snapshot(args.repo, revision, config)
                    sample[label] = {
                        "seconds": time.perf_counter() - start,
                        "sha256": hashlib.sha256(
                            json.dumps(snapshot.model_dump(), sort_keys=True).encode()
                        ).hexdigest(),
                    }
                samples.append(sample)
            finally:
                cache.close()
    analyzer = Path(impact_graph.__file__).resolve().parents[2]
    result = {
        "analyzer_revision": git(analyzer, "rev-parse", "HEAD").decode().strip(),
        "base_tree": tree.tree,
        "head_tree": inventory(args.repo, args.head).tree,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
