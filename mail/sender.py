from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

from models import AnalyzedJob
from settings import as_bool


LOGGER = logging.getLogger("mail.sender")


def build_markdown_report(
    analyzed_jobs: list[AnalyzedJob],
    generated_at: datetime,
    config: dict,
    stats: dict | None = None,
) -> str:
    stats = stats or {}
    lines = [
        "# C++后端实习机会",
        "",
        f"- 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 统计日期：{stats.get('daily_date', generated_at.strftime('%Y-%m-%d'))}",
        f"- 新增推荐：{len(analyzed_jobs)} 个",
        f"- 历史岗位：{stats.get('total_jobs', 0)} 个",
        (
            "- 今日累计有效岗位："
            f"{stats.get('daily_valid_jobs', 0)} / {stats.get('daily_target_valid_jobs', 10)} 个"
        ),
        (
            "- 今日累计爬取轮次："
            f"{stats.get('daily_attempts', 0)} / {stats.get('daily_max_attempts', 200)} 次"
        ),
        f"- 本次爬取轮次：{stats.get('attempts_this_run', 0)} 次",
        "",
    ]

    if not analyzed_jobs:
        lines.extend(["今天暂未发现新的高匹配岗位。", ""])
        return "\n".join(lines)

    for index, analyzed in enumerate(analyzed_jobs, start=1):
        job = analyzed.job
        lines.extend(
            [
                f"## {index}. {job.company} - {job.position}",
                "",
                f"- 地点：{job.location or '未知'}",
                f"- 来源：{job.source}",
                f"- 发布时间：{job.published_at or '未知'}",
                f"- 匹配度：{analyzed.score} / {analyzed.level}",
                f"- 命中规则：{'; '.join(analyzed.matched_rules) or '无'}",
                f"- 扣分项：{'; '.join(analyzed.penalties) or '无'}",
                f"- 链接：{job.url or job.dedupe_key}",
                "",
                "### 岗位要求",
                "",
                job.requirements or job.description or "暂无详情",
                "",
                "### AI/规则分析",
                "",
                analyzed.ai_analysis,
                "",
            ]
        )
    return "\n".join(lines)


def write_report(report_dir: str | Path, markdown: str) -> Path:
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    latest = path / "latest.md"
    latest.write_text(markdown, encoding="utf-8")
    return latest


def _markdown_to_basic_html(markdown: str) -> str:
    escaped = escape(markdown)
    return "<html><body><pre style=\"white-space:pre-wrap;font-family:Arial,sans-serif\">" + escaped + "</pre></body></html>"


def send_email(subject: str, markdown: str, config: dict) -> bool:
    email_config = config.get("email", {})
    if not as_bool(email_config.get("enabled", True)):
        LOGGER.info("email disabled by config")
        return False

    smtp_host = str(email_config.get("smtp_host", "") or "")
    smtp_port = int(email_config.get("smtp_port", 587) or 587)
    smtp_use_ssl_raw = str(email_config.get("smtp_use_ssl", "") or "").strip()
    smtp_use_ssl = as_bool(smtp_use_ssl_raw) if smtp_use_ssl_raw else smtp_port == 465
    smtp_starttls = as_bool(email_config.get("smtp_starttls", True))
    username = str(email_config.get("smtp_username", "") or "")
    password = str(email_config.get("smtp_password", "") or "")
    from_addr = str(email_config.get("from_addr", "") or username)
    to_addr = str(email_config.get("to_addr", "") or "")

    missing = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": username,
            "SMTP_PASSWORD": password,
            "EMAIL_FROM": from_addr,
            "EMAIL_TO": to_addr,
        }.items()
        if not value
    ]
    if missing:
        LOGGER.warning("email skipped, missing config: %s", ", ".join(missing))
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(markdown)
    message.add_alternative(_markdown_to_basic_html(markdown), subtype="html")

    smtp_class = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=30) as smtp:
        if not smtp_use_ssl and smtp_starttls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    LOGGER.info("email sent to %s", to_addr)
    return True

