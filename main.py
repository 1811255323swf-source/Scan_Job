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
        help="Crawl and send today's accumulated report even if the daily target is not complete.",
    )
    parser.add_argument(
        "--email-only",
        action="store_true",
        help="Resend reports/latest.md without crawling.",
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


def write_email_sent_flag(report_dir: str | Path, run_date: str) -> Path:
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    flag_path = path / f"email_sent_{run_date}.flag"
    flag_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return flag_path


def run(
    config: dict,
    no_email: bool = False,
    require_email: bool = False,
    force_email: bool = False,
    email_only: bool = False,
) -> int:
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
        generated_at = datetime.now(report_tz)
        run_date = generated_at.strftime("%Y-%m-%d")

        if email_only:
            crawlers = []
            report_path = Path(app_config.get("report_dir", "reports")) / "latest.md"
            if not report_path.is_file():
                logger.error("cannot resend email: %s does not exist", report_path)
                return 2
            report = report_path.read_text(encoding="utf-8")
            subject_prefix = config.get("email", {}).get("subject_prefix", "C++后端实习机会")
            subject = f"{subject_prefix} - {run_date}（补发）"
            email_sent = False if no_email else send_email(subject, report, config)
            if email_sent:
                write_email_sent_flag(app_config.get("report_dir", "reports"), run_date)
                logger.info("latest report resent successfully")
                return 0
            return 2 if require_email else 0
        else:
            crawlers = build_crawlers(config)
            logger.info("enabled crawlers: %s", ", ".join(crawler.name for crawler in crawlers) or "none")
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
            if daily_attempts >= max_daily_crawl_attempts and not force_email:
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
            excluded_jobs = 0
            below_score_jobs = 0
            duplicate_jobs = 0
            sample_rejections: list[str] = []
            for job in crawled_jobs:
                score_result = score_job(job, config)
                if score_result.excluded:
                    excluded_jobs += 1
                    if len(sample_rejections) < 5:
                        sample_rejections.append(
                            f"excluded score={score_result.score} title={job.position[:80]}"
                        )
                    continue
                if score_result.score < min_score:
                    below_score_jobs += 1
                    if len(sample_rejections) < 5:
                        sample_rejections.append(
                            f"below-score score={score_result.score} title={job.position[:80]}"
                        )
                    continue
                if store.seen(job):
                    duplicate_jobs += 1
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
            logger.info(
                "attempt %d filter summary: excluded=%d below_score=%d duplicates=%d added=%d",
                attempt_no,
                excluded_jobs,
                below_score_jobs,
                duplicate_jobs,
                new_valid_jobs,
            )
            for rejection in sample_rejections:
                logger.info("filter sample: %s", rejection)

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
        day_start = generated_at.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        daily_jobs = store.jobs_created_between(day_start, day_end, limit=max_jobs)
        target_locations = list(config.get("user_profile", {}).get("target_locations", []))

        def location_rank(analyzed: AnalyzedJob) -> int:
            for index, location in enumerate(target_locations):
                if location and location in analyzed.job.location:
                    return index
            return len(target_locations)

        daily_jobs.sort(key=lambda item: (location_rank(item), -item.score))
        report = build_markdown_report(daily_jobs, generated_at, config, stats)
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
            if email_sent:
                flag_path = write_email_sent_flag(app_config.get("report_dir", "reports"), run_date)
                logger.info("email sent flag written to %s", flag_path)
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
    return run(
        config,
        no_email=args.no_email,
        require_email=args.require_email,
        force_email=args.force_email,
        email_only=args.email_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
