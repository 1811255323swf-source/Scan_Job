from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analyzer import AIAnalyzer, score_job
from crawler import build_crawlers
from mail.sender import build_markdown_report, send_email, write_report
from models import AnalyzedJob, Job
from settings import load_config
from storage import JobStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="C++ backend internship cloud monitor")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--no-email", action="store_true", help="Generate report without sending email")
    parser.add_argument(
        "--require-email",
        action="store_true",
        help="Fail the run if email is skipped or cannot be sent.",
    )
    parser.add_argument(
        "--force-email",
        action="store_true",
        help="Send the current report even if the daily crawl target is not complete.",
    )
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


def configured_timezone(name: str):
    normalized = (name or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        if normalized in {"Asia/Shanghai", "China", "UTC+8", "UTC+08:00"}:
            return timezone(timedelta(hours=8), "Asia/Shanghai")
        logging.getLogger("main").warning("unknown timezone %s, fallback to UTC", normalized)
        return timezone.utc


def run(config: dict, no_email: bool = False, require_email: bool = False, force_email: bool = False) -> int:
    logger = logging.getLogger("main")
    app_config = config.get("app", {})
    min_score = int(app_config.get("min_score", 50))
    max_jobs = int(app_config.get("max_jobs_per_run", 30))
    max_ai_jobs = int(app_config.get("max_ai_jobs_per_run", 8))
    daily_target_valid_jobs = int(app_config.get("daily_target_valid_jobs", 10))
    max_daily_crawl_attempts = int(app_config.get("max_daily_crawl_attempts", 200))
    max_crawl_attempts_per_run = int(app_config.get("max_crawl_attempts_per_run", max_daily_crawl_attempts))
    crawl_interval_seconds = float(app_config.get("crawl_interval_seconds", 0))
    report_tz = configured_timezone(str(app_config.get("daily_timezone", "Asia/Shanghai")))

    store = JobStore(app_config.get("database_path", "database/jobs.db"))
    analyzer = AIAnalyzer(config)
    analyzed_jobs: list[AnalyzedJob] = []
    ai_count = 0

    try:
        if force_email:
            crawlers = []
            logger.info("force-email requested; skip crawling and send the current report")
        else:
            crawlers = build_crawlers(config)
            logger.info("enabled crawlers: %s", ", ".join(crawler.name for crawler in crawlers) or "none")

        generated_at = datetime.now(report_tz)
        run_date = generated_at.strftime("%Y-%m-%d")
        attempts_this_run = 0

        if not crawlers:
            logger.warning("no enabled crawlers, skip crawl loop")

        while crawlers and len(analyzed_jobs) < max_jobs:
            daily_stats = store.daily_stats(run_date)
            daily_attempts = daily_stats["attempts"]
            daily_valid_jobs = daily_stats["valid_jobs"]

            if daily_valid_jobs >= daily_target_valid_jobs:
                logger.info(
                    "daily target reached: %d/%d valid jobs",
                    daily_valid_jobs,
                    daily_target_valid_jobs,
                )
                break
            if daily_attempts >= max_daily_crawl_attempts:
                logger.info(
                    "daily crawl limit reached: %d/%d attempts",
                    daily_attempts,
                    max_daily_crawl_attempts,
                )
                break
            if attempts_this_run >= max_crawl_attempts_per_run:
                logger.info(
                    "per-run crawl limit reached: %d/%d attempts",
                    attempts_this_run,
                    max_crawl_attempts_per_run,
                )
                break

            attempt_no = store.add_daily_attempt(run_date)
            attempts_this_run += 1
            logger.info(
                "crawl attempt %d/%d for %s, target progress %d/%d",
                attempt_no,
                max_daily_crawl_attempts,
                run_date,
                daily_valid_jobs,
                daily_target_valid_jobs,
            )

            crawled_jobs: list[Job] = []
            for crawler in crawlers:
                jobs = crawler.crawl()
                logger.info("%s fetched %d jobs", crawler.name, len(jobs))
                crawled_jobs.extend(jobs)

            crawled_jobs = unique_jobs(crawled_jobs)
            logger.info("attempt %d unique fetched jobs: %d", attempt_no, len(crawled_jobs))

            new_valid_jobs = 0
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

                new_valid_jobs += 1
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

            daily_valid_jobs = store.add_daily_valid_jobs(run_date, new_valid_jobs)
            logger.info(
                "attempt %d added %d valid jobs, daily progress %d/%d",
                attempt_no,
                new_valid_jobs,
                daily_valid_jobs,
                daily_target_valid_jobs,
            )

            if daily_valid_jobs >= daily_target_valid_jobs:
                break
            if crawl_interval_seconds > 0 and attempts_this_run < max_crawl_attempts_per_run:
                time.sleep(crawl_interval_seconds)

        final_daily_stats = store.daily_stats(run_date)
        daily_complete = (
            final_daily_stats["valid_jobs"] >= daily_target_valid_jobs
            or final_daily_stats["attempts"] >= max_daily_crawl_attempts
        )
        stats = store.stats()
        stats.update(
            {
                "daily_date": run_date,
                "daily_attempts": final_daily_stats["attempts"],
                "daily_max_attempts": max_daily_crawl_attempts,
                "daily_valid_jobs": final_daily_stats["valid_jobs"],
                "daily_target_valid_jobs": daily_target_valid_jobs,
                "attempts_this_run": attempts_this_run,
                "daily_complete": daily_complete or force_email,
            }
        )

        generated_at = datetime.now(report_tz)
        report = build_markdown_report(analyzed_jobs, generated_at, config, stats)
        report_path = write_report(app_config.get("report_dir", "reports"), report)
        logger.info("report written to %s", report_path)

        email_sent = False
        if no_email:
            logger.info("email skipped by --no-email")
            if require_email and (daily_complete or force_email):
                logger.error("--require-email cannot be used with --no-email after the daily crawl is complete")
                return 2
        elif daily_complete or force_email:
            subject_prefix = config.get("email", {}).get("subject_prefix", "C++后端实习机会")
            subject = f"{subject_prefix} - {generated_at.strftime('%Y-%m-%d')}"
            email_sent = send_email(subject, report, config)
        else:
            logger.info(
                "email postponed until daily completion: %d/%d valid jobs, %d/%d attempts",
                final_daily_stats["valid_jobs"],
                daily_target_valid_jobs,
                final_daily_stats["attempts"],
                max_daily_crawl_attempts,
            )

        if require_email and (daily_complete or force_email) and not email_sent:
            logger.error("email was required but was not sent")
            return 2

        logger.info("new recommended jobs: %d", len(analyzed_jobs))
        return 0
    finally:
        store.close()


def main() -> int:
    args = parse_args()
    setup_logging()
    config = load_config(Path(args.config))
    return run(config, no_email=args.no_email, require_email=args.require_email, force_email=args.force_email)


if __name__ == "__main__":
    raise SystemExit(main())

