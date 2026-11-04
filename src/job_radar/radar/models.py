"""Job radar data: companies to watch, normalized postings, and the radar's own settings."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Hashable
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
    SIMPLIFY = "simplify"  # Simplify's lists on GitHub: links straight to the company's form


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


class SimplifyConfig(SiteConfig):
    repos: list[str] = Field(default_factory=lambda: ["SimplifyJobs/New-Grad-Positions"])


class Sources(BaseModel):
    queries: list[str] = Field(default_factory=list)
    location: str = "United States"
    days: int = 7
    linkedin: SiteConfig = Field(default_factory=lambda: SiteConfig(enabled=False))
    jobright: SiteConfig = Field(default_factory=lambda: SiteConfig(enabled=False))
    simplify: SimplifyConfig = Field(default_factory=lambda: SimplifyConfig(enabled=False))


class RadarConfig(BaseModel):
    companies: list[Company]
    filters: Filters
    skills: list[Skill]
    sources: Sources = Field(default_factory=Sources)


def load_radar_config(config_dir: Path, personal_dir: Path | None = None) -> RadarConfig:
    """Shared settings from `config_dir` (in git). A companies / filters / sources file of the
    same name in `personal_dir` (profile/, not in git) holds only what one person changes, so
    `git pull` never conflicts with it."""

    def read(path: Path) -> dict:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def load(name: str) -> dict:
        shared = read(config_dir / name)
        return merge_settings(shared, read(personal_dir / name)) if personal_dir else shared

    companies = read(config_dir / "companies.yaml").get("companies") or []
    if personal_dir:
        mine = read(personal_dir / "companies.yaml").get("companies") or []
        companies = merge_entries(companies, mine, _company_key)
    return RadarConfig(
        companies=companies,
        filters=load("filters.yaml"),
        skills=read(config_dir / "skills.yaml").get("skills", []),
        sources=load("sources.yaml"),
    )


def merge_settings(base: dict, override: dict) -> dict:
    """`override` wins: mappings merge key by key, lists of entries with an `id` (role
    families) merge by id, other lists are replaced."""
    out = dict(base)
    for key, value in override.items():
        old = out.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            out[key] = merge_settings(old, value)
        elif _has_ids(old) and _has_ids(value):
            out[key] = merge_entries(old, value, lambda entry: entry["id"])
        else:
            out[key] = value
    return out


def merge_entries(
    base: list[dict], override: list[dict], key: Callable[[dict], Hashable]
) -> list[dict]:
    """Entries of `override` update the base entry with the same key; new ones are appended."""
    merged = {key(entry): entry for entry in base}
    for entry in override:
        k = key(entry)
        merged[k] = merge_settings(merged[k], entry) if k in merged else entry
    return list(merged.values())


def _has_ids(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(e, dict) and "id" in e for e in value)
    )


def _company_key(entry: dict) -> Hashable:
    return (entry.get("platform"), entry.get("token"))
