"""Rule-based matching (no LLM): hard filters, then a 0–100 score from skill overlap, role
preference and level. Every exclusion keeps its reason so the page can show why."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from job_radar.profile import Profile, resume_text
from job_radar.radar.models import Filters, Skill

LEVEL_NAMES = {"intern": "實習", "new_grad": "新鮮人"}
# Seniority labels from job sites; a label mapped to None is excluded.
SITE_LEVELS = {
    "": "", "entry level": "new_grad", "new grad": "new_grad", "internship": "intern",
    "intern": "intern", "associate": "new_grad", "not applicable": "",
    "mid level": None, "mid, senior level": None, "senior level": None, "lead/staff": None,
    "mid-senior level": None, "director": None, "executive": None,
}  # fmt: skip
_YEARS = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?(?:years?|yrs?)\b[^.\n]{0,40}?experience",
    re.I,
)


def min_years(description: str) -> int | None:
    """The smallest "N+ years of experience" a JD asks for (None if it never says)."""
    found = [int(m.group(1)) for m in _YEARS.finditer(description)]
    found = [n for n in found if 0 < n < 20]
    return min(found) if found else None


@dataclass
class Match:
    id: str
    company: str
    title: str
    location: str
    url: str
    apply_url: str
    platform: str
    posted_at: datetime | None
    first_seen_at: datetime | None
    is_new: bool  # first seen in the last NEW_DAYS days (a board's first fetch never counts)
    role: str = ""
    level: str = ""
    score: int = 0
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    excluded: str = ""  # why it is not recommended; "" when it is
    other_locations: list[str] = field(default_factory=list)  # same job posted elsewhere
    also_on: list[str] = field(default_factory=list)  # job sites listing this same ATS job
    manual: bool = False  # a job-site posting with no matching ATS job: open it yourself


def _any(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


class Matcher:
    def __init__(self, filters: Filters, skills: list[Skill], my_skills: set[str]) -> None:
        self.f = filters
        self.roles = [(r, _any(r.titles)) for r in filters.roles if r.enabled]
        self.exclude_title = _any(filters.exclude_titles)
        self.level_exclude = _any(filters.levels.exclude)
        self.level_boost = {name: _any(pats) for name, pats in filters.levels.boost.items()}
        self.intern_requires = _any(filters.levels.intern_requires)
        self.intern_requires_in_jd = _any(filters.levels.intern_requires_in_jd)
        self.loc_include = _any(filters.locations.include)
        self.loc_exclude = _any(filters.locations.exclude)
        self.no_sponsor = _any(filters.sponsorship.no_sponsorship)
        self.skills = [(s.name, re.compile(s.match, re.I)) for s in skills]
        self.my_skills = my_skills

    def evaluate(self, job: dict, now: datetime | None = None) -> Match:
        now = now or datetime.now(UTC).replace(tzinfo=None)
        m = Match(
            id=job["id"],
            company=job["company"],
            title=job["title"],
            location=job.get("location") or "",
            url=job["url"],
            apply_url=job["apply_url"],
            platform=job["platform"],
            posted_at=job.get("posted_at"),
            first_seen_at=job.get("first_seen_at"),
            is_new=_recent(job, now),
            manual=job["platform"] in ("linkedin", "jobright"),
        )
        title = m.title
        role = next((r for r, rx in self.roles if rx and rx.search(title)), None)
        m.role = role.id if role else ""
        m.level = next((n for n, rx in self.level_boost.items() if rx and rx.search(title)), "")
        m.level = m.level or SITE_LEVELS.get((job.get("seniority") or "").strip().lower(), "")
        # Title and location rule out most postings; only the rest pay for reading the JD.
        m.excluded = self._excluded_by_title(job, title, role)
        if m.excluded:
            return m
        m.excluded = self._excluded_by_description(job, now)
        text = f"{title}\n{job.get('description') or ''}"
        jd_skills = [name for name, rx in self.skills if rx.search(text)]
        m.matched_skills = [s for s in jd_skills if s in self.my_skills]
        m.missing_skills = [s for s in jd_skills if s not in self.my_skills]

        w = self.f.weights
        # Smoothed share of the JD's skills I have: 2 of 2 should not beat 6 of 7.
        skill = (len(m.matched_skills) + 1) / (len(jd_skills) + 2)
        level = self._level_score(m.level)
        total = w.skills + w.role + w.level or 1
        role_weight = role.weight if role else 0
        m.score = round(100 * (w.skills * skill + w.role * role_weight + w.level * level) / total)
        return m

    def _in_area(self, location: str) -> bool:
        """Any listed place that matches `include` and not `exclude` ("Remote - Canada" fails,
        "San Francisco, CA; London" passes)."""
        for place in re.split(r"[;|•/]| or ", location):
            if self.loc_include and not self.loc_include.search(place):
                continue
            if self.loc_exclude and self.loc_exclude.search(place):
                continue
            return True
        return False

    def _level_score(self, level: str) -> float:
        """1 for a wanted level (or when any level is fine), less when unstated or unwanted."""
        want = self.f.levels.want
        if "any" in want or level in want:
            return 1.0
        return 0.6 if level else 0.3

    def _excluded_by_title(self, job: dict, title: str, role) -> str:
        if self.exclude_title and (hit := self.exclude_title.search(title)):
            return f"職稱含「{hit.group(0)}」"
        if role is None:
            return "不是目標職務類別"
        if self.level_exclude and (hit := self.level_exclude.search(title)):
            return f"層級：{hit.group(0).strip()}"
        seniority = (job.get("seniority") or "").strip()
        if seniority and SITE_LEVELS.get(seniority.lower()) is None:
            return f"層級：{seniority}"
        if self._unwanted_intern(job, title):
            return "實習（不是 co-op / off-cycle）"
        location = job.get("location") or ""
        if location and not self._in_area(location):
            return f"地點：{location}"
        return ""

    def _unwanted_intern(self, job: dict, title: str) -> bool:
        """An internship without the co-op / off-cycle wording `intern_requires` asks for."""
        intern = self.level_boost.get("intern")
        rules = (self.intern_requires, self.intern_requires_in_jd)
        if not (intern and any(rules) and intern.search(title)):
            return False
        in_title = self.intern_requires and self.intern_requires.search(title)
        jd = job.get("description") or ""
        in_jd = self.intern_requires_in_jd and self.intern_requires_in_jd.search(jd)
        return not (in_title or in_jd)

    def _excluded_by_description(self, job: dict, now: datetime) -> str:
        years = min_years(job.get("description") or "")
        if self.f.levels.max_years is not None and years and years > self.f.levels.max_years:
            return f"要求 {years} 年以上經驗"
        if (
            self.f.sponsorship.exclude_no_sponsorship
            and self.no_sponsor
            and (hit := self.no_sponsor.search(job.get("description") or ""))
        ):
            return f"不提供 sponsorship（「{hit.group(0)[:60]}」）"
        posted = job.get("posted_at")
        if self.f.max_age_days and posted and now - posted > timedelta(days=self.f.max_age_days):
            return f"發布超過 {self.f.max_age_days} 天"
        return ""


NEW_DAYS = 3


def _recent(job: dict, now: datetime) -> bool:
    first = job.get("first_seen_at")
    if job.get("is_baseline", False) or first is None:
        return False
    return now - first <= timedelta(days=NEW_DAYS)


def my_skills(profile: Profile, profile_dir: Path, skills: list[Skill]) -> set[str]:
    """Vocabulary skills found in highlights, the resume, and profile/skills.yaml (if any)."""
    parts = []
    for h in profile.highlights:
        parts += [h.context, h.did, *h.results, *h.skills]
    for path in profile.resume_variants().values():
        parts.append(resume_text(path))
    extra = profile_dir / "skills.yaml"
    if extra.exists():
        listed = (yaml.safe_load(extra.read_text("utf-8")) or {}).get("skills", [])
        parts += [str(s) for s in listed]
    text = "\n".join(parts)
    return {s.name for s in skills if re.search(s.match, text, re.I)}
