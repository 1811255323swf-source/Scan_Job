from __future__ import annotations

from urllib.parse import quote_plus

from crawler.generic import GenericCrawler


class NowCoderCrawler(GenericCrawler):
    def _build_urls(self) -> list[str]:
        urls = list(self.source_config.get("urls", []))
        keywords = self.source_config.get("keywords", [])
        max_pages = int(self.source_config.get("max_pages", 1))
        for keyword in keywords:
            for page in range(1, max_pages + 1):
                urls.append(
                    "https://www.nowcoder.com/jobs/recommend/campus"
                    f"?query={quote_plus(keyword)}&page={page}"
                )
        return urls

