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

