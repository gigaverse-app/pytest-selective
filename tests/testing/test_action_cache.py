from pathlib import Path

import pytest

from pytest_selective.action_cache import cache_keys
from tests.testing.git_repo import commit, init, write


@pytest.mark.parametrize("bases", [["b" * 40, "c" * 40], ["b" * 40, "c" * 40, "d" * 40]])
def test_primary_and_restore_keys_fit_github_ten_key_limit(tmp_path: Path, bases: list[str]) -> None:
    key, restores = cache_keys(
        tmp_path,
        head="a" * 40,
        bases=bases,
        ref="refs/pull/3397/merge",
        default_branch="main",
        os_name="Linux",
        run="1-1",
    )
    assert len([key, *restores]) <= 10
    assert restores[-1] == "test-impact-v1-Linux-"
    # The ordinary two-base run must still discover its exact legacy base cache.
    assert f"test-impact-v1-Linux-{bases[0]}-" in restores


def test_cache_keys_follow_analyzed_head_and_prefer_base_over_unrelated_main(tmp_path: Path) -> None:
    init(tmp_path)
    write(tmp_path, "source.py", "VALUE = 1\n")
    base = commit(tmp_path)
    write(tmp_path, "source.py", "VALUE = 2\n")
    head = commit(tmp_path)
    main_key, _ = cache_keys(
        tmp_path, head=base, bases=[], ref="refs/heads/main", default_branch="main", os_name="Linux", run="1-1"
    )
    unrelated, _ = cache_keys(
        tmp_path, head=head, bases=[], ref="refs/heads/main", default_branch="main", os_name="Linux", run="2-1"
    )
    key, restores = cache_keys(
        tmp_path,
        head="HEAD",
        bases=[base],
        ref="refs/pull/3397/merge",
        default_branch="main",
        os_name="Linux",
        run="3-1",
    )
    assert head in key
    assert key != unrelated
    # GitHub tries prefixes in order, choosing the newest match within a prefix.
    available = [unrelated, main_key]
    restored = next(candidate for prefix in restores for candidate in available if candidate.startswith(prefix))
    assert restored == main_key
    assert restores[-1] == "test-impact-v1-Linux-"


def test_previous_pr_cache_is_preferred_and_runtime_scopes_do_not_overlap(tmp_path: Path) -> None:
    init(tmp_path)
    base = commit(tmp_path)
    write(tmp_path, "source.py", "VALUE = 2\n")
    head = commit(tmp_path)
    args = dict(ref="refs/pull/3397/merge", default_branch="main", os_name="Linux")
    previous, _ = cache_keys(tmp_path, head=base, bases=[], run="1-1", **args)
    current, restores = cache_keys(tmp_path, head=head, bases=[base, base], run="2-1", **args)
    assert previous.startswith(restores[1])
    assert current.startswith(restores[0])
    assert len(restores) == len(set(restores))
    assert "py314" in current
    windows, _ = cache_keys(
        tmp_path, head=head, bases=[], ref=args["ref"], default_branch="main", os_name="Windows", run="2-1"
    )
    assert not any(windows.startswith(prefix) for prefix in restores)


def test_legacy_exact_base_beats_newer_unrelated_cache_and_missing_optional_refs(tmp_path: Path) -> None:
    init(tmp_path)
    base = commit(tmp_path)
    key, restores = cache_keys(
        tmp_path,
        head="HEAD",
        bases=["missing-ref", base],
        ref="refs/pull/1/merge",
        default_branch="main",
        os_name="Linux",
        run="3-1",
    )
    unrelated, _ = cache_keys(
        tmp_path,
        head="a" * 40,
        bases=[],
        ref="refs/heads/main",
        default_branch="main",
        os_name="Linux",
        run="2-1",
    )
    legacy = f"test-impact-v1-Linux-{base}-1"
    available = [unrelated, legacy]
    assert next(item for prefix in restores for item in available if item.startswith(prefix)) == legacy
    assert base in key
    with pytest.raises(ValueError, match="cannot resolve cache head"):
        cache_keys(
            tmp_path, head="missing", bases=[], ref="refs/heads/main", default_branch="main", os_name="Linux", run="4-1"
        )
