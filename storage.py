from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import Job, ScoreResult


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
"""


class JobStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def seen(self, job: Job) -> bool:
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
            return True
        except sqlite3.IntegrityError:
            return False

    def stats(self) -> dict[str, Any]:
        cursor = self.connection.execute("SELECT COUNT(*) AS total FROM jobs")
        total = cursor.fetchone()["total"]
        return {"total_jobs": total}

