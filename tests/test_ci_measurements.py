import pytest

from scripts.measure_ci_runs import compare, summarize


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
    with pytest.raises(ValueError, match="comparable"):
        summarize(run, jobs)


def test_pending_rerun_jobs_cannot_reuse_an_old_success_summary():
    run, jobs = records()
    jobs[0].update(status="in_progress", conclusion=None, completed_at=None)
    with pytest.raises(ValueError, match="all jobs"):
        summarize(run, jobs)


def test_an_expected_job_failure_counts_as_executed_work():
    run, jobs = records()
    run["conclusion"] = "failure"
    jobs[0]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="comparable"):
        summarize(run, jobs)
    report = summarize(run, jobs, frozenset({"tests"}))
    assert report["expected_failures"] == ["tests"]
    assert report["runner_seconds"] == 30


def test_expecting_one_failure_does_not_excuse_another():
    run, jobs = records()
    run["conclusion"] = "failure"
    jobs[0]["conclusion"] = "failure"
    jobs[1]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="all jobs"):
        summarize(run, jobs, frozenset({"tests"}))


def other_workflow(run_id, name, created, start, end, head="abc"):
    run, jobs = records()
    run.update(id=run_id, name=name, created_at=created, head_sha=head)
    jobs = [dict(jobs[0], id=run_id * 10, started_at=start, completed_at=end)]
    return summarize(run, jobs)


def test_a_side_adds_runner_time_across_workflows_and_spans_their_elapsed_time():
    selected = [summarize(*records())]
    full = [
        summarize(*records()),
        other_workflow(2, "Docs", "2026-01-01T00:00:02Z", "2026-01-01T00:00:20Z", "2026-01-01T00:01:02Z"),
    ]
    result = compare(selected, full)
    assert result["full"]["workflows"] == ["CI", "Docs"]
    assert result["full"]["runner_seconds"] == 30 + 42
    assert result["full"]["elapsed_seconds"] == 62
    assert result["runner_seconds_saved"] == 42
    assert result["runner_seconds_reduction_percent"] == 58.3
    assert result["elapsed_seconds_saved"] == 32


def test_sides_must_share_one_head_and_hold_one_run_per_workflow():
    first = summarize(*records())
    moved = other_workflow(2, "Docs", "2026-01-01T00:00:02Z", "2026-01-01T00:00:20Z", "2026-01-01T00:01:02Z", "def")
    with pytest.raises(ValueError, match="same head"):
        compare([first], [moved])
    with pytest.raises(ValueError, match="one run per workflow"):
        compare([first], [first, dict(first, run_id=9)])
