"""Plan path-based pytest shards from historical per-test durations."""

import json
import math
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, RootModel

from pytest_selective.pytest_plugins import registers_plugins
from pytest_selective.test_inventory import (
    DEFAULT_TEST_FILE_PATTERNS as DEFAULT_TEST_FILE_PATTERNS,
)
from pytest_selective.test_inventory import discover_test_files as discover_inventory

DEFAULT_UNKNOWN_TEST_FILE_DURATION = 1.0
DEFAULT_MAX_UNIT_TESTS = 250
DEFAULT_MAX_UNIT_FILES = 10
#: Shards run as concurrent processes inside one job, so an added shard costs a
#: pytest startup rather than a runner. The bound that matters is the runner's
#: width, which the caller passes as `max_shards`.
DEFAULT_FILES_PER_SHARD = 30
DEFAULT_SHARD_SECONDS = 120.0


class DurationManifest(RootModel[dict[str, float]]):
    """Validated pytest node-id to duration mapping."""


class SplitUnit(BaseModel):
    """A collection-safe path and its historical execution weight."""

    model_config = ConfigDict(frozen=True)

    duration: float
    count: int
    file_count: int


class ShardPlan(BaseModel):
    """Paths assigned to one independent pytest runner."""

    paths: list[str]
    duration: float = 0.0
    count: int = 0


def file_path_for_nodeid(nodeid: str) -> str:
    """Return the filesystem path portion of a pytest node ID."""
    return nodeid.split("::", 1)[0]


def load_durations(path: Path) -> dict[str, float]:
    """Read and validate a pytest-split duration manifest."""
    return DurationManifest.model_validate_json(path.read_text()).root


def discover_test_files(
    test_roots: list[Path],
    test_file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
) -> set[Path]:
    """
    Discover conventionally named pytest modules below configured roots.

    A root may also be a single test module: file-level CI selection plans
    shards from individual changed files, and `Path.rglob` on a file would
    silently yield nothing.
    """
    return discover_inventory(test_roots, test_file_patterns)


def add_missing_test_files(
    durations: dict[str, float],
    test_roots: list[Path],
    unknown_test_file_duration: float = DEFAULT_UNKNOWN_TEST_FILE_DURATION,
    test_file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
) -> dict[str, float]:
    """
    Give new or intentionally unmeasured test files a small nonzero
    weight."""
    known_files = {file_path_for_nodeid(nodeid) for nodeid in durations}
    updated = dict(durations)
    for test_file in sorted(discover_test_files(test_roots, test_file_patterns)):
        file_path = test_file.as_posix()
        if file_path not in known_files:
            updated[f"{file_path}::__unknown_duration__"] = unknown_test_file_duration
    return updated


def _stats_for_tests(tests: dict[str, float]) -> SplitUnit:
    return SplitUnit(
        duration=sum(tests.values()),
        count=len(tests),
        file_count=len({file_path_for_nodeid(nodeid) for nodeid in tests}),
    )


def _should_split(unit: SplitUnit, threshold: float, max_unit_tests: int, max_unit_files: int) -> bool:
    return unit.duration > threshold or unit.count > max_unit_tests or unit.file_count > max_unit_files


def discover_split_units(
    durations: dict[str, float],
    threshold: float = 50.0,
    max_unit_tests: int = DEFAULT_MAX_UNIT_TESTS,
    max_unit_files: int = DEFAULT_MAX_UNIT_FILES,
) -> dict[str, SplitUnit]:
    """Group node IDs into collection-efficient directory or file paths."""
    top_dirs: dict[str, dict[str, float]] = defaultdict(dict)
    for nodeid, duration in durations.items():
        file_path = file_path_for_nodeid(nodeid)
        parts = file_path.split("/")
        top_dir = f"{parts[0]}/{parts[1]}" if len(parts) >= 3 else "__root__"
        top_dirs[top_dir][nodeid] = duration

    units: dict[str, SplitUnit] = {}
    for top_dir, tests in top_dirs.items():
        top_stats = _stats_for_tests(tests)
        if top_dir == "__root__":
            for nodeid, duration in tests.items():
                file_path = file_path_for_nodeid(nodeid)
                previous = units.get(file_path)
                units[file_path] = SplitUnit(
                    duration=duration + (previous.duration if previous else 0.0),
                    count=1 + (previous.count if previous else 0),
                    file_count=1,
                )
            continue

        if not _should_split(top_stats, threshold, max_unit_tests, max_unit_files):
            units[top_dir] = top_stats
            continue

        sub_groups: dict[str, dict[str, float]] = defaultdict(dict)
        for nodeid, duration in tests.items():
            file_path = file_path_for_nodeid(nodeid)
            parts = file_path.split("/")
            sub_key = f"{top_dir}/{parts[2]}" if len(parts) >= 4 else file_path
            sub_groups[sub_key][nodeid] = duration

        for sub_key, sub_tests in sub_groups.items():
            sub_stats = _stats_for_tests(sub_tests)
            if not _should_split(sub_stats, threshold, max_unit_tests, max_unit_files):
                units[sub_key] = sub_stats
                continue

            file_groups: dict[str, dict[str, float]] = defaultdict(dict)
            for nodeid, duration in sub_tests.items():
                file_groups[file_path_for_nodeid(nodeid)][nodeid] = duration
            units.update({file_path: _stats_for_tests(file_tests) for file_path, file_tests in file_groups.items()})

    return units


def discover_file_units(durations: dict[str, float]) -> dict[str, SplitUnit]:
    """Group node durations into exact test-file units."""
    file_groups: dict[str, dict[str, float]] = defaultdict(dict)
    for nodeid, duration in durations.items():
        file_groups[file_path_for_nodeid(nodeid)][nodeid] = duration
    return {file_path: _stats_for_tests(tests) for file_path, tests in file_groups.items()}


def greedy_bin_pack(units: dict[str, SplitUnit], shard_count: int) -> list[ShardPlan]:
    """Assign longest units first to the currently lightest shard."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")

    shards = [ShardPlan(paths=[]) for _ in range(shard_count)]
    for path, unit in sorted(units.items(), key=lambda item: (-item[1].duration, item[0])):
        shard = min(shards, key=lambda candidate: candidate.duration)
        shard.paths.append(path)
        shard.duration += unit.duration
        shard.count += unit.count
    for shard in shards:
        shard.paths.sort()
    return shards


def plan_shard_count(
    selected: list[str],
    durations: dict[str, float],
    *,
    max_shards: int,
    files_per_shard: int = DEFAULT_FILES_PER_SHARD,
    shard_seconds: float = DEFAULT_SHARD_SECONDS,
) -> int:
    """
    Size the shard pool from the selected work, not from the file count alone.

    Counting files reads every file as costing the same. A selection of thirty
    slow modules then plans one shard and runs for as long as a near-complete
    suite, while thirty trivial ones plan the same. Measured durations are
    already on disk for the planner, so the pool follows the work.

    The duration rule may only add shards: an unmeasured or stale manifest reads
    as no work, and sizing down on that would make every fresh selection serial.
    Shards never outnumber the files they would hold, because a file is the
    smallest schedulable unit and an emptier plan still starts a pytest process.
    """
    if not selected:
        return 0
    by_files = math.ceil(len(selected) / files_per_shard)
    chosen = set(selected)
    measured = sum(duration for nodeid, duration in durations.items() if file_path_for_nodeid(nodeid) in chosen)
    by_duration = math.ceil(measured / shard_seconds) if measured > 0 else 1
    return max(1, min(max_shards, len(selected), max(by_files, by_duration)))


def plan_shards(
    durations: dict[str, float],
    test_roots: list[Path],
    shard_count: int,
    threshold: float = 50.0,
    max_unit_tests: int = DEFAULT_MAX_UNIT_TESTS,
    max_unit_files: int = DEFAULT_MAX_UNIT_FILES,
    unknown_test_file_duration: float = DEFAULT_UNKNOWN_TEST_FILE_DURATION,
    exact_files: bool = False,
    test_file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
) -> list[ShardPlan]:
    """
    Build shard plans after dropping stale paths and adding current
    files."""
    # INVARIANT: historical durations may weight only files selected by the current roots.
    selected_files = {path.as_posix() for path in discover_test_files(test_roots, test_file_patterns)}
    live_durations = {
        nodeid: duration for nodeid, duration in durations.items() if file_path_for_nodeid(nodeid) in selected_files
    }
    complete_durations = add_missing_test_files(
        live_durations,
        test_roots,
        unknown_test_file_duration,
        test_file_patterns,
    )
    units = (
        discover_file_units(complete_durations)
        if exact_files
        else discover_split_units(complete_durations, threshold, max_unit_tests, max_unit_files)
    )
    live_units = {path: unit for path, unit in units.items() if Path(path).exists()}
    shards = greedy_bin_pack(live_units, shard_count)
    if shard_count > 1 and any(registers_plugins(Path(path).read_bytes()) for path in sorted(selected_files)):
        # A test module can register fixtures/hooks for every other collected
        # module. Independent sessions would lose that registration. Keep one
        # complete session, with empty manifests for unused runner slots.
        # Root-conftest registrations remain parallel: pytest loads them in
        # every process automatically. No test is duplicated to load a plugin.
        combined = _stats_for_tests(complete_durations)
        shards = [ShardPlan(paths=sorted(selected_files), duration=combined.duration, count=combined.count)]
        shards.extend(ShardPlan(paths=[]) for _ in range(shard_count - 1))
    if exact_files:
        assigned = [path for shard in shards for path in shard.paths]
        # Enforce the exact-manifest invariant at the production boundary: no
        # duplicate assignment and no current test module omitted.
        if len(assigned) != len(set(assigned)) or set(assigned) != selected_files:
            raise ValueError("exact shard manifests must partition the complete test-file inventory")
    return shards


def write_shard_files(shards: list[ShardPlan], output_dir: Path) -> None:
    """Write one newline-delimited pytest path file per shard."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, shard in enumerate(shards, start=1):
        content = "\n".join(shard.paths)
        (output_dir / f"group-{index}.txt").write_text(f"{content}\n" if content else "")


def merge_duration_files(input_files: list[Path], output_file: Path) -> dict[str, float]:
    """
    Merge disjoint shard manifests, retaining the maximum duplicate
    duration."""
    merged: dict[str, float] = {}
    for input_file in input_files:
        if not input_file.is_file() or input_file.stat().st_size == 0:
            continue
        for nodeid, duration in load_durations(input_file).items():
            merged[nodeid] = max(duration, merged.get(nodeid, duration))
    ordered = dict(sorted(merged.items()))
    output_file.write_text(json.dumps(ordered, indent=4) + "\n")
    return ordered
