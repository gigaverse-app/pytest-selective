"""Run a real Git -> selection -> pytest journey in a disposable repository."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(root: Path, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(args, cwd=root, env=environment, text=True, capture_output=True)
    if result.returncode != expected:
        raise RuntimeError(
            f"{args}: expected exit {expected}, got {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
    return result


def write(root: Path, name: str, content: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def commit(root: Path) -> str:
    run(root, "git", "add", "-A")
    run(
        root,
        "git",
        "-c",
        "user.name=Tutorial",
        "-c",
        "user.email=tutorial@example.invalid",
        "-c",
        "core.hooksPath=",
        "commit",
        "-qm",
        "tutorial step",
    )
    return run(root, "git", "rev-parse", "HEAD").stdout.strip()


def demonstrate(root: Path, artifacts: Path) -> list[dict]:
    run(root, "git", "init", "-q")
    files = {
        "shop/__init__.py": "",
        "shop/prices.py": "def total(price):\n    return price * 2\n",
        "shop/checkout.py": "from shop.prices import total\n",
        "tests/test_checkout.py": "from shop.checkout import total\ndef test_total():\n    assert total(3) == 6\n",
        "tests/test_health.py": "def test_health():\n    assert 2 + 2 == 4\n",
        "tests/test_labels.py": "def test_label():\n    assert 'hello'.upper() == 'HELLO'\n",
        "README.md": "# Tutorial shop\n",
        "conftest.py": "",
        "impact.json": json.dumps({"module_roots": ["."], "test_roots": ["tests"]}),
    }
    for name, content in files.items():
        write(root, name, content)
    base = commit(root)
    run(root, sys.executable, "-m", "pytest", "-q", "tests")
    scenarios = [
        ("transitive regression", "shop/prices.py", "def total(price):\n    return price * 3\n", "scoped", 1, 1),
        ("documentation only", "README.md", "# Updated tutorial shop\n", "none", 0, None),
        ("shared conftest", "conftest.py", 'CHECKOUT_MODE = "strict"\n', "full", 3, 1),
    ]
    evidence = []
    for label, path, content, mode, count, pytest_exit in scenarios:
        write(root, path, content)
        head = commit(root)
        report_path = artifacts / "selection.json"
        run(
            root,
            sys.executable,
            "-m",
            "pytest_selective",
            "affected",
            "--config",
            "impact.json",
            "--base",
            base,
            "--head",
            head,
            "--cache",
            str(artifacts / "cache.sqlite3"),
            "--output",
            str(report_path),
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["mode"] != mode or len(report["selected"]) != count:
            raise AssertionError(f"{label}: unexpected selection {report}")
        # An empty selection must skip pytest: no paths means the complete suite.
        if report["selected"]:
            run(root, sys.executable, "-m", "pytest", "-q", *report["selected"], expected=pytest_exit)
        evidence.append(
            {
                "scenario": label,
                "mode": mode,
                "selected": report["selected"],
                "total_files": report["total_files"],
                "pytest_exit": pytest_exit,
                "base": base,
                "head": head,
                "reasons": report["reasons"],
            }
        )
        print(
            f"{label}: {mode}, {count}/{report['total_files']} files; "
            + ("pytest skipped" if pytest_exit is None else f"pytest exit {pytest_exit} (expected)")
        )
        base = head
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pytest-selective-tutorial-") as temporary:
        folder = Path(temporary)
        root = folder / "repo"
        root.mkdir()
        evidence = demonstrate(root, folder)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
