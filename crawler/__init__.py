from __future__ import annotations

from crawler.company import CompanyCrawler
from crawler.generic import GenericCrawler
from crawler.nowcoder import NowCoderCrawler
from crawler.shixiseng import ShixisengCrawler
from crawler.yingjiesheng import YingjieshengCrawler


def build_crawlers(config: dict):
    crawler_types = {
        "generic": GenericCrawler,
        "company": CompanyCrawler,
        "nowcoder": NowCoderCrawler,
        "shixiseng": ShixisengCrawler,
        "yingjiesheng": YingjieshengCrawler,
    }
    crawlers = []
    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        crawler_class = crawler_types.get(str(source.get("type", "generic")).lower())
        if crawler_class is None:
            continue
        crawlers.append(crawler_class(source, config))
    return crawlers


__all__ = ["build_crawlers"]

