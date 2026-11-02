"""Job radar data: companies to watch, normalized postings, and the radar's own settings."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Platform(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    # Job sites searched without logging in; their postings link to an ATS job when one matches.
    LINKEDIN = "linkedin"
    JOBRIGHT = "jobright"


ATS_PLATFORMS = (Platform.GREENHOUSE, Platform.LEVER, Platform.ASHBY)


class Company(BaseModel):
    name: str
    platform: Platform
    token: str
    enabled: bool = True


class Posting(BaseModel):
    """One job as fetched, normalized across platforms."""

    id: str  # "{platform}:{source id}"
    platform: Platform
    company: str
    token: str
    title: str
    location: str = ""
    url: str  # the posting page
    apply_url: str  # the page with the application form
    description: str = ""  # plain text
    posted_at: datetime | None = None
    remote: bool | None = None
    seniority: str = ""  # as the job site labels it ("Entry Level", "New Grad"...)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.description}".encode()).hexdigest()


class RoleFamily(BaseModel):
    id: str
    weight: float = 1.0
    titles: list[str]
    enabled: bool = True


class Levels(BaseModel):
    exclude: list[str] = Field(default_factory=list)
    boost: dict[str, list[str]] = Field(default_factory=dict)
    want: list[str] = Field(default_factory=lambda: ["any"])
    intern_requires: list[str] = Field(default_factory=list)  # in the title
    intern_requires_in_jd: list[str] = Field(default_factory=list)
    max_years: int | None = None


class Locations(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class Sponsorship(BaseModel):
    exclude_no_sponsorship: bool = False
    no_sponsorship: list[str] = Field(default_factory=list)


class Weights(BaseModel):
    skills: float = 0.5
    role: float = 0.3
    level: float = 0.2


class Filters(BaseModel):
    roles: list[RoleFamily] = Field(default_factory=list)
    exclude_titles: list[str] = Field(default_factory=list)
    levels: Levels = Field(default_factory=Levels)
    locations: Locations = Field(default_factory=Locations)
    sponsorship: Sponsorship = Field(default_factory=Sponsorship)
    weights: Weights = Field(default_factory=Weights)
    max_age_days: int | None = None


class Skill(BaseModel):
    name: str
    match: str


class SiteConfig(BaseModel):
    enabled: bool = True
    pages_per_query: int = 1
    delay_seconds: tuple[float, float] = (3.0, 8.0)


class Sources(BaseModel):
    queries: list[str] = Field(default_factory=list)
    location: str = "United States"
    days: int = 7
    linkedin: SiteConfig = Field(default_factory=lambda: SiteConfig(enabled=False))
    jobright: SiteConfig = Field(default_factory=lambda: SiteConfig(enabled=False))


class RadarConfig(BaseModel):
    companies: list[Company]
    filters: Filters
    skills: list[Skill]
    sources: Sources = Field(default_factory=Sources)


def load_radar_config(config_dir: Path) -> RadarConfig:
    def read(name: str) -> dict:
        path = config_dir / name
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    return RadarConfig(
        companies=read("companies.yaml").get("companies", []),
        filters=read("filters.yaml"),
        skills=read("skills.yaml").get("skills", []),
        sources=read("sources.yaml"),
    )
