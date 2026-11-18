import json
from pathlib import Path

import pytest
from selective_deps import crowded_sidecars

from pytest_selective.impact_cli import main
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, init, write

SIDECAR = "dependencies:\n  - inputs: ['//data/{name}.json']\n    kind: content\n    reason: Reads {name}.\n"


def declarations(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    config = tmp_path / "config.json"
    config.write_text(ImpactConfig(module_roots=["."], test_roots=["tests"]).model_dump_json(), encoding="utf-8")
    status = main(
        [
            "declarations",
            "--repo",
            str(repo),
            "--config",
            str(config),
            "--cache",
            str(tmp_path / "cache.sqlite3"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert captured.out, captured.err
    return status, json.loads(captured.out)


def test_crowded_sidecars_groups_file_sidecars_by_directory() -> None:
    files = [
        "a/x.py.gv-dependency.yaml",
        "a/y.py.gv-dependency.yaml",
        "a/.gv-dependencies.yaml",
        "b/z.py.gv-dependency.yaml",
        "root.py.gv-dependency.yaml",
        "other.py.gv-dependency.yaml",
    ]
    assert crowded_sidecars(files) == {
        ".": ["other.py.gv-dependency.yaml", "root.py.gv-dependency.yaml"],
        "a": ["a/x.py.gv-dependency.yaml", "a/y.py.gv-dependency.yaml"],
    }


def test_lists_unreached_readers_and_directories_to_merge(tmp_path, capsys) -> None:
    repo = tmp_path / "repo"
    init(repo)
    for name in ("one", "two", "orphan"):
        write(repo, f"data/{name}.json", "{}")
    write(repo, "pkg/__init__.py")
    write(repo, "pkg/loader.py", "def load(): return 1\n")
    write(repo, "pkg/orphan.py", "def unused(): return 1\n")
    write(repo, "tests/test_one.py", "from pkg.loader import load\ndef test_one(): assert load()\n")
    write(repo, "tests/test_two.py", "def test_two(): assert True\n")
    write(repo, "tests/test_one.py.gv-dependency.yaml", SIDECAR.format(name="one"))
    write(repo, "tests/test_two.py.gv-dependency.yaml", SIDECAR.format(name="two"))
    write(repo, "pkg/orphan.py.gv-dependency.yaml", SIDECAR.format(name="orphan"))
    commit(repo)
    status, found = declarations(repo, tmp_path, capsys)
    assert status == 1
    assert found == {
        "unreached": ["pkg/orphan.py"],
        "crowded": {"tests": ["tests/test_one.py.gv-dependency.yaml", "tests/test_two.py.gv-dependency.yaml"]},
    }

    (repo / "pkg/orphan.py.gv-dependency.yaml").unlink()
    for name in ("one", "two"):
        (repo / f"tests/test_{name}.py.gv-dependency.yaml").unlink()
    write(
        repo,
        "tests/.gv-dependencies.yaml",
        "dependencies:\n  - readers: [test_one.py, test_two.py]\n    inputs: ['//data/one.json', '//data/two.json']\n"
        "    kind: content\n    reason: The tests read the shared data files.\n",
    )
    commit(repo)
    assert declarations(repo, tmp_path, capsys) == (0, {"unreached": [], "crowded": {}})
