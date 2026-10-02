from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from models import AnalyzedJob, Job, ScoreResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
    id INTEGER PRIMARY KEY,
    company TEXT,
    position TEXT,
    location TEXT,
    published_at TEXT,
    education TEXT,
    graduation_year TEXT,
    internship_period TEXT,
    description TEXT,
    requirements TEXT,
    source TEXT,
    url TEXT UNIQUE,
    score INTEGER,
    level TEXT,
    score_detail TEXT,
    ai_analysis TEXT,
    create_time DATETIME
);

CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_create_time ON jobs(create_time);

CREATE TABLE IF NOT EXISTS daily_crawl_stats(
    run_date TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0,
    valid_jobs INTEGER NOT NULL DEFAULT 0,
    updated_at DATETIME
);
"""


class JobStore:
    def __init__(self, database_path: str | Path, seen_hashes_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_hashes_path = Path(seen_hashes_path) if seen_hashes_path else None
        self.seen_hashes: set[str] = set()
        if self.seen_hashes_path and self.seen_hashes_path.is_file():
            self.seen_hashes = {
                line.strip()
                for line in self.seen_hashes_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def seen(self, job: Job) -> bool:
        if self._seen_hash(job) in self.seen_hashes:
            return True
        cursor = self.connection.execute(
            "SELECT 1 FROM jobs WHERE url = ? LIMIT 1",
            (job.dedupe_key,),
        )
        return cursor.fetchone() is not None

    def insert(self, job: Job, score_result: ScoreResult, ai_analysis: str) -> bool:
        score_detail = json.dumps(
            {
                "matched_rules": score_result.matched_rules,
                "penalties": score_result.penalties,
                "excluded": score_result.excluded,
            },
            ensure_ascii=False,
        )
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.connection.execute(
                """
                INSERT INTO jobs(
                    company, position, location, published_at, education,
                    graduation_year, internship_period, description, requirements,
                    source, url, score, level, score_detail, ai_analysis, create_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.company,
                    job.position,
                    job.location,
                    job.published_at,
                    job.education,
                    job.graduation_year,
                    job.internship_period,
                    job.description,
                    job.requirements,
                    job.source,
                    job.dedupe_key,
                    score_result.score,
                    score_result.level,
                    score_detail,
                    ai_analysis,
                    now,
                ),
            )
            self.connection.commit()
            self._remember_seen(job)
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def _seen_hash(job: Job) -> str:
        return sha256(job.dedupe_key.encode("utf-8")).hexdigest()

    def _remember_seen(self, job: Job) -> None:
        if self.seen_hashes_path is None:
            return
        digest = self._seen_hash(job)
        if digest in self.seen_hashes:
            return
        self.seen_hashes.add(digest)
        self.seen_hashes_path.parent.mkdir(parents=True, exist_ok=True)
        with self.seen_hashes_path.open("a", encoding="utf-8") as file:
            file.write(f"{digest}\n")

    def daily_stats(self, run_date: str) -> dict[str, int]:
        cursor = self.connection.execute(
            """
            SELECT attempts, valid_jobs
            FROM daily_crawl_stats
            WHERE run_date = ?
            """,
            (run_date,),
        )
        row = cursor.fetchone()
        if row is None:
            return {"attempts": 0, "valid_jobs": 0}
        return {"attempts": int(row["attempts"]), "valid_jobs": int(row["valid_jobs"])}

    def add_daily_attempt(self, run_date: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO daily_crawl_stats(run_date, attempts, valid_jobs, updated_at)
            VALUES (?, 1, 0, ?)
            ON CONFLICT(run_date) DO UPDATE SET
                attempts = attempts + 1,
                updated_at = excluded.updated_at
            """,
            (run_date, now),
        )
        self.connection.commit()
        return self.daily_stats(run_date)["attempts"]

    def add_daily_valid_jobs(self, run_date: str, amount: int) -> int:
        if amount <= 0:
            return self.daily_stats(run_date)["valid_jobs"]

        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO daily_crawl_stats(run_date, attempts, valid_jobs, updated_at)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(run_date) DO UPDATE SET
                valid_jobs = valid_jobs + excluded.valid_jobs,
                updated_at = excluded.updated_at
            """,
            (run_date, amount, now),
        )
        self.connection.commit()
        return self.daily_stats(run_date)["valid_jobs"]

    def stats(self) -> dict[str, Any]:
        cursor = self.connection.execute("SELECT COUNT(*) AS total FROM jobs")
        total = cursor.fetchone()["total"]
        return {"total_jobs": total}

    def jobs_created_between(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 100,
    ) -> list[AnalyzedJob]:
        """Return jobs inserted in a UTC time window for daily report retries."""
        cursor = self.connection.execute(
            """
            SELECT company, position, location, published_at, education,
                   graduation_year, internship_period, description, requirements,
                   source, url, score, level, score_detail, ai_analysis
            FROM jobs
            WHERE create_time >= ? AND create_time < ?
            ORDER BY score DESC, create_time DESC
            LIMIT ?
            """,
            (start_time.astimezone(timezone.utc).isoformat(), end_time.astimezone(timezone.utc).isoformat(), limit),
        )

        result: list[AnalyzedJob] = []
        for row in cursor.fetchall():
            detail = json.loads(row["score_detail"] or "{}")
            job = Job(
                source=row["source"],
                company=row["company"],
                position=row["position"],
                location=row["location"],
                published_at=row["published_at"],
                education=row["education"],
                graduation_year=row["graduation_year"],
                internship_period=row["internship_period"],
                description=row["description"],
                requirements=row["requirements"],
                url=row["url"],
            )
            result.append(
                AnalyzedJob(
                    job=job,
                    score=int(row["score"]),
                    level=row["level"],
                    matched_rules=list(detail.get("matched_rules", [])),
                    penalties=list(detail.get("penalties", [])),
                    ai_analysis=row["ai_analysis"] or "",
                )
            )
        return result
