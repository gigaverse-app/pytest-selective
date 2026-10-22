"""The published tutorial must find the regression and skip an empty selection."""

import json
import subprocess
import sys
from pathlib import Path

from pytest_selective.impact_cli import main
from tests.testing.git_repo import commit, init, write


def test_tutorial_runs_real_git_selection_and_pytest(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "tutorial.py"
    subprocess.run([sys.executable, str(script), "--output", str(report)], check=True)
    scenarios = json.loads(report.read_text(encoding="utf-8"))
    assert [scenario["mode"] for scenario in scenarios] == ["scoped", "none", "full"]
    assert scenarios[0]["selected"] == ["tests/test_checkout.py"]
    assert [scenario["pytest_exit"] for scenario in scenarios] == [1, None, 1]


def test_adoption_fingerprints_and_reader_owned_data(tmp_path: Path) -> None:
    """The configuration guide must select a data reader after policy enrollment."""
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    write(root, "tests/test_prices.py", "def test_prices(): pass\n")
    write(root, "tests/test_other.py", "def test_other(): pass\n")
    write(root, "tests/data/prices.json", '{"price": 3}\n')
    write(root, "uv.lock", "version = 1\n")
    write(
        root,
        "tests/test_prices.py.gv-dependency.yaml",
        'dependencies:\n  - inputs: ["//tests/data/prices.json"]\n'
        "    kind: content\n    reason: Reads expected prices.\n",
    )
    config = {
        "module_roots": ["."],
        "test_roots": ["tests"],
        "dependencies": [
            {
                "readers": ["tests/*.py"],
                "inputs": ["uv.lock", "pyproject.toml"],
                "kind": "content",
                "reason": "All tests use this dependency environment.",
            }
        ],
    }
    write(root, ".github/test-impact.json", json.dumps(config))
    commit(root)
    config_path = root / ".github/test-impact.json"
    common = ["--repo", str(root), "--config", str(config_path), "--cache", str(tmp_path / "cache.sqlite3")]
    fingerprints = tmp_path / "fingerprints.json"
    assert main(["fingerprints", *common, "--output", str(fingerprints)]) == 0
    config["pytest_policy"] = json.loads(fingerprints.read_text(encoding="utf-8"))
    assert "pyproject.toml" in config["pytest_policy"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    base = commit(root)
    write(root, "tests/data/prices.json", '{"price": 4}\n')
    head = commit(root)
    report = tmp_path / "selection.json"
    assert main(["affected", *common, "--base", base, "--head", head, "--output", str(report)]) == 0
    selection = json.loads(report.read_text(encoding="utf-8"))
    assert selection["mode"] == "scoped"
    assert selection["selected"] == ["tests/test_prices.py"]
    write(root, "uv.lock", "version = 2\n")
    lock_head = commit(root)
    assert main(["affected", *common, "--base", head, "--head", lock_head, "--output", str(report)]) == 0
    selection = json.loads(report.read_text(encoding="utf-8"))
    assert selection["mode"] == "full"
    assert selection["selected"] == ["tests/test_other.py", "tests/test_prices.py"]
