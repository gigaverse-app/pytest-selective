from pathlib import Path

import pytest

from pytest_selective.impact_audit import audit
from pytest_selective.impact_audit_declarations import (
    CONTENT_REASON,
    IMPORT_REASON,
    plan_declarations,
    write_sidecar,
)
from pytest_selective.impact_declarations import DependencyDeclarationError
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import AuditRecord, ImpactConfig, ManifestDependencyRule
from tests.testing.git_repo import commit, init, write

TEST = "tests/test_reader.py"
CONFIG = ImpactConfig(module_roots=["src", "."], test_roots=["tests"])
FILES = [
    "data/full/one.json",
    "data/full/two.json",
    "data/full/nested/three.json",
    "data/partial/one.json",
    "data/partial/two.json",
    "data/single/only.json",
    "data/other.json",
    "scripts/tool.py",
    "scripts/helper.py",
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    init(root)
    write(root, TEST, "def test_read(): pass\n")
    for path in FILES:
        write(root, path, "1\n")
    commit(root)
    return root


def plan(repo: Path, tmp_path: Path, *reads: str):
    snapshot = GraphCache(tmp_path / "cache.sqlite3").snapshot(repo, "HEAD", CONFIG)
    records = [AuditRecord(inputs={TEST: list(reads)})]
    return plan_declarations(audit(snapshot, records, CONFIG), snapshot, records)


def test_a_directory_becomes_a_glob_only_when_every_tracked_file_in_it_was_read(repo: Path, tmp_path: Path) -> None:
    result = plan(
        repo,
        tmp_path,
        "data/full/one.json",
        "data/full/two.json",
        "data/full/nested/three.json",
        # One of two files: listing the directory would claim an input the test never read.
        "data/partial/one.json",
        # The only file of its directory: a glob would only add inputs that do not exist yet.
        "data/single/only.json",
    )
    assert result.skipped == []
    [sidecar] = result.sidecars
    assert sidecar.rules == [
        ManifestDependencyRule(
            inputs=["//data/full/**", "//data/partial/one.json", "//data/single/only.json"],
            kind="content",
            reason=CONTENT_REASON,
        )
    ]
    assert sidecar.covers["//data/full/**"] == [
        "data/full/nested/three.json",
        "data/full/one.json",
        "data/full/two.json",
    ]


def test_shared_convention_satisfies_audit_without_regenerating_sidecars(repo: Path, tmp_path: Path) -> None:
    write(repo, "tests/data/input.json", "1")
    write(
        repo,
        "tests/.gv-dependencies.yaml",
        'dependencies: [{readers: ["test_*.py"], relative_to: reader, inputs: ["data/*.json"], kind: content}]',
    )
    commit(repo)
    assert plan(repo, tmp_path, "tests/data/input.json").sidecars == []
    # A read outside the convention still needs a declaration.
    [missing] = plan(repo, tmp_path, "tests/data/input.json", "data/other.json").sidecars
    assert missing.rules == [
        ManifestDependencyRule(inputs=["//data/other.json"], kind="content", reason=CONTENT_REASON)
    ]


def test_python_inputs_are_import_rules_even_when_globbed(repo: Path, tmp_path: Path) -> None:
    # A script run in a subprocess also depends on what it imports, which `import` follows.
    [sidecar] = plan(repo, tmp_path, "scripts/tool.py", "scripts/helper.py", "data/other.json").sidecars
    assert sidecar.rules == [
        ManifestDependencyRule(inputs=["//data/other.json"], kind="content", reason=CONTENT_REASON),
        ManifestDependencyRule(inputs=["//scripts/**"], kind="import", reason=IMPORT_REASON),
    ]


def test_a_path_the_declaration_language_cannot_name_is_reported_not_written(repo: Path, tmp_path: Path) -> None:
    write(repo, "data/odd[1].json", "1\n")
    commit(repo)
    result = plan(repo, tmp_path, "data/odd[1].json", "data/other.json")
    assert [rule.inputs for sidecar in result.sidecars for rule in sidecar.rules] == [["//data/other.json"]]
    assert len(result.skipped) == 1
    assert result.skipped[0].startswith(f"{TEST} -> data/odd[1].json: ")


def test_rules_are_appended_to_an_existing_sidecar_keeping_its_comments(repo: Path, tmp_path: Path) -> None:
    existing = "# Reviewed by hand.\ndependencies:\n  - inputs: ['//data/single/only.json']\n    kind: content\n"
    (repo / f"{TEST}.gv-dependency.yaml").write_bytes(existing.encode())
    [sidecar] = plan(repo, tmp_path, "data/other.json").sidecars
    write_sidecar(repo, sidecar)
    text = (repo / f"{TEST}.gv-dependency.yaml").read_bytes().decode()
    assert text.startswith(existing)
    assert text.endswith(
        f'  - inputs:\n      - "//data/other.json"\n    kind: content\n    reason: "{CONTENT_REASON}"\n'
    )


def test_a_sidecar_the_rules_cannot_be_appended_to_is_left_untouched(repo: Path, tmp_path: Path) -> None:
    existing = "dependencies: [{inputs: ['//data/single/only.json'], kind: content}]\n"
    path = repo / f"{TEST}.gv-dependency.yaml"
    path.write_bytes(existing.encode())
    [sidecar] = plan(repo, tmp_path, "data/other.json").sidecars
    with pytest.raises(DependencyDeclarationError, match="add these rules by hand"):
        write_sidecar(repo, sidecar)
    assert path.read_bytes().decode() == existing


def test_each_sidecar_says_how_many_tests_its_inputs_select(repo: Path, tmp_path: Path) -> None:
    # Another test module imports the reader, so a declared input reaches both.
    write(repo, "tests/test_other.py", "from tests.test_reader import test_read\n")
    write(repo, "tests/test_alone.py", "def test_alone(): pass\n")
    commit(repo)
    result = plan(repo, tmp_path, "data/other.json")
    assert result.total_tests == 3
    assert [(sidecar.test, sidecar.selects) for sidecar in result.sidecars] == [(TEST, 2)]
