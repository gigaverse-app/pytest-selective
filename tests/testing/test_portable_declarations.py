"""Non-Python adapters use declarations without importing the selection engine."""

import subprocess
import sys


def test_portable_api_has_no_pytest_or_selection_imports():
    code = r"""
import sys
from pytest_selective_declarations import dependency_edges, contents_node
files = {'web/read.ts', 'web/read.ts.gv-dependency.yaml', 'fixtures/data.json'}
manifests = {'web/read.ts.gv-dependency.yaml': b'dependencies:\n  - inputs: ["//fixtures/*.json"]\n    kind: content\n'}
edges = dependency_edges(manifests, files, revision='example')
assert edges == {'web/read.ts': {'web/read.ts.gv-dependency.yaml', contents_node('fixtures/data.json')}}
assert not any(name == 'pytest' or name.startswith(('pytest.', '_pytest', 'pytest_selective.')) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
