from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())


@dataclass(frozen=True)
class Job:
    source: str
    company: str
    position: str
    location: str = ""
    published_at: str = ""
    education: str = ""
    graduation_year: str = ""
    internship_period: str = ""
    description: str = ""
    requirements: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "source",
            "company",
            "position",
            "location",
            "published_at",
            "education",
            "graduation_year",
            "internship_period",
            "description",
            "requirements",
            "url",
        ):
            object.__setattr__(self, field_name, clean_text(getattr(self, field_name)))

    @property
    def search_text(self) -> str:
        return " ".join(
            [
                self.company,
                self.position,
                self.location,
                self.published_at,
                self.education,
                self.graduation_year,
                self.internship_period,
                self.description,
                self.requirements,
            ]
        )

    @property
    def dedupe_key(self) -> str:
        if self.url:
            return self.url
        raw = "|".join([self.company, self.position, self.location, self.source])
        digest = sha256(raw.encode("utf-8")).hexdigest()
        return f"generated://{digest}"


@dataclass(frozen=True)
class ScoreResult:
    score: int
    level: str
    matched_rules: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    excluded: bool = False


@dataclass(frozen=True)
class AnalyzedJob:
    job: Job
    score: int
    level: str
    matched_rules: list[str]
    penalties: list[str]
    ai_analysis: str

