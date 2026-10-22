"""Select complete CI lanes while preserving each lane's execution/evidence contract."""

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import Field, field_validator

from pytest_selective.impact_graph import DependencyDeclarationError, GraphCache, matches, within
from pytest_selective.impact_models import ImpactConfig, ImpactModel
from pytest_selective.impact_selection import affected


class Lane(ImpactModel):
    """Test roots and additional inputs of one indivisible CI execution."""

    roots: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)

    @field_validator("roots", "inputs")
    @classmethod
    def relative_paths(cls, values: list[str]) -> list[str]:
        return ImpactConfig.relative_paths(values)


class LaneConfig(ImpactModel):
    graph: ImpactConfig
    lanes: dict[str, Lane]
    global_inputs: list[str] = Field(
        default_factory=lambda: ["**/pyproject.toml", "pyproject.toml", "**/uv.lock", "uv.lock", ".github/**"]
    )

    @field_validator("lanes")
    @classmethod
    def safe_output_names(cls, lanes: dict[str, Lane]) -> dict[str, Lane]:
        if not lanes or any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in lanes):
            raise ValueError("provide lanes named with lowercase letters, digits and underscores")
        if any(not lane.roots and not lane.inputs for lane in lanes.values()):
            raise ValueError("each lane needs test roots or explicit inputs")
        return lanes


class LanePlan(ImpactModel):
    lanes: dict[str, bool]
    selected: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    reason: str
    lane_reasons: dict[str, list[str]] = Field(default_factory=dict)


def plan(repo: Path, config: LaneConfig, base: str, head: str, *, full: bool = False) -> LanePlan:
    """A missing proof runs every lane; bad declarations remain actionable failures."""

    def all_lanes(reason: str, *, selected: list[str] | None = None, changed: list[str] | None = None) -> LanePlan:
        return LanePlan(
            lanes=dict.fromkeys(config.lanes, True),
            selected=selected or [],
            changed=changed or [],
            reason=reason,
            lane_reasons={name: [reason] for name in config.lanes},
        )

    if full:
        return all_lanes("explicit full-suite checkpoint")
    cache = None
    try:
        cache = GraphCache(repo / ".test-impact/cache.sqlite3")
        report = affected(repo, base, head, config.graph, cache)
        # Removed tests are absent from report.selected, but their lane still needs
        # completeness checks. Consult the cached base inventory, not filename guesses.
        before = cache.snapshot(repo, base, config.graph)
        affected_tests = set(report.selected) | (set(report.changed) & set(before.tests))
        unmapped = sorted(
            test
            for test in affected_tests
            if not any(within(test, root) for lane in config.lanes.values() for root in lane.roots)
        )
        if unmapped:
            return all_lanes(
                "full-suite fallback: unmapped affected tests: " + ", ".join(unmapped),
                selected=report.selected,
                changed=report.changed,
            )
        global_paths = [path for path in report.changed if matches(path, config.global_inputs)]
        lanes = {}
        evidence = {}
        # Select whole lanes: validators may require complete conformance evidence.
        for name, lane in config.lanes.items():
            reasons = [f"global input: {path}" for path in global_paths]
            if report.mode == "full":
                reasons.append("all graph test files affected")
            reasons.extend(
                f"affected test: {test}" for test in report.selected if any(within(test, root) for root in lane.roots)
            )
            reasons.extend(
                f"changed root input: {path}"
                for path in report.changed
                if path not in report.selected and any(within(path, root) for root in lane.roots)
            )
            reasons.extend(f"explicit input: {path}" for path in report.changed if matches(path, lane.inputs))
            lanes[name] = bool(reasons)
            evidence[name] = reasons or ["no affected tests or changed inputs"]
        return LanePlan(
            lanes=lanes,
            selected=report.selected,
            changed=report.changed,
            reason="global CI/dependency input" if global_paths else "; ".join(report.reasons),
            lane_reasons=evidence,
        )
    except DependencyDeclarationError:
        raise
    except Exception as error:
        # A broken cache, missing Git history, or unreviewed pytest policy must
        # never turn a failed planner into a passing skipped test job.
        return all_lanes(f"full-suite fallback: {error}")
    finally:
        if cache is not None:
            cache.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = LaneConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        result = plan(args.repo, config, args.base, args.head, full=args.full)
    except (ValueError, OSError, DependencyDeclarationError) as error:
        print(f"Invalid lane configuration/dependency: {error}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for name, enabled in result.lanes.items():
                output.write(f"{name}={str(enabled).lower()}\n")
            output.write(f"lanes={json.dumps(result.lanes)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
