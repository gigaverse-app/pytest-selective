"""
Inspect and use the cached test dependency graph.

Run with python -m pytest_selective.impact_cli.
"""

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pytest_selective.impact_audit import audit, load_records, summary
from pytest_selective.impact_explanation import dependent_tests, explain
from pytest_selective.impact_graph import (
    DependencyDeclarationError,
    GraphCache,
    explanation,
    git,
    inventory,
    policy_fingerprints,
    reachable,
)
from pytest_selective.impact_models import (
    GraphAnalysisReport,
    ImpactConfig,
    ImpactReport,
    SelectionExplanation,
)
from pytest_selective.impact_selection import affected, base_snapshot
from pytest_selective.pytest_sharding import (
    DEFAULT_SHARD_SECONDS,
    load_durations,
    plan_shard_count,
)
from pytest_selective.typecheck_scope import TypecheckScope, scope


def _measured_durations(path: Path) -> dict[str, float]:
    """
    Read the duration manifest the shard planner will use, or nothing.

    The manifest is restored from cache beside this step and is routinely
    absent or unreadable: a cold cache, a consumer that does not record
    timings, a truncated download. Sizing treats an empty mapping as
    unmeasured and falls back to counting files, so a bad read must not fail
    planning.
    """
    try:
        return load_durations(path)
    except OSError, ValueError:
        return {}


def _select(
    repo: Path,
    head: str,
    config: ImpactConfig,
    cache: GraphCache,
    config_path: str | None,
    dependency_cache: Path,
    base: str,
    extra_files: Path | None,
) -> ImpactReport:
    return affected(
        repo,
        base,
        head,
        config,
        cache,
        extra_files.read_text(encoding="utf-8").splitlines() if extra_files else [],
        config_path,
        dependency_cache=dependency_cache,
        # Read from the environment, never argv, so it cannot appear in a process listing.
        dependency_token=os.environ.get("IMPACT_DEPENDENCY_TOKEN") or None,
    )


def _smaller_selection(
    select: Callable[[str, Path | None], ImpactReport],
    proven: tuple[str, ImpactReport],
    alternate_base: str,
    alternate_extra: Path | None,
) -> tuple[str, ImpactReport]:
    """
    Keep whichever of two proven bases selects fewer tests.

    Each base alone is sound: the primary is a tree whose selected tests all passed (or the
    PR base itself), and the alternate is the PR base every PR diff is already trusted
    against. They differ in size when main moved: after main is merged into a validated
    PR, the delta since the validated tree carries main's own changes, and a change to a
    module every test imports selects the whole suite for a PR that edited one file.

    The alternate can only shrink a sound selection, so failing to compute it keeps the
    primary. That includes an alternate its configuration cannot describe: declarations are
    authoring errors only at the head. Unparseable source is a hard error in either tree.
    """
    base, report = proven
    try:
        candidate = select(alternate_base, alternate_extra)
    except DependencyDeclarationError:
        raise
    except Exception as error:
        report.reasons.append(f"alternate base {alternate_base} not used: {error}")
        return base, report
    if len(candidate.selected) < len(report.selected):
        candidate.reasons.append(
            f"selected from {alternate_base} instead of {base}, which selects {len(report.selected)} files"
        )
        return alternate_base, candidate
    report.reasons.append(f"kept {base}; {alternate_base} selects {len(candidate.selected)} files")
    return base, report


def _merge_base(repo: Path, graph_base: str, head: str) -> str | None:
    """
    Where the change forked from `graph_base`, the PR's own base, or None when history lacks it.

    Selection may start from a tree an earlier push already validated, which would hide a graph
    change after the first green push. Floor and widening deltas compare against the whole PR.
    """
    if not graph_base:
        return None
    try:
        return git(repo, "merge-base", graph_base, head).decode().strip() or None
    except subprocess.CalledProcessError:
        return None


def _write_explanation(
    args: argparse.Namespace,
    config: ImpactConfig,
    cache: GraphCache,
    config_path: str | None,
    base: str,
    report: ImpactReport,
) -> None:
    """
    Explain the final selection beside it, or warn; never change which tests run.

    The explanation is for the PR author. Any failure to build it must not reach the caller's
    exit status, which the CI action would read as a failed plan and replace with the full suite.
    """
    try:
        graph_base = _merge_base(args.repo, args.graph_base, args.head)
        explanation = explain(
            args.repo,
            base_snapshot(args.repo, base, config, cache, config_path),
            cache.snapshot(args.repo, args.head, config),
            report,
            config,
            graph_before=base_snapshot(args.repo, graph_base, config, cache, config_path) if graph_base else None,
            forced_full=args.full,
        )
    except Exception as error:  # noqa: BLE001 - reported, and selection stands without it
        print(f"::warning::Test selection explanation unavailable: {error}", file=sys.stderr)
        return
    args.explanation_output.parent.mkdir(parents=True, exist_ok=True)
    args.explanation_output.write_text(explanation.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _typecheck_scope(args: argparse.Namespace) -> int:
    """
    Write the files to type-check and the mode; every failure is the full check.

    Unlike test selection, a scope that cannot be computed never fails the step: the full
    check is always a correct answer, only a slower one.
    """
    cache = None
    try:
        config = ImpactConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        cache = GraphCache(args.cache)
        result = scope(
            args.repo, args.base, args.head, config, cache, args.checker_config, args.global_inputs, args.max_fraction
        )
    except Exception as error:  # noqa: BLE001 - any doubt is the full check, and the reason is reported
        result = TypecheckScope(mode="full", files=[], reason=f"scope unavailable: {error}")
    finally:
        if cache is not None:
            cache.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(f"{path}\n" for path in result.files), encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"mode={result.mode}\nfiles={len(result.files)}\nreason={result.reason}\n")
    print(f"Type-check scope: {result.mode}; {result.reason}")
    return 0


def _audit(args: argparse.Namespace, config: ImpactConfig, cache: GraphCache) -> int:
    """
    Fail on reads the head graph cannot reach from the reading test (exit 2, an authoring error).

    A missing or unreadable record raises, which is operational (exit 1): the audit proved nothing.
    """
    report = audit(cache.snapshot(args.repo, args.head, config), load_records(args.records), config)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as output:
            output.write(summary(report))
    print(
        f"Test-impact read audit: {len(report.undeclared)} undeclared of {report.recorded_reads} reads "
        f"by {report.audited_tests} test files ({report.exempted_reads} exempted or always-run)"
    )
    for read in report.undeclared:
        print(f"{read.test} -> {read.input}")
    for error in report.recorder_errors:
        print(f"recorder error: {error}", file=sys.stderr)
    return 2 if report.undeclared else 0


#: Files that joined the floor named in the budget error before the rest are counted.
BUDGET_LISTED_FILES = 10


def _floor_budget(args: argparse.Namespace) -> int:
    """
    Fail when this PR grows the startup floor past the configured `floor_budget`.

    The check reads the explanation planning already wrote, so it costs no graph work. A plan that
    fell back to the complete suite wrote no explanation it can trust, so the check passes rather
    than block a PR on an unproven floor. A floor under budget passes with a notice to lower it.
    """
    config = ImpactConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    budget = config.floor_budget
    if budget is None:
        return 0
    try:
        explanation = SelectionExplanation.model_validate_json(args.explanation.read_text(encoding="utf-8"))
    except OSError, ValueError:
        print("::warning::Startup-floor budget not checked: planning produced no explanation")
        return 0
    floor = explanation.floor
    if floor.after > budget:
        joined = floor.added[:BUDGET_LISTED_FILES]
        more = f" and {len(floor.added) - len(joined)} more" if len(floor.added) > len(joined) else ""
        through = f" They enter through {' -> '.join(step.path for step in floor.path)}." if floor.path else ""
        print(
            f"::error::This PR grows the startup floor to {floor.after} files, over its budget of {budget}. "
            f"Joined the floor: {', '.join(joined) or 'none'}{more}.{through} Remove the import that brings "
            f"them in, or raise floor_budget in {args.config} with the reason."
        )
        return 1
    if floor.after < budget:
        print(
            f"::notice::The startup floor is {floor.after} files, under its budget of {budget}. "
            f"Lower floor_budget to {floor.after} in {args.config} to keep it there."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "affected",
            "audit",
            "dependencies",
            "explain",
            "conftest-impact",
            "fingerprints",
            "floor-budget",
            "warm",
            "typecheck-scope",
        ],
    )
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".test-impact/cache.sqlite3"))
    parser.add_argument("--base", default="HEAD^")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--test", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--output", type=Path)
    # affected: why the selection is this large, for the PR sticky (never changes the selection).
    parser.add_argument("--explanation-output", type=Path)
    # affected: the PR's base, which floor and widening deltas compare against (its merge base).
    parser.add_argument("--graph-base", default="")
    parser.add_argument("--extra-files", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--minimum-files", type=int, default=0)
    parser.add_argument("--max-shards", type=int, default=8)
    parser.add_argument("--durations", type=Path, default=Path(".test_durations"))
    parser.add_argument("--shard-seconds", type=float, default=DEFAULT_SHARD_SECONDS)
    # Bare clones of declared first-party packages, cached with the parsed graph.
    parser.add_argument("--dependency-cache", type=Path, default=Path(".test-impact/dependencies"))
    # typecheck-scope: the checker's config file, inputs that change every verdict, and the
    # scope size (as a fraction of checked files) above which the full check is no slower.
    parser.add_argument("--checker-config", default="pyrightconfig.json")
    parser.add_argument("--global-input", action="append", default=[], dest="global_inputs")
    parser.add_argument("--max-fraction", type=float, default=0.6)
    # A second proven base, with its own extra files; the one that selects fewer tests wins.
    parser.add_argument("--alternate-base", default="")
    parser.add_argument("--alternate-extra-files", type=Path)
    # audit: the directory of pytest read records, and a markdown summary (GITHUB_STEP_SUMMARY) to append to.
    parser.add_argument("--records", type=Path, default=Path("impact-audit"))
    parser.add_argument("--summary", type=Path)
    # floor-budget: the explanation `affected --explanation-output` wrote for this plan.
    parser.add_argument("--explanation", type=Path, default=Path("test-impact-explanation.json"))
    args = parser.parse_args(argv)
    if args.command == "typecheck-scope":
        return _typecheck_scope(args)
    if args.command == "floor-budget":
        return _floor_budget(args)
    cache = None
    try:
        config = ImpactConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        cache = GraphCache(args.cache)
        if args.command == "audit":
            return _audit(args, config, cache)
        if args.command == "fingerprints":
            result = json.dumps(policy_fingerprints(args.repo, inventory(args.repo, args.head)), indent=2)
        elif args.command == "affected":
            config_path = (
                args.config.resolve().relative_to(args.repo.resolve()).as_posix()
                if args.config.resolve().is_relative_to(args.repo.resolve())
                else None
            )
            select = functools.partial(_select, args.repo, args.head, config, cache, config_path, args.dependency_cache)
            base = args.base
            report = select(base, args.extra_files)
            if args.alternate_base and args.alternate_base != base and not args.full:
                base, report = _smaller_selection(
                    select, (base, report), args.alternate_base, args.alternate_extra_files
                )
            if args.full:
                snapshot = cache.snapshot(args.repo, args.head, config)
                report.selected = snapshot.tests
                report.mode = "full"
                report.reasons.append("explicit full-suite event/label")
            if report.selected and len(report.selected) < args.minimum_files:
                snapshot = cache.snapshot(args.repo, args.head, config)
                extras = [test for test in snapshot.tests if test not in report.selected]
                report.selected = sorted(report.selected + extras[: args.minimum_files - len(report.selected)])
                report.reasons.append(f"minimum file count for fixed shards: {args.minimum_files}")
            result = report.model_dump_json(indent=2)
            if args.explanation_output:
                _write_explanation(args, config, cache, config_path, base, report)
            if args.github_output:
                shards = plan_shard_count(
                    report.selected,
                    _measured_durations(args.durations),
                    max_shards=args.max_shards,
                    shard_seconds=args.shard_seconds,
                )
                with args.github_output.open("a", encoding="utf-8") as output:
                    output.write(f"base={base}\n")
                    output.write(f"mode={report.mode}\n")
                    output.write(f"dependencies_unchanged={str(report.dependencies_unchanged).lower()}\n")
                    output.write(
                        f"test_roots={' '.join(config.test_roots if report.mode == 'full' else report.selected)}\n"
                    )
                    output.write(f"shard_count={shards}\ngroups={json.dumps(list(range(1, shards + 1)))}\n")
                    reason = (
                        f"Selected {len(report.selected)}/{report.total_files} test files; {'; '.join(report.reasons)}"
                    )
                    # One output per line: a multi-line reason (a quoted validation error) would
                    # truncate this value and corrupt every output GitHub parses after it.
                    output.write(f"reason={' '.join(reason.split())}\n")
        else:
            start = time.perf_counter()
            snapshot = cache.snapshot(args.repo, args.head, config)
            if args.command == "warm":
                result = GraphAnalysisReport(
                    head=snapshot.tree,
                    total_files=len(snapshot.tests),
                    elapsed_seconds=time.perf_counter() - start,
                    parsed_blobs=cache.parsed_blobs,
                    snapshot_hits=cache.snapshot_hits,
                ).model_dump_json(indent=2)
            elif args.command == "dependencies":
                result = json.dumps(sorted(reachable(snapshot.edges, {args.test})), indent=2)
            elif args.command == "explain":
                result = json.dumps(explanation(snapshot, args.test, args.source), indent=2)
            else:
                reach = dependent_tests(snapshot)
                result = json.dumps(
                    {
                        path: reach.get(path, 0).bit_count()
                        for path in sorted(snapshot.files)
                        if path.endswith("conftest.py")
                    },
                    indent=2,
                )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result + "\n", encoding="utf-8")
        else:
            print(result)
        return 0
    except DependencyDeclarationError as error:
        print(f"Invalid test dependency: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Exit nonzero: composite action falls back to its complete configured
        # roots. Never turn a missing ref or corrupt cache into an empty suite.
        print(f"Test impact planning failed: {error}", file=sys.stderr)
        return 1
    finally:
        if cache is not None:
            cache.close()


if __name__ == "__main__":
    raise SystemExit(main())
