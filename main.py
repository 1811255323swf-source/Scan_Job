from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from analyzer import AIAnalyzer, score_job
from crawler import build_crawlers
from mail.sender import build_markdown_report, send_email, write_report
from models import AnalyzedJob, Job
from settings import as_bool, load_config
from storage import JobStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="C++ backend internship cloud monitor")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--no-email", action="store_true", help="Generate report without sending email")
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def unique_jobs(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    result: list[Job] = []
    for job in jobs:
        key = job.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


def run(config: dict, no_email: bool = False) -> int:
    logger = logging.getLogger("main")
    app_config = config.get("app", {})
    min_score = int(app_config.get("min_score", 50))
    max_jobs = int(app_config.get("max_jobs_per_run", 30))
    max_ai_jobs = int(app_config.get("max_ai_jobs_per_run", 8))

    store = JobStore(app_config.get("database_path", "database/jobs.db"))
    analyzer = AIAnalyzer(config)
    analyzed_jobs: list[AnalyzedJob] = []
    ai_count = 0

    try:
        crawlers = build_crawlers(config)
        logger.info("enabled crawlers: %s", ", ".join(crawler.name for crawler in crawlers) or "none")

        crawled_jobs: list[Job] = []
        for crawler in crawlers:
            jobs = crawler.crawl()
            logger.info("%s fetched %d jobs", crawler.name, len(jobs))
            crawled_jobs.extend(jobs)

        crawled_jobs = unique_jobs(crawled_jobs)
        logger.info("total unique fetched jobs: %d", len(crawled_jobs))

        for job in crawled_jobs:
            score_result = score_job(job, config)
            if score_result.excluded or score_result.score < min_score:
                continue
            if store.seen(job):
                continue

            if analyzer.enabled() and ai_count < max_ai_jobs:
                ai_analysis = analyzer.analyze(job, score_result)
                ai_count += 1
            else:
                ai_analysis = analyzer.fallback(job, score_result)

            inserted = store.insert(job, score_result, ai_analysis)
            if not inserted:
                continue

            analyzed_jobs.append(
                AnalyzedJob(
                    job=job,
                    score=score_result.score,
                    level=score_result.level,
                    matched_rules=score_result.matched_rules,
                    penalties=score_result.penalties,
                    ai_analysis=ai_analysis,
                )
            )
            if len(analyzed_jobs) >= max_jobs:
                break

        generated_at = datetime.now()
        report = build_markdown_report(analyzed_jobs, generated_at, config, store.stats())
        report_path = write_report(app_config.get("report_dir", "reports"), report)
        logger.info("report written to %s", report_path)

        send_empty_report = as_bool(app_config.get("send_empty_report", True))
        if no_email:
            logger.info("email skipped by --no-email")
        elif analyzed_jobs or send_empty_report:
            subject_prefix = config.get("email", {}).get("subject_prefix", "C++后端实习机会")
            subject = f"{subject_prefix} - {generated_at.strftime('%Y-%m-%d')}"
            send_email(subject, report, config)

        logger.info("new recommended jobs: %d", len(analyzed_jobs))
        return 0
    finally:
        store.close()


def main() -> int:
    args = parse_args()
    setup_logging()
    config = load_config(Path(args.config))
    return run(config, no_email=args.no_email)


if __name__ == "__main__":
    raise SystemExit(main())

