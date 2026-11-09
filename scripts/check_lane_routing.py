"""Plan one-file changes with CI-esta's planner and this repository's lane file, and fail on unexpected lanes.

CI plans its lanes with CI-esta's `plan-work`, which reads them from the workflows and .github/test-lanes.json, so
the routing can only be checked with CI-esta installed. The `quality` job, which never skips, runs:

    uv run --no-project --python 3.14 --with "ci-esta[selection]>=1.12.0,<2.0.0" python scripts/check_lane_routing.py

The checkout's tracked files, including uncommitted edits, become the first commit of a temporary repository. Each
row commits a one-line change to one path, plans it against that first commit, and resets.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ci_esta.testing.lane_inference import resolve
from ci_esta.testing.work_plan import plan_work

ROOT = Path(__file__).resolve().parents[1]
LANE_FILE = Path(".github/test-lanes.json")
EVERY = {"tests", "contracts", "package"}
PACKAGE = {"package"}
TESTS = {"tests"}
NOTHING: set[str] = set()
# A one-line change to the path must plan exactly these lanes.
ROUTES: dict[str, set[str]] = {
    # Every lane-gated job runs the public actions, and the planner job runs the root action.
    "action.yml": EVERY,
    "actions/plan-lanes/action.yml": EVERY,
    "actions/test-impact/action.yml": EVERY,
    # Only the public-action smoke and the tests that read it use the gate action; CI uses CI-esta's.
    "actions/validation-gate/action.yml": TESTS,
    # A file no job runs and no test reads.
    "actions/plan-lanes/helper.py": NOTHING,
    "actions/README.md": NOTHING,
    # Both distributions embed README.md and LICENSE; the contract job checks the README's contract report, and
    # tests/test_distribution_metadata.py imports scripts/check_metadata.py, which reads the README.
    "README.md": EVERY,
    "LICENSE": PACKAGE,
    "CONTRIBUTING.md": NOTHING,
    "docs/ci.md": NOTHING,
    "docs/benchmarks/data.json": NOTHING,
    # Read the Docs dependencies are not the test environment.
    "documentation/requirements.txt": NOTHING,
    "documentation/requirements.in": NOTHING,
    "documentation/check_site.py": NOTHING,
    "documentation/llms.txt": NOTHING,
    "mkdocs.yml": NOTHING,
    "skills/pytest-selective/SKILL.md": NOTHING,
    ".github/dependabot.yml": NOTHING,
    ".github/pull_request_template.md": NOTHING,
    # `quality` runs pre-commit on every change; no lane runs it.
    ".pre-commit-config.yaml": NOTHING,
    # The tests that check the workflows read every workflow; an unchanged job selects nothing else.
    ".github/workflows/observe-ci.yml": TESTS,
    ".github/workflows/release.yml": TESTS,
    ".github/workflows/ci.yml": TESTS,
    # The planner reads the lane files, so they reach every lane.
    ".github/test-lanes.json": EVERY,
    ".github/plan-lanes.json": EVERY,
    "scripts/ci_file_config.py": EVERY,
    # The package lane runs the distribution checks; the smoke step runs only when the tests lane is planned.
    "scripts/check_metadata.py": {"package", "tests"},
    "scripts/smoke_distribution.py": {"package", "tests"},
    "scripts/tutorial.py": {"package", "tests"},
    # Scripts no job runs and no test imports.
    "scripts/benchmark_graph.py": NOTHING,
    "scripts/public_actions.py": NOTHING,
    # Every test loads the package's pytest11 plugin, and the contract imports the graph.
    "src/pytest_selective/plugin.py": EVERY,
    "src/pytest_selective/impact_graph.py": EVERY,
    # Lane planning is outside the Quint contract.
    "src/pytest_selective/ci.py": {"package", "tests"},
    "tests/test_hygiene.py": TESTS,
    "tests/testing/git_repo.py": EVERY,
    "contracts/selection/selection.qnt": {"contracts"},
    "contracts/selection/quint-connect.json": {"contracts"},
    "contracts/selection/quint.ini": {"contracts"},
    "contracts/selection/README.md": NOTHING,
    "pyproject.toml": EVERY,
    "uv.lock": EVERY,
    ".python-version": EVERY,
}
COMMENTS = {".py": "\n# probe\n", ".toml": "\n# probe\n", ".yml": "\n# probe\n", ".yaml": "\n# probe\n"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def copy_tracked(repo: Path) -> str:
    for name in git(ROOT, "ls-files", "-z").split("\0"):
        source = ROOT / name
        if name and source.is_file():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "routing@example.invalid")
    git(repo, "config", "user.name", "routing")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--no-verify", "-m", "base")
    return git(repo, "rev-parse", "HEAD")


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="lane-routing-") as temporary:
        repo = Path(temporary)
        base = copy_tracked(repo)
        resolved = resolve(repo, base, base, repo / LANE_FILE)
        full = plan_work(repo, resolved.config, base, base, full=True, rules=resolved.rules)
        if {name for name, enabled in full.lanes.items() if enabled} != EVERY:
            failures.append(f"a full checkpoint planned {full.lanes}")
        for path, expected in ROUTES.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(COMMENTS.get(target.suffix, "\n"))
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "--no-verify", "-m", f"change {path}")
            head = git(repo, "rev-parse", "HEAD")
            resolved = resolve(repo, base, head, repo / LANE_FILE)
            result = plan_work(repo, resolved.config, base, head, rules=resolved.rules)
            selected = {name for name, enabled in result.lanes.items() if enabled}
            print(f"{'ok' if selected == expected else 'UNEXPECTED':10} {path}: {sorted(selected)}", flush=True)
            if selected != expected:
                failures.append(
                    f"{path}: planned {sorted(selected)}, expected {sorted(expected)}: {result.lane_reasons}"
                )
            git(repo, "reset", "-q", "--hard", base)
            git(repo, "clean", "-qfd")
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
