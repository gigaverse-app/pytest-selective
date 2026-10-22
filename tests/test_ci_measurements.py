import pytest

from scripts.measure_ci_runs import summarize


def records():
    run = {
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "example/repo"},
        "id": 1,
        "html_url": "https://github.com/example/repo/actions/runs/1",
        "name": "CI",
        "head_sha": "abc",
        "run_attempt": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    jobs = [
        {
            "id": 1,
            "name": "tests",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-01-01T00:00:10Z",
            "completed_at": "2026-01-01T00:00:30Z",
        },
        {
            "id": 2,
            "name": "lint",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-01-01T00:00:05Z",
            "completed_at": "2026-01-01T00:00:15Z",
        },
        # GitHub sometimes reports reversed timestamps for skipped job records.
        {
            "id": 3,
            "name": "live",
            "status": "completed",
            "conclusion": "skipped",
            "started_at": "2026-01-01T00:00:06Z",
            "completed_at": "2026-01-01T00:00:05Z",
        },
    ]
    return run, jobs


def test_elapsed_includes_queue_but_runner_time_excludes_skipped_records():
    report = summarize(*records())
    assert report["elapsed_seconds"] == 30
    assert report["runner_seconds"] == 30
    assert report["executed_jobs"] == 2
    assert report["skipped_job_records"] == 1


@pytest.mark.parametrize(
    "status,conclusion", [("in_progress", None), ("completed", "failure"), ("completed", "cancelled")]
)
def test_incomplete_or_failed_controls_cannot_claim_savings(status, conclusion):
    run, jobs = records()
    run.update(status=status, conclusion=conclusion)
    with pytest.raises(ValueError, match="successful"):
        summarize(run, jobs)


def test_pending_rerun_jobs_cannot_reuse_an_old_success_summary():
    run, jobs = records()
    jobs[0].update(status="in_progress", conclusion=None, completed_at=None)
    with pytest.raises(ValueError, match="all jobs"):
        summarize(run, jobs)
