"""Measure the optional upstream Rust import API, including materialization cost.

Run with uv run --with pytest-impacted-rs==0.35.0 python scripts/benchmark_rust.py.
Imports alone are not equivalent to pytest-selective's complete dependency facts.
"""

import argparse
import json
import platform
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

from pytest_impacted_rs import parse_all_imports

from pytest_selective.impact_graph import blobs, inventory, parse_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tree = inventory(args.repo, args.revision)
    sources = blobs(args.repo, {oid for path, oid in tree.files.items() if path.endswith(".py")})
    result = {
        "tree": tree.tree,
        "native_version": version("pytest-impacted-rs"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "unique_blobs": len(sources),
        "source_bytes": sum(map(len, sources.values())),
    }
    with tempfile.TemporaryDirectory(prefix="selective-rust-benchmark-") as directory:
        start = time.perf_counter()
        modules = []
        for oid, source in sources.items():
            path = Path(directory) / f"{oid}.py"
            path.write_bytes(source)
            modules.append((str(path), oid, False))
        result["materialize_seconds"] = time.perf_counter() - start
        samples = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            parse_all_imports(modules)
            samples.append(time.perf_counter() - start)
        result["native_imports_seconds"] = samples
        result["correctness"] = {}
        for name, source in {
            "invalid": b"import application\ndef broken(:",
            "encoding": b'# coding: latin-1\nimport application\nlabel="caf\xe9"\n',
        }.items():
            path = Path(directory) / f"{name}.py"
            path.write_bytes(source)
            result["correctness"][name] = {
                "native": parse_all_imports([(str(path), "sample", False)]),
                "selective": parse_source(source).model_dump(),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
