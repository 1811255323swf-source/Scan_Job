from datetime import datetime, timedelta, timezone

from models import Job, ScoreResult
from storage import JobStore


def test_store_deduplicates_by_url(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = Job(
        source="test",
        company="Example",
        position="C++ 后端实习",
        url="https://example.com/job/1",
    )
    score = ScoreResult(score=80, level="建议关注", matched_rules=["C++ +20"], penalties=[])

    try:
        assert store.insert(job, score, "analysis")
        assert store.seen(job)
        assert not store.insert(job, score, "analysis")
    finally:
        store.close()


def test_store_tracks_daily_crawl_progress(tmp_path):
    store = JobStore(tmp_path / "jobs.db")

    try:
        assert store.daily_stats("2026-09-29") == {"attempts": 0, "valid_jobs": 0}

        assert store.add_daily_attempt("2026-09-29") == 1
        assert store.add_daily_attempt("2026-09-29") == 2
        assert store.add_daily_valid_jobs("2026-09-29", 3) == 3
        assert store.add_daily_valid_jobs("2026-09-29", 0) == 3

        assert store.daily_stats("2026-09-29") == {"attempts": 2, "valid_jobs": 3}
        assert store.daily_stats("2026-09-30") == {"attempts": 0, "valid_jobs": 0}
    finally:
        store.close()


def test_store_loads_jobs_for_daily_report_retry(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = Job(
        source="test",
        company="Example",
        position="C++ Linux 后端实习",
        location="武汉",
        url="https://example.com/job/retry",
    )
    score = ScoreResult(score=75, level="建议关注", matched_rules=["C++ +20"], penalties=[])

    try:
        assert store.insert(job, score, "retry analysis")
        now = datetime.now(timezone.utc)
        jobs = store.jobs_created_between(now - timedelta(minutes=1), now + timedelta(minutes=1))
        assert len(jobs) == 1
        assert jobs[0].job.url == job.url
        assert jobs[0].score == 75
        assert jobs[0].ai_analysis == "retry analysis"
    finally:
        store.close()
