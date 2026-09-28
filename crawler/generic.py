from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from crawler.base import BaseCrawler
from crawler.http import fetch_text
from models import Job, clean_text


JOB_TITLE_HINTS = ["实习", "intern", "校招", "招聘", "开发", "工程师", "后端", "服务端", "Linux", "C++"]


def _text_or_empty(node) -> str:
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def _attr_or_text(item, selector: str | None, attr: str | None = None) -> str:
    if not selector:
        return ""
    node = item.select_one(selector)
    if not node:
        return ""
    if attr:
        return clean_text(node.get(attr, ""))
    return _text_or_empty(node)


def _guess_location(text: str, locations: list[str]) -> str:
    for location in locations:
        if location and location in text:
            return location
    common_locations = ["武汉", "北京", "上海", "深圳", "广州", "杭州", "南京", "成都", "远程"]
    for location in common_locations:
        if location in text:
            return location
    return ""


def _looks_like_job(text: str, positive_keywords: list[str]) -> bool:
    if not text or len(text) > 180:
        return False
    lowered = text.casefold()
    has_title_hint = any(hint.casefold() in lowered for hint in JOB_TITLE_HINTS)
    has_positive = any(keyword.casefold() in lowered for keyword in positive_keywords)
    return has_title_hint or has_positive


def extract_jobs_from_html(
    html: str,
    page_url: str,
    source_name: str,
    positive_keywords: list[str],
    target_locations: list[str],
    max_items: int = 80,
) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    jobs: list[Job] = []
    seen_links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = _text_or_empty(anchor)
        if not _looks_like_job(title, positive_keywords):
            continue

        parent = anchor.find_parent(["li", "article", "section", "div"]) or anchor.parent
        context = _text_or_empty(parent)[:1200]
        link = urljoin(page_url, anchor.get("href", ""))
        if link in seen_links:
            continue
        seen_links.add(link)
        if not _looks_like_job(f"{title} {context}", positive_keywords):
            continue

        jobs.append(
            Job(
                source=source_name,
                company=source_name,
                position=title,
                location=_guess_location(context, target_locations),
                description=context,
                requirements=context,
                url=link,
            )
        )
        if len(jobs) >= max_items:
            break
    return jobs


class GenericCrawler(BaseCrawler):
    def crawl(self) -> list[Job]:
        timeout = int(self.config.get("app", {}).get("request_timeout_seconds", 15))
        urls = self._build_urls()
        jobs: list[Job] = []
        for url in urls:
            try:
                html = fetch_text(url, timeout=timeout)
                jobs.extend(self._parse_html(html, url))
            except Exception as exc:  # noqa: BLE001 - crawler failures should not kill the run
                self.logger.warning("failed to crawl %s: %s", url, exc.__class__.__name__)
        return self._unique(jobs)

    def _build_urls(self) -> list[str]:
        urls = list(self.source_config.get("urls", []))
        url_template = self.source_config.get("url_template")
        if url_template:
            keywords = self.source_config.get("keywords", [])
            locations = self.source_config.get("locations", [""])
            max_pages = int(self.source_config.get("max_pages", 1))
            for keyword in keywords:
                for location in locations:
                    for page in range(1, max_pages + 1):
                        urls.append(
                            url_template.format(
                                keyword=quote_plus(keyword),
                                location=quote_plus(location),
                                page=page,
                            )
                        )
        return urls

    def _parse_html(self, html: str, page_url: str) -> list[Job]:
        item_selector = self.source_config.get("item_selector")
        fields = self.source_config.get("fields", {})
        if item_selector:
            return self._parse_with_selectors(html, page_url, item_selector, fields)

        keywords = self.config.get("keywords", {}).get("positive", [])
        locations = self.config.get("user_profile", {}).get("target_locations", [])
        max_items = int(self.source_config.get("max_items", 80))
        return extract_jobs_from_html(html, page_url, self.name, keywords, locations, max_items=max_items)

    def _parse_with_selectors(self, html: str, page_url: str, item_selector: str, fields: dict) -> list[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[Job] = []
        for item in soup.select(item_selector):
            link_selector = fields.get("url") or fields.get("link")
            relative_url = _attr_or_text(item, link_selector, "href") if link_selector else ""
            description = _attr_or_text(item, fields.get("description")) or _text_or_empty(item)
            jobs.append(
                Job(
                    source=self.name,
                    company=_attr_or_text(item, fields.get("company")) or self.name,
                    position=_attr_or_text(item, fields.get("position")) or _text_or_empty(item)[:80],
                    location=_attr_or_text(item, fields.get("location")),
                    published_at=_attr_or_text(item, fields.get("published_at")),
                    education=_attr_or_text(item, fields.get("education")),
                    graduation_year=_attr_or_text(item, fields.get("graduation_year")),
                    internship_period=_attr_or_text(item, fields.get("internship_period")),
                    description=description,
                    requirements=_attr_or_text(item, fields.get("requirements")) or description,
                    url=urljoin(page_url, relative_url),
                )
            )
        return jobs

