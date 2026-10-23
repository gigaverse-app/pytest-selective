"""Select complete CI lanes while preserving each lane's execution/evidence contract."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator

from pytest_selective.impact_graph import DependencyDeclarationError, GraphCache, git, matches, within
from pytest_selective.impact_models import ImpactConfig, ImpactModel
from pytest_selective.impact_selection import affected
from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS

JOB_INPUT = re.compile(r"(?P<path>[^#*?\[\]]+)#(?P<job>[A-Za-z_][A-Za-z0-9_-]*)")


def job_input(value: str) -> tuple[str, str] | None:
    """`<workflow path>#<job id>` names one GitHub Actions job; any other input is a glob."""
    if "#" not in value:
        return None
    match = JOB_INPUT.fullmatch(value)
    if match is None:
        raise ValueError(f"{value!r}: write a job input as `<workflow path>#<job id>`, without wildcards")
    return match["path"], match["job"]


class Lane(ImpactModel):
    """Test roots and additional inputs of one indivisible CI execution."""

    roots: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)

    @field_validator("roots", "inputs")
    @classmethod
    def relative_paths(cls, values: list[str]) -> list[str]:
        return ImpactConfig.relative_paths(values)

    @field_validator("inputs")
    @classmethod
    def valid_job_inputs(cls, values: list[str]) -> list[str]:
        for value in values:
            job_input(value)
        return values


class LaneConfig(ImpactModel):
    graph: ImpactConfig
    lanes: dict[str, Lane]
    # None keeps the built-in policy distinct from an adopter's explicit globs,
    # including after JSON serialization. Explicit declarations always win.
    global_inputs: list[str] | None = None

    def is_global_input(self, path: str) -> bool:
        if self.global_inputs is not None:
            return matches(path, self.global_inputs)
        if path.startswith(".github/"):
            # Markdown is documentation unless a reader or adopter declares it.
            # Retain unknown/extensionless CI inputs rather than an extension allowlist.
            return Path(path).suffix.lower() not in {".md", ".markdown"}
        return matches(path, list(DEFAULT_GLOBAL_INPUTS))

    @field_validator("lanes")
    @classmethod
    def safe_output_names(cls, lanes: dict[str, Lane]) -> dict[str, Lane]:
        if not lanes or any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in lanes):
            raise ValueError("provide lanes named with lowercase letters, digits and underscores")
        if any(not lane.roots and not lane.inputs for lane in lanes.values()):
            raise ValueError("each lane needs test roots or explicit inputs")
        return lanes

    @model_validator(mode="after")
    def job_inputs_can_narrow(self) -> "LaneConfig":
        # A global input runs every lane before job inputs are consulted, so the
        # job input would silently never narrow anything.
        for lane in self.lanes.values():
            for value in lane.inputs:
                scoped = job_input(value)
                if scoped and self.is_global_input(scoped[0]):
                    raise ValueError(
                        f"{value!r} cannot narrow: {scoped[0]} matches a global input, which runs every lane; "
                        "set global_inputs without it"
                    )
        return self


class WorkflowJobs:
    """Whether one job of a workflow file changed, including the settings every job inherits."""

    def __init__(self, repo: Path, base: str, head: str) -> None:
        self.repo = repo
        self.base = base
        self.head = head
        self.documents: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
        self.heads: dict[str, dict[str, Any] | None] = {}

    def changed(self, path: str, job: str) -> bool:
        if path not in self.documents:
            self.documents[path] = (self.load(self.base, path), self.load(self.head, path))
        before, after = (self.view(document, job) for document in self.documents[path])
        if before[1] is None and after[1] is None:
            raise DependencyDeclarationError(f"{path}#{job}: {path} has no job {job!r} at the base or the head")
        return before != after

    def require(self, path: str, job: str) -> None:
        """Reject a misspelled job before the change it should have caught."""
        if path not in self.heads:
            self.heads[path] = self.load(self.head, path)
        if self.view(self.heads[path], job)[1] is None:
            raise DependencyDeclarationError(f"{path}#{job}: {path} has no job {job!r}")

    def load(self, revision: str, path: str) -> dict[str, Any] | None:
        """The parsed workflow, or None when the revision does not have the file."""
        try:
            text = git(self.repo, "show", f"{revision}:{path}")
        except subprocess.CalledProcessError:
            return None
        # Malformed YAML raises, so the planner falls back to every lane.
        document = yaml.safe_load(text)
        if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
            raise ValueError(f"{path} at {revision} is not a workflow with a jobs mapping")
        return document

    @staticmethod
    def view(document: dict[str, Any] | None, job: str) -> tuple[dict[str, Any], Any]:
        # Triggers, env, defaults, permissions and concurrency apply to every job.
        if document is None:
            return {}, None
        return {key: value for key, value in document.items() if key != "jobs"}, document["jobs"].get(job)


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
        global_paths = [path for path in report.changed if config.is_global_input(path)]
        changed = set(report.changed)
        workflows = WorkflowJobs(repo, base, head)
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
            globs = [value for value in lane.inputs if job_input(value) is None]
            reasons.extend(f"explicit input: {path}" for path in report.changed if matches(path, globs))
            unchanged_jobs = []
            for value in lane.inputs:
                scoped = job_input(value)
                if scoped is None:
                    continue
                if scoped[0] not in changed:
                    workflows.require(*scoped)
                elif workflows.changed(*scoped):
                    reasons.append(f"explicit input: {value}")
                else:
                    unchanged_jobs.append(f"unchanged job: {value}")
            lanes[name] = bool(reasons)
            evidence[name] = reasons or unchanged_jobs or ["no affected tests or changed inputs"]
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
