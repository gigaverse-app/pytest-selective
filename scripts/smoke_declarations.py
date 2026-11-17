"""Install the portable distributions with their ordinary dependencies, without pytest."""

import os
import subprocess
import tempfile
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = r"""
import importlib.util
import sys
from pytest_selective_declarations import dependency_edges, contents_node, DependencyDeclarationError
assert importlib.util.find_spec("pytest") is None
assert importlib.util.find_spec("pytest_selective") is None
files = {"web/read.ts", "web/read.ts.gv-dependency.yaml", "data.json"}
manifests = {"web/read.ts.gv-dependency.yaml": b'dependencies:\n  - inputs: ["//data.json"]\n    kind: content\n'}
assert dependency_edges(manifests, files) == {"web/read.ts": {"web/read.ts.gv-dependency.yaml", contents_node("data.json")}}
try:
    dependency_edges({}, files)
except DependencyDeclarationError:
    pass
else:
    raise AssertionError("missing declarations were accepted")
assert not any(name.startswith(("pytest_selective.", "_pytest")) for name in sys.modules)
"""


def smoke() -> None:
    distributions = sorted((ROOT / "dist").glob("pytest_selective_declarations-*.whl")) + sorted(
        (ROOT / "dist").glob("pytest_selective_declarations-*.tar.gz")
    )
    assert len(distributions) == 2, "Expected one declarations wheel and sdist"
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    for distribution, version in product(distributions, ("3.11", "3.14")):
        with tempfile.TemporaryDirectory(prefix="declarations-install-") as temporary:
            folder = Path(temporary)
            venv = folder / "venv"
            subprocess.run(["uv", "venv", "--python", version, str(venv)], check=True, env=environment)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), str(distribution)], check=True, env=environment
            )
            subprocess.run([str(python), "-I", "-c", PROBE], cwd=folder, check=True, env=environment)
            print(f"Verified {distribution.name} on Python {version} without pytest or pytest-selective", flush=True)


if __name__ == "__main__":
    smoke()
