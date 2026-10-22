"""Read-only GitHub Actions timing export. Requires authenticated gh; no billing estimates."""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def summarize(run: dict, jobs: list[dict]) -> dict:
    """Freeze one successful attempt; skipped jobs consume no measured runner time."""
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("only completed successful runs are comparable")
    if not jobs or any(j["status"] != "completed" or j["conclusion"] not in {"success", "skipped"} for j in jobs):
        raise ValueError("all jobs must be completed successfully or explicitly skipped")
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
        "created_at": run["created_at"],
        "completed_at": finished.isoformat(),
        "elapsed_seconds": (finished - timestamp(run["created_at"])).total_seconds(),
        "runner_seconds": sum(durations),
        "executed_jobs": len(executed),
        "skipped_job_records": len(jobs) - len(executed),
        "jobs": [{key: j[key] for key in ("id", "name", "conclusion", "started_at", "completed_at")} for j in jobs],
    }


def api(path: str) -> dict:
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def collect(repository: str, run_id: int) -> dict:
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
    return summarize(run, jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="owner/repo")
    parser.add_argument("runs", type=int, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [collect(args.repository, run) for run in args.runs]
    if len({report["head_sha"] for report in reports}) != 1:
        raise ValueError("matched comparisons must use the same head SHA")
    args.output.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
