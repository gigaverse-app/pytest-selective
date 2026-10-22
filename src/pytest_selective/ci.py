"""Select complete CI lanes while preserving each lane's execution/evidence contract."""

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import Field, field_validator

from pytest_selective.impact_graph import DependencyDeclarationError, GraphCache, matches
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


def plan(repo: Path, config: LaneConfig, base: str, head: str, *, full: bool = False) -> LanePlan:
    """A missing proof runs every lane; bad declarations remain actionable failures."""
    if full:
        return LanePlan(lanes=dict.fromkeys(config.lanes, True), reason="explicit full-suite checkpoint")
    cache = None
    try:
        cache = GraphCache(repo / ".test-impact/cache.sqlite3")
        report = affected(repo, base, head, config.graph, cache)
        global_change = any(matches(path, config.global_inputs) for path in report.changed)
        # Select a whole lane if any of its tests is affected. Never feed partial
        # conformance evidence into a validator that requires complete guarantees.
        lanes = {
            name: global_change
            or report.mode == "full"
            or any(
                test == root or test.startswith(root.rstrip("/") + "/")
                for test in report.selected
                for root in lane.roots
            )
            or any(matches(path, lane.inputs) for path in report.changed)
            for name, lane in config.lanes.items()
        }
        return LanePlan(
            lanes=lanes,
            selected=report.selected,
            changed=report.changed,
            reason="global CI/dependency input" if global_change else "; ".join(report.reasons),
        )
    except DependencyDeclarationError:
        raise
    except Exception as error:
        # A broken cache, missing Git history, or unreviewed pytest policy must
        # never turn a failed planner into a passing skipped test job.
        return LanePlan(lanes=dict.fromkeys(config.lanes, True), reason=f"full-suite fallback: {error}")
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
