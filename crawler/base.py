from __future__ import annotations

import logging
from typing import Iterable

from models import Job


class BaseCrawler:
    def __init__(self, source_config: dict, config: dict) -> None:
        self.source_config = source_config
        self.config = config
        self.name = str(source_config.get("name", source_config.get("type", "source")))
        self.logger = logging.getLogger(f"crawler.{self.name}")

    def crawl(self) -> list[Job]:
        raise NotImplementedError

    def _unique(self, jobs: Iterable[Job]) -> list[Job]:
        seen: set[str] = set()
        result: list[Job] = []
        for job in jobs:
            key = job.dedupe_key
            if key in seen:
                continue
            seen.add(key)
            result.append(job)
        return result

