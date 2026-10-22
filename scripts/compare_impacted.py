"""Replay shared local-change scenarios against installed selectors.

Install pytest-impacted separately at the revision being compared. It is an
experiment dependency, not a pytest-selective runtime dependency. No source or
test imports are executed during the comparison.
"""

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
from pathlib import Path

from pytest_impacted.api import get_impacted_tests
from pytest_impacted.git import GitMode
from pytest_impacted.strategies import clear_dep_tree_cache

from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected
from pytest_selective.working_tree import snapshot_working_tree


def replay(case: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="selector-comparison-") as directory:
        folder = Path(directory)
        repo = folder / "repo"
        repo.mkdir()

        def write(path: str, text: str) -> None:
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        def git(*args: str) -> str:
            return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()

        git("init", "-q")
        write("pkg/__init__.py", "")
        write("pkg/value.py", "VALUE = 1\n")
        write("pkg/helper.py", "from .value import VALUE\n")
        write("tests/left/test_value.py", "from pkg.helper import VALUE\ndef test_value(): assert VALUE\n")
        write("tests/right/test_other.py", "def test_other(): assert True\n")
        if case == "application fixture":
            write("tests/left/conftest.py", "from pkg.helper import VALUE\n")
            write("tests/left/test_value.py", "def test_value(): assert True\n")
        git("add", "-A")
        git(
            "-c",
            "user.name=Comparison",
            "-c",
            "user.email=compare@example.invalid",
            "-c",
            "core.hooksPath=",
            "commit",
            "-qm",
            "baseline",
        )
        if case == "deleted source":
            (repo / "pkg/value.py").unlink()
        elif case == "dependency file":
            write("requirements.txt", "example==1\n")
        elif case == "documentation":
            write("README.md", "# Documentation\n")
        elif case == "untracked test":
            write("tests/right/test_new.py", "def test_new(): assert True\n")
        elif case == "package initializer":
            write("pkg/__init__.py", "FLAG = True\n")
        else:
            write("pkg/value.py", "VALUE = 2\n")

        result = {"case": case}
        for conservative in (False, True):
            clear_dep_tree_cache()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                paths = (
                    get_impacted_tests(
                        GitMode.UNSTAGED,
                        "",
                        repo,
                        "pkg",
                        tests_dir="tests",
                        conftest_imports=conservative,
                    )
                    or []
                )
            result["impacted_conservative" if conservative else "impacted_default"] = sorted(
                Path(path).resolve().relative_to(repo.resolve()).as_posix() for path in paths
            )
        cache = GraphCache(folder / "cache.db")
        try:
            result["selective"] = affected(
                repo,
                "HEAD",
                snapshot_working_tree(repo),
                ImpactConfig(test_roots=["tests"]),
                cache,
            ).selected
        finally:
            cache.close()
        assert result["selective"] == result["impacted_conservative"], result
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [
        replay(case)
        for case in (
            "transitive source",
            "deleted source",
            "dependency file",
            "documentation",
            "untracked test",
            "package initializer",
            "application fixture",
        )
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
