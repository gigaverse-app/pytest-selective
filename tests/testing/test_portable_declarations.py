"""Non-Python adapters use declarations without importing the selection engine."""

import subprocess
import sys


def test_portable_api_has_no_pytest_or_selection_imports():
    code = r"""
import sys
from selective_deps import dependency_edges, contents_node
files = {'web/read.ts', 'web/read.ts.gv-dependency.yaml', 'fixtures/data.json'}
manifests = {'web/read.ts.gv-dependency.yaml': b'dependencies:\n  - inputs: ["//fixtures/*.json"]\n    kind: content\n'}
edges = dependency_edges(manifests, files, revision='example')
assert edges == {'web/read.ts': {'web/read.ts.gv-dependency.yaml', contents_node('fixtures/data.json')}}
assert not any(name == 'pytest' or name.startswith(('pytest.', '_pytest', 'pytest_selective.')) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_reviewed_readers_without_inputs_depend_only_on_their_manifest():
    from selective_deps import dependency_edges

    files = {"ci/.gv-dependencies.yaml", "ci/report.mjs", "ci/upload.mjs"}
    manifest = b'dependencies:\n  - readers: ["*.mjs"]\n    inputs: []\n    reason: Reads only generated reports.\n'
    edges = dependency_edges({"ci/.gv-dependencies.yaml": manifest}, files)
    assert edges == {"ci/report.mjs": {"ci/.gv-dependencies.yaml"}, "ci/upload.mjs": {"ci/.gv-dependencies.yaml"}}


def test_a_rule_without_inputs_must_say_why():
    import pytest
    from selective_deps import DependencyDeclarationError, dependency_edges

    files = {"ci/.gv-dependencies.yaml", "ci/report.mjs"}
    manifest = b'dependencies:\n  - readers: ["report.mjs"]\n    inputs: []\n'
    with pytest.raises(DependencyDeclarationError, match="requires a reason"):
        dependency_edges({"ci/.gv-dependencies.yaml": manifest}, files)


def test_stem_pairs_each_reader_with_its_own_sibling():
    from selective_deps import dependency_edges

    files = {"ci/.gv-dependencies.yaml", "ci/a.mjs", "ci/a.test.mjs", "ci/b.mjs", "ci/b.test.mjs"}
    manifest = b'dependencies:\n  - readers: ["*.test.mjs"]\n    inputs: ["{stem}.mjs"]\n'
    edges = dependency_edges({"ci/.gv-dependencies.yaml": manifest}, files)
    assert edges["ci/a.test.mjs"] == {"ci/.gv-dependencies.yaml", "ci/a.mjs"}
    assert edges["ci/b.test.mjs"] == {"ci/.gv-dependencies.yaml", "ci/b.mjs"}


def test_stem_reports_the_reader_whose_sibling_is_missing():
    import pytest
    from selective_deps import DependencyDeclarationError, dependency_edges

    files = {"ci/.gv-dependencies.yaml", "ci/a.mjs", "ci/a.test.mjs", "ci/b.test.mjs"}
    manifest = b'dependencies:\n  - readers: ["*.test.mjs"]\n    inputs: ["{stem}.mjs"]\n'
    with pytest.raises(DependencyDeclarationError, match=r"reader ci/b\.test\.mjs.*'b\.mjs' matches no tracked files"):
        dependency_edges({"ci/.gv-dependencies.yaml": manifest}, files)


def test_other_brace_placeholders_remain_invalid():
    import pytest
    from selective_deps import DependencyDeclarationError, dependency_edges

    files = {"ci/.gv-dependencies.yaml", "ci/a.mjs", "ci/a.test.mjs"}
    manifest = b'dependencies:\n  - readers: ["*.test.mjs"]\n    inputs: ["{name}.mjs"]\n'
    with pytest.raises(DependencyDeclarationError, match="invalid repository-relative dependency pattern"):
        dependency_edges({"ci/.gv-dependencies.yaml": manifest}, files)
