"""A pull request is planned against the base its merge commit was built on, not the event's older base."""

import subprocess
from pathlib import Path

from pytest_selective.ci import Lane, LaneConfig, plan
from pytest_selective.ci import main as plan_main
from pytest_selective.git_operations import pull_request_merge_base
from pytest_selective.impact_models import ImpactConfig
from tests.testing.git_repo import commit, init, write


def _git(root: Path, *args: str) -> str:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    return subprocess.run(
        ["git", "-C", str(root), *identity, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _behind_pr(root: Path) -> tuple[str, str, str, str]:
    """
    GitHub's shape when a PR falls behind: the PR branched from `old_base`, main then bumped a
    dependency (a global input), and refs/pull/N/merge merges the PR head into main's new tip.
    Returns (old_base, main_tip, pr_head, merge).
    """
    init(root)
    write(root, "requirements.txt", "demo-dependency==1.0\n")
    write(root, "src/demo/a.py", "A = 1\n")
    write(root, "src/demo/b.py", "B = 1\n")
    write(root, "tests/test_a.py", "from demo.a import A\ndef test_a(): assert A\n")
    write(root, "tests/test_b.py", "from demo.b import B\ndef test_b(): assert B\n")
    old_base = commit(root, "base")
    _git(root, "branch", "-M", "main")
    _git(root, "checkout", "-q", "-b", "pr")
    write(root, "src/demo/a.py", "A = 2\n")
    pr_head = commit(root, "pr changes a.py")
    _git(root, "checkout", "-q", "main")
    write(root, "requirements.txt", "demo-dependency==1.1\n")
    main_tip = commit(root, "dependency bump on main")
    _git(root, "merge", "-q", "--no-ff", "-m", "Merge pr into main", "pr")
    merge = _git(root, "rev-parse", "HEAD")
    return old_base, main_tip, pr_head, merge


def _lanes() -> LaneConfig:
    return LaneConfig(
        graph=ImpactConfig(module_roots=["src"], test_roots=["tests"]),
        lanes={"a": Lane(roots=["tests/test_a.py"]), "b": Lane(roots=["tests/test_b.py"])},
    )


def test_a_pr_behind_main_is_planned_against_its_merge_base(tmp_path: Path) -> None:
    old_base, main_tip, pr_head, merge = _behind_pr(tmp_path)
    assert pull_request_merge_base(tmp_path, old_base, merge, pr_head) == main_tip
    # The dependency bump is main's change, not the PR's: only a.py's tests are affected.
    assert plan(tmp_path, _lanes(), main_tip, merge).lanes == {"a": True, "b": False}
    # Against the event's stale base, main's bump reads as the PR's own global-input change.
    assert plan(tmp_path, _lanes(), old_base, merge).lanes == {"a": True, "b": True}


def test_the_planner_cli_uses_the_merge_base_when_given_the_pr_head(tmp_path: Path, capsys) -> None:
    old_base, main_tip, pr_head, merge = _behind_pr(tmp_path)
    config = tmp_path / "lanes.json"
    config.write_text(_lanes().model_dump_json(), encoding="utf-8")
    args = ["--repo", str(tmp_path), "--config", str(config), "--base", old_base, "--head", merge]
    assert plan_main([*args, "--pr-head", pr_head]) == 0
    narrowed = capsys.readouterr()
    assert '"b": false' in narrowed.out and main_tip in narrowed.err
    assert plan_main(args) == 0
    assert '"b": true' in capsys.readouterr().out


def test_anything_but_a_pr_merge_keeps_the_given_base(tmp_path: Path) -> None:
    old_base, main_tip, pr_head, merge = _behind_pr(tmp_path)
    # A push: no PR head, so a multi-commit push keeps every pushed commit's changes.
    assert pull_request_merge_base(tmp_path, old_base, merge, "") == old_base
    # A head that is not the merge of this PR head.
    assert pull_request_merge_base(tmp_path, old_base, main_tip, pr_head) == old_base
    assert pull_request_merge_base(tmp_path, old_base, merge, main_tip) == old_base
    # A base that is not an ancestor of the merge's first parent (for example an earlier validated PR head).
    assert pull_request_merge_base(tmp_path, pr_head, merge, pr_head) == pr_head
    # An unknown PR head is not proof of anything.
    assert pull_request_merge_base(tmp_path, old_base, merge, "0" * 40) == old_base
