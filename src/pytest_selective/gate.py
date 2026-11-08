"""Fail an aggregate CI job unless each prerequisite succeeded or a successful lane plan skipped it.

GitHub reports a job skipped by its `if:` as passing a required check. Make one aggregate
job the required check and run this as its only step, so a skip counts only when the
planner succeeded and said every lane of that job is unaffected. A failed, cancelled or
missing planner, or any other skip, fails the gate. Standard library only: the
`validation-gate` action runs this file directly, without installing anything.
"""

import argparse
import json
import os
import sys
from typing import Any


class GateError(ValueError):
    """The gate's inputs cannot support a decision; the job must fail."""


def admissions(needs: dict[str, Any], planner: str, lane_jobs: dict[str, Any], lanes: Any = None) -> dict[str, bool]:
    """Whether each direct prerequisite had to run. Only an explicit `false` lane makes a job optional."""
    if planner not in needs:
        raise GateError(f"the planner job {planner!r} must be a direct prerequisite (needs:) of the gate")
    if not isinstance(lane_jobs, dict):
        raise GateError("lane-jobs must be a JSON object mapping job ids to lists of lane names")
    planned = needs[planner].get("result") == "success"
    if lanes is None:
        lanes = (needs[planner].get("outputs") or {}).get("lanes", "{}")
    if isinstance(lanes, str):
        try:
            lanes = json.loads(lanes or "{}")
        except json.JSONDecodeError:
            # An unreadable plan cannot prove a skip; every mapped job is then required.
            lanes = {}
    if not isinstance(lanes, dict):
        lanes = {}
    required = dict.fromkeys(needs, True)
    for job, job_lanes in lane_jobs.items():
        if job not in needs or job == planner:
            raise GateError(f"lane-jobs names {job!r}, which is not a direct prerequisite other than the planner")
        if (
            not isinstance(job_lanes, list)
            or not job_lanes
            or not all(isinstance(lane, str) and lane for lane in job_lanes)
        ):
            raise GateError(f"lane-jobs[{job!r}] must be a nonempty list of lane names")
        required[job] = not (planned and all(lanes.get(lane) is False for lane in job_lanes))
    return required


def failures(needs: dict[str, Any], required: dict[str, bool]) -> list[str]:
    """Prerequisites whose result the gate cannot accept."""
    if not needs:
        raise GateError("the gate has no prerequisites; list every job it guards under needs:")
    problems = []
    for job, data in sorted(needs.items()):
        result = (data or {}).get("result")
        if result == "success" or (result == "skipped" and required[job] is False):
            continue
        reason = "required" if required[job] else "optional"
        problems.append(f"{job}: {result or 'no result'} ({reason})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--needs", default=os.environ.get("VALIDATION_NEEDS", ""), help="toJSON(needs)")
    parser.add_argument("--planner", default=os.environ.get("VALIDATION_PLANNER") or "select-tests")
    parser.add_argument("--lane-jobs", default=os.environ.get("VALIDATION_LANE_JOBS") or "{}")
    parser.add_argument(
        "--lanes", default=os.environ.get("VALIDATION_LANES") or None, help="defaults to the planner's `lanes` output"
    )
    args = parser.parse_args(argv)
    try:
        needs = json.loads(args.needs)
        lane_jobs = json.loads(args.lane_jobs)
        if not isinstance(needs, dict):
            raise GateError("needs must be the JSON object from toJSON(needs)")
        required = admissions(needs, args.planner, lane_jobs, args.lanes)
        problems = failures(needs, required)
    except (GateError, json.JSONDecodeError) as error:
        print(f"Validation gate: {error}", file=sys.stderr)
        return 2
    for job in sorted(needs):
        state = "required" if required[job] else "skippable"
        print(f"{job}: {needs[job].get('result')} ({state})")
    if problems:
        print("Validation gate failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print("Validation gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
