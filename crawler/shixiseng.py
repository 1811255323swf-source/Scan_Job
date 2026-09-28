from __future__ import annotations

from urllib.parse import quote_plus

from crawler.generic import GenericCrawler


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

