"""Read-only GitHub Actions timing export. Requires authenticated gh; no billing estimates.

Pass run ids to export each run, or `--selected IDS --full IDS` to compare two sides of one
head. A side may hold several workflow runs (for example CI and Docs triggered by the same
push): runner-seconds add up and elapsed runs from the first run's creation to the last job's
completion. `--expected-failure JOB` accepts that job's deliberate failure (a probe) as executed
work instead of rejecting the run; any other failed, cancelled or unfinished job still does.

The sides may come from different events. A `pull_request` run records the branch head as its
`head_sha` (although it checks out the merge commit), so a `workflow_dispatch` or `push` run on
that branch is the same head: the usual full control beside a selected pull-request run.
"""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def summarize(run: dict, jobs: list[dict], expected_failures: frozenset[str] = frozenset()) -> dict:
    """Freeze one completed attempt; skipped jobs consume no measured runner time."""
    failed = {j["name"] for j in jobs if j["status"] == "completed" and j["conclusion"] == "failure"}
    accepted = failed & expected_failures
    if run["status"] != "completed" or not (
        run["conclusion"] == "success" or (run["conclusion"] == "failure" and accepted)
    ):
        raise ValueError("only completed successful runs, or runs failing only expected jobs, are comparable")
    allowed = {"success", "skipped"}
    if not jobs or any(
        j["status"] != "completed" or not (j["conclusion"] in allowed or j["name"] in accepted) for j in jobs
    ):
        raise ValueError("all jobs must be completed successfully, explicitly skipped, or expected failures")
    executed = [j for j in jobs if j["conclusion"] != "skipped"]
    if not executed:
        raise ValueError("a fully skipped workflow is not a successful executed control")
    durations = [(timestamp(j["completed_at"]) - timestamp(j["started_at"])).total_seconds() for j in executed]
    if any(duration < 0 for duration in durations):
        raise ValueError("executed-job timestamps must be ordered")
    finished = max(timestamp(j["completed_at"]) for j in executed)
    return {
        "repository": run["repository"]["full_name"],
        "run_id": run["id"],
        "url": run["html_url"],
        "workflow": run["name"],
        "head_sha": run["head_sha"],
        "attempt": run["run_attempt"],
        "conclusion": run["conclusion"],
        "expected_failures": sorted(accepted),
        "created_at": run["created_at"],
        "completed_at": finished.isoformat(),
        "elapsed_seconds": (finished - timestamp(run["created_at"])).total_seconds(),
        "runner_seconds": sum(durations),
        "executed_jobs": len(executed),
        "skipped_job_records": len(jobs) - len(executed),
        "jobs": [{key: j[key] for key in ("id", "name", "conclusion", "started_at", "completed_at")} for j in jobs],
    }


def same_head(reports: list[dict]) -> str:
    heads = {report["head_sha"] for report in reports}
    if len(heads) != 1:
        raise ValueError("matched comparisons must use the same head SHA")
    return heads.pop()


def side(reports: list[dict]) -> dict:
    """One side of a comparison: every workflow run the same event started for one head."""
    if not reports:
        raise ValueError("each side needs at least one run")
    workflows = [report["workflow"] for report in reports]
    if len(set(workflows)) != len(workflows):
        raise ValueError("a side holds at most one run per workflow; compare reruns as separate sides")
    start = min(timestamp(report["created_at"]) for report in reports)
    finish = max(timestamp(report["completed_at"]) for report in reports)
    return {
        "head_sha": same_head(reports),
        "workflows": sorted(workflows),
        "elapsed_seconds": (finish - start).total_seconds(),
        "runner_seconds": sum(report["runner_seconds"] for report in reports),
        "executed_jobs": sum(report["executed_jobs"] for report in reports),
        "skipped_job_records": sum(report["skipped_job_records"] for report in reports),
        "runs": reports,
    }


def compare(selected: list[dict], full: list[dict]) -> dict:
    same_head([*selected, *full])
    # A workflow that one side did not start at all is a real difference; both lists are reported.
    chosen, control = side(selected), side(full)
    saved = control["runner_seconds"] - chosen["runner_seconds"]
    return {
        "selected": chosen,
        "full": control,
        "runner_seconds_saved": saved,
        "runner_seconds_reduction_percent": round(100 * saved / control["runner_seconds"], 1),
        "elapsed_seconds_saved": control["elapsed_seconds"] - chosen["elapsed_seconds"],
    }


def api(path: str) -> dict:
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def collect(repository: str, run_id: int, expected_failures: frozenset[str] = frozenset()) -> dict:
    run = api(f"repos/{repository}/actions/runs/{run_id}")
    # A rerun can start while querying. Address the captured attempt explicitly.
    path = f"repos/{repository}/actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs"
    jobs = []
    page = 1
    while True:
        result = api(f"{path}?per_page=100&page={page}")
        jobs.extend(result["jobs"])
        if len(jobs) >= result["total_count"]:
            break
        if not result["jobs"]:
            raise ValueError("incomplete job pagination")
        page += 1
    return summarize(run, jobs, expected_failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository", help="owner/repo")
    parser.add_argument("runs", type=int, nargs="*", help="run ids to export, all on one head")
    parser.add_argument("--selected", type=int, nargs="+", default=[], help="run ids of the selected side")
    parser.add_argument("--full", type=int, nargs="+", default=[], help="run ids of the full-control side")
    parser.add_argument("--expected-failure", action="append", default=[], metavar="JOB", help="job name")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = frozenset(args.expected_failure)
    if bool(args.selected) != bool(args.full) or bool(args.runs) == bool(args.selected):
        parser.error("pass either run ids, or both --selected and --full")
    if args.runs:
        reports = [collect(args.repository, run, expected) for run in args.runs]
        same_head(reports)
        result: list[dict] | dict = reports
    else:
        result = compare(
            [collect(args.repository, run, expected) for run in args.selected],
            [collect(args.repository, run, expected) for run in args.full],
        )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
