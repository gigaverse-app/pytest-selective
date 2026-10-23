"""Run affected local pytest files, avoiding collection of unrelated modules."""

import argparse
import errno
import os
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from pytest_selective.impact_graph import DependencyDeclarationError, GraphCache, git
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected
from pytest_selective.working_tree import snapshot_working_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="pytest arguments after --")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        config = ImpactConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        print(f"Invalid test configuration: {error}", file=sys.stderr)
        return 2
    selected = config.test_roots
    cache = None
    try:
        if not args.full:
            head = snapshot_working_tree(repo)
            # Git's private directory never enters a working-tree snapshot, even
            # before the consumer has added our cache directory to .gitignore.
            cache_path = git(repo, "rev-parse", "--git-path", "pytest-selective/cache.sqlite3").decode().strip()
            cache = GraphCache(repo / cache_path)
            config_path = args.config.resolve()
            report = affected(
                repo,
                args.base,
                head,
                config,
                cache,
                config_path=config_path.relative_to(repo).as_posix() if config_path.is_relative_to(repo) else None,
                dependency_token=os.environ.get("IMPACT_DEPENDENCY_TOKEN") or None,
            )
            if report.mode != "full" and not report.selected:
                print("No affected tests; pytest was not started.")
                return 0
            selected = config.test_roots if report.mode == "full" else report.selected
            print(f"Running {len(report.selected)} affected test files of {report.total_files}.", flush=True)
    except DependencyDeclarationError as error:
        print(f"Invalid test dependency: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Test selection full-suite fallback: {error}", file=sys.stderr)
    finally:
        if cache is not None:
            cache.close()
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    # The outer runner has already planned (or explicitly requested full).
    # Loading by entry-point name works with autoload disabled too. Never let
    # an ini default reselect a full run or calculate a second, different plan.
    pytest_command = [sys.executable, "-m", "pytest", "-p", "selective", "--no-selective"]
    # No shell splitting: paths with spaces remain one argument. In particular,
    # an empty successful plan never becomes bare pytest (which runs everything).
    try:
        return subprocess.run([*pytest_command, *selected, *extra], cwd=repo).returncode
    except OSError as error:
        if selected == config.test_roots or (error.errno != errno.E2BIG and getattr(error, "winerror", None) != 206):
            raise
        # Ask the OS rather than guessing a limit: environment size and quoting
        # also consume the available command line. Retry broader roots only once.
        print(
            "Test selection full-suite fallback: pytest command line is too long; running configured roots.",
            file=sys.stderr,
        )
    return subprocess.run([*pytest_command, *config.test_roots, *extra], cwd=repo).returncode
