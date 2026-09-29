from datetime import datetime

from models import Job
from storage import JobStore

import main as monitor


class FakeCrawler:
    name = "fake"

    def __init__(self, batches):
        self.batches = list(batches)

    def crawl(self):
        if not self.batches:
            return []
        return self.batches.pop(0)


def test_run_continues_until_daily_target(monkeypatch, tmp_path):
    crawler = FakeCrawler(
        [
            [
                Job(
                    source="fake",
                    company="A",
                    position="C++ Linux 后端实习",
                    location="武汉",
                    requirements="Socket epoll 网络编程",
                    url="https://example.com/a",
                )
            ],
            [
                Job(
                    source="fake",
                    company="B",
                    position="C++ Linux 后端实习",
                    location="武汉",
                    requirements="Socket epoll 网络编程",
                    url="https://example.com/b",
                )
            ],
            [],
        ]
    )
    monkeypatch.setattr(monitor, "build_crawlers", lambda config: [crawler])

    config = {
        "app": {
            "database_path": str(tmp_path / "jobs.db"),
            "report_dir": str(tmp_path / "reports"),
            "min_score": 50,
            "max_jobs_per_run": 30,
            "max_ai_jobs_per_run": 0,
            "daily_target_valid_jobs": 2,
            "max_daily_crawl_attempts": 5,
            "max_crawl_attempts_per_run": 5,
            "crawl_interval_seconds": 0,
            "send_empty_report": False,
        },
        "ai": {"provider": "disabled"},
        "keywords": {"positive": ["C++", "Linux", "后端", "Socket", "epoll"], "negative": ["前端"]},
        "user_profile": {"target_locations": ["武汉"], "graduation_year": "2028"},
        "scoring": {
            "rules": [
                {"name": "C++", "keywords": ["C++"], "score": 20},
                {"name": "Linux", "keywords": ["Linux"], "score": 20},
                {"name": "Socket", "keywords": ["Socket"], "score": 20},
                {"name": "epoll", "keywords": ["epoll"], "score": 10},
                {"name": "后端", "keywords": ["后端"], "score": 15},
            ],
            "location_score": 15,
            "graduation_score": 10,
            "non_target_penalty": -30,
            "negative_keyword_penalty": -30,
            "internship_conflict_penalty": -10,
        },
    }

    assert monitor.run(config, no_email=True) == 0

    store = JobStore(tmp_path / "jobs.db")
    try:
        run_date = datetime.now(monitor.configured_timezone("Asia/Shanghai")).strftime("%Y-%m-%d")
        daily_stats = store.daily_stats(run_date)
        assert daily_stats["attempts"] == 2
        assert daily_stats["valid_jobs"] == 2
        assert store.stats()["total_jobs"] == 2
    finally:
        store.close()
