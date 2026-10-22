import json
from pathlib import Path

import pytest

from pytest_selective.pytest_sharding import (
    DEFAULT_TEST_FILE_PATTERNS,
    SplitUnit,
    add_missing_test_files,
    greedy_bin_pack,
    merge_duration_files,
    plan_shard_count,
    plan_shards,
    write_shard_files,
)

EXACT_SHARD_COUNT = 2


def test_greedy_bin_pack_balances_longest_units_and_orders_paths() -> None:
    units = {
        "tests/test_z.py": SplitUnit(duration=6.0, count=2, file_count=1),
        "tests/test_a.py": SplitUnit(duration=4.0, count=1, file_count=1),
        "tests/test_b.py": SplitUnit(duration=2.0, count=1, file_count=1),
    }

    shards = greedy_bin_pack(units, shard_count=2)

    assert [shard.duration for shard in shards] == [6.0, 6.0]
    assert shards[1].paths == ["tests/test_a.py", "tests/test_b.py"]


def test_greedy_bin_pack_rejects_zero_shards() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        greedy_bin_pack({}, shard_count=0)


def test_new_test_file_gets_small_nonzero_weight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_known.py").touch()
    (tests_dir / "test_new.py").touch()

    durations = add_missing_test_files({"tests/test_known.py::test_one": 4.0}, [Path("tests")])

    assert durations["tests/test_new.py::__unknown_duration__"] == 1.0
    assert "tests/test_known.py::__unknown_duration__" not in durations


def test_single_file_roots_are_discovered_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    File-level CI selection passes individual changed test files as roots;
    `rglob` on a file yields nothing, so files need their own branch."""
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_selected.py").touch()
    (tests_dir / "helpers.py").touch()

    durations = add_missing_test_files({}, [Path("tests/test_selected.py"), Path("tests/helpers.py")])

    assert list(durations) == ["tests/test_selected.py::__unknown_duration__"]


def test_plan_drops_deleted_files_and_assigns_every_current_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").touch()
    (tests_dir / "test_b.py").touch()

    shards = plan_shards(
        {"tests/test_a.py::test_one": 4.0, "tests/test_deleted.py::test_gone": 100.0},
        [Path("tests")],
        shard_count=2,
    )

    assigned = {path for shard in shards for path in shard.paths}
    assert assigned == {"tests/test_a.py", "tests/test_b.py"}


def test_plan_ignores_durations_outside_selected_test_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: scoped shard plans contain only the selected test inventory."""
    monkeypatch.chdir(tmp_path)
    selected_dir = tmp_path / "tests" / "selected"
    selected_dir.mkdir(parents=True)
    unrelated_dir = tmp_path / "tests" / "unrelated"
    unrelated_dir.mkdir()
    (selected_dir / "test_selected.py").touch()
    (unrelated_dir / "test_unrelated.py").touch()

    shards = plan_shards(
        {
            "tests/selected/test_selected.py::test_selected": 1.0,
            "tests/unrelated/test_unrelated.py::test_unrelated": 100.0,
        },
        [Path("tests/selected")],
        shard_count=EXACT_SHARD_COUNT,
        exact_files=True,
    )

    assigned = [path for shard in shards for path in shard.paths]
    assert assigned == ["tests/selected/test_selected.py"]


def test_exact_file_plans_cover_every_supported_test_module_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: exact manifests partition the complete test-file inventory."""
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    expected = {
        "tests/test_prefix.py",
        "tests/suffix_test.py",
        "tests/suffix_tests.py",
        "tests/tests.py",
    }
    for relative_path in expected:
        (tmp_path / relative_path).touch()
    (tests_dir / "helper.py").touch()

    shards = plan_shards(
        {"tests/test_prefix.py::test_measured": 4.0},
        [Path("tests")],
        shard_count=EXACT_SHARD_COUNT,
        exact_files=True,
        test_file_patterns=DEFAULT_TEST_FILE_PATTERNS,
    )

    assigned = [path for shard in shards for path in shard.paths]
    assert set(assigned) == expected
    assert len(assigned) == len(set(assigned))
    assert all(Path(path).is_file() for path in assigned)


def test_write_shard_files_uses_one_based_stable_names(tmp_path: Path) -> None:
    shards = greedy_bin_pack(
        {"tests/test_a.py": SplitUnit(duration=1.0, count=1, file_count=1)},
        shard_count=2,
    )

    write_shard_files(shards, tmp_path)

    assert (tmp_path / "group-1.txt").read_text() == "tests/test_a.py\n"
    assert (tmp_path / "group-2.txt").read_text() == ""


def test_merge_duration_files_keeps_maximum_duplicate_and_sorts_output(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    first.write_text(json.dumps({"tests/test_b.py::test_b": 1.0, "tests/test_a.py::test_a": 2.0}))
    second = tmp_path / "second.json"
    second.write_text(json.dumps({"tests/test_a.py::test_a": 3.0}))
    output = tmp_path / "merged.json"

    merged = merge_duration_files([first, second, tmp_path / "missing.json"], output)

    assert merged == {"tests/test_a.py::test_a": 3.0, "tests/test_b.py::test_b": 1.0}
    assert list(json.loads(output.read_text())) == ["tests/test_a.py::test_a", "tests/test_b.py::test_b"]


def test_slow_selection_gets_more_shards_than_its_file_count_would_buy() -> None:
    """
    INVARIANT: shard count follows the work, not the number of files holding it.

    Falsifies sizing from `len(selected)` alone. Thirty files worth 281s of
    measured work is one shard under a files-per-shard rule, so the default gate
    runs a scoped selection for as long as a near-complete suite.
    """
    selected = [f"tests/test_{index}.py" for index in range(30)]
    durations = {f"{path}::test_case": 281.0 / 30 for path in selected}

    assert plan_shard_count(selected, durations, max_shards=8, shard_seconds=120.0) == 3


def test_fast_selection_keeps_the_file_count_shape() -> None:
    """CONTROL: the duration rule leaves a cheap selection exactly where it was."""
    selected = [f"tests/test_{index}.py" for index in range(30)]
    durations = {f"{path}::test_case": 0.5 for path in selected}

    assert plan_shard_count(selected, durations, max_shards=8, shard_seconds=120.0) == 1


def test_duration_sizing_never_shards_less_than_file_count_sizing() -> None:
    """
    INVARIANT: the duration rule may only add shards.

    Sixty fast files are two shards by file count; a cheap total must not talk
    the planner back down to one and make a wide selection serial.
    """
    selected = [f"tests/test_{index}.py" for index in range(60)]
    durations = {f"{path}::test_case": 0.1 for path in selected}

    assert plan_shard_count(selected, durations, max_shards=8, shard_seconds=120.0) == 2


def test_shards_never_outnumber_the_files_they_would_hold() -> None:
    """
    INVARIANT: a file is the smallest schedulable unit, so an extra shard is empty.

    An empty shard still starts a pytest process, and a path file with no paths
    is what makes one collect the whole repository instead of nothing.
    """
    durations = {"tests/test_slow.py::test_case": 900.0}

    assert plan_shard_count(["tests/test_slow.py"], durations, max_shards=8, shard_seconds=120.0) == 1


def test_shard_count_is_capped_by_the_runner_width() -> None:
    selected = [f"tests/test_{index}.py" for index in range(40)]
    durations = {f"{path}::test_case": 100.0 for path in selected}

    assert plan_shard_count(selected, durations, max_shards=8, shard_seconds=120.0) == 8


def test_unmeasured_selection_falls_back_to_file_count_sizing() -> None:
    """
    INVARIANT: a missing or stale duration manifest cannot shrink the plan.

    New test files have no measured node ids at all; reading that as zero work
    would size every fresh selection at one shard.
    """
    selected = [f"tests/test_{index}.py" for index in range(60)]

    assert plan_shard_count(selected, {}, max_shards=8, shard_seconds=120.0) == 2


def test_empty_selection_plans_no_shards() -> None:
    assert plan_shard_count([], {"tests/test_one.py::test_case": 10.0}, max_shards=8, shard_seconds=120.0) == 0
