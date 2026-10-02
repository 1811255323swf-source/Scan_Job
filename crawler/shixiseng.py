from __future__ import annotations

import html as html_module
import re
from io import BytesIO
from urllib.parse import quote_plus, urljoin

import requests
from fontTools.ttLib import TTFont

from crawler.generic import GenericCrawler
from crawler.http import DEFAULT_HEADERS


FONT_URL_PATTERN = re.compile(r"@font-face\s*\{.*?src:\s*url\(([^)]+)\)", re.DOTALL)
GLYPH_NAME_PATTERN = re.compile(r"uni([0-9A-Fa-f]{2,6})$")


def _font_translation(font_bytes: bytes) -> dict[int, int]:
    font = TTFont(BytesIO(font_bytes))
    translation: dict[int, int] = {}
    for table in font["cmap"].tables:
        for codepoint, glyph_name in table.cmap.items():
            match = GLYPH_NAME_PATTERN.fullmatch(glyph_name)
            if match:
                translation[codepoint] = int(match.group(1), 16)
    return translation


class ShixisengCrawler(GenericCrawler):
    def _build_urls(self) -> list[str]:
        urls = list(self.source_config.get("urls", []))
        keywords = self.source_config.get("keywords", [])
        locations = self.source_config.get("locations", [""])
        max_pages = int(self.source_config.get("max_pages", 1))
        for keyword in keywords:
            for location in locations:
                for page in range(1, max_pages + 1):
                    urls.append(
                        "https://www.shixiseng.com/interns"
                        f"?keyword={quote_plus(keyword)}&city={quote_plus(location)}&page={page}"
                    )
        return urls

    def crawl(self):
        """Decode Shixiseng's per-page webfont before parsing job titles."""
        timeout = int(self.config.get("app", {}).get("request_timeout_seconds", 15))
        session = requests.Session()
        jobs = []
        for url in self._build_urls():
            try:
                response = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
                response.raise_for_status()
                if not response.encoding or response.encoding.lower() == "iso-8859-1":
                    response.encoding = response.apparent_encoding
                page_html = response.text

                match = FONT_URL_PATTERN.search(page_html)
                if match:
                    font_url = urljoin(url, match.group(1).strip("\"'"))
                    font_response = session.get(
                        font_url,
                        headers={**DEFAULT_HEADERS, "Referer": url},
                        timeout=timeout,
                    )
                    font_response.raise_for_status()
                    translation = _font_translation(font_response.content)
                    page_html = html_module.unescape(page_html).translate(translation)
                else:
                    self.logger.warning("no obfuscation font found at %s", url)

                jobs.extend(self._parse_html(page_html, url))
            except Exception as exc:  # noqa: BLE001 - one source page must not abort the report
                self.logger.warning("failed to crawl %s: %s", url, exc.__class__.__name__)
        return self._unique(jobs)
