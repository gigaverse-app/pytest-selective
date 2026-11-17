"""Install the portable distributions with their ordinary dependencies, without pytest."""

import subprocess

from smoke_environments import installed_distributions

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
    for distribution, version, folder, _, python, environment in installed_distributions(
        "pytest_selective_declarations"
    ):
        subprocess.run([str(python), "-I", "-c", PROBE], cwd=folder, check=True, env=environment)
        print(f"Verified {distribution.name} on Python {version} without pytest or pytest-selective", flush=True)


if __name__ == "__main__":
    smoke()
