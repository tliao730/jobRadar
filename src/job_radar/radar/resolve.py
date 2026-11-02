"""Match job-site postings (LinkedIn, Jobright) to the same job on a company's ATS board.

A match turns a posting the assistant cannot fill (the site hides the apply link without a
login) into one it can. Companies whose board is unknown get their likely board tokens tried
on Greenhouse, Lever and Ashby; the answer, found or not, is cached for RECHECK_DAYS.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx

from job_radar.radar.fetchers import FETCHERS, FetchError
from job_radar.radar.models import ATS_PLATFORMS, Company, Platform
from job_radar.radar.store import BoardResult, RadarStore, utcnow

log = logging.getLogger(__name__)

RECHECK_DAYS = 30
MIN_TITLE_SIMILARITY = 0.6
_SUFFIXES = {
    "inc", "llc", "ltd", "corp", "corporation", "co", "company", "the", "group", "holdings",
    "technologies", "technology", "labs", "usa", "us", "plc", "lp",
}  # fmt: skip
_TITLE_NOISE = {"the", "a", "an", "and", "of", "for", "to", "in", "at", "with", "remote", "hybrid"}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()


def company_key(name: str) -> str:
    return " ".join(w for w in _words(name) if w not in _SUFFIXES)


def slug_guesses(name: str) -> list[str]:
    # The whole name only: a first-word guess ("applied", "new", "general") lands on other
    # companies' boards.
    words = company_key(name).split()
    return list(dict.fromkeys(["".join(words), "-".join(words)])) if words else []


def title_similarity(a: str, b: str) -> float:
    left = set(_words(a)) - _TITLE_NOISE
    right = set(_words(b)) - _TITLE_NOISE
    return len(left & right) / len(left | right) if left and right else 0.0


class Resolver:
    def __init__(self, store: RadarStore, client: httpx.Client, workers: int = 4) -> None:
        self.store = store
        self.client = client
        self.workers = workers

    def resolve(
        self, postings: list[dict], ats_jobs: list[dict], known: list[Company]
    ) -> tuple[dict[str, str], list[BoardResult]]:
        """(posting id → ATS job id, boards fetched for newly found companies)."""
        by_company: dict[str, list[dict]] = {}
        for job in ats_jobs:
            by_company.setdefault(company_key(job["company"]), []).append(job)
        tracked = {company_key(c.name) for c in known}
        titles: dict[str, list[str]] = {}
        names: dict[str, str] = {}
        for p in postings:
            key = company_key(p["company"])
            if key and key not in by_company and key not in tracked:
                titles.setdefault(key, []).append(p["title"])
                names.setdefault(key, p["company"])
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            found = list(pool.map(lambda k: self._board(k, names[k], titles[k]), sorted(titles)))
        boards = [b for b in found if b is not None]
        for board in boards:
            by_company[company_key(board.company.name)] = [
                {"id": p.id, "title": p.title, "company": p.company} for p in board.postings
            ]
        links = {}
        for posting in postings:
            candidates = by_company.get(company_key(posting["company"]), [])
            best = max(
                candidates,
                key=lambda j: title_similarity(j["title"], posting["title"]),
                default=None,
            )
            if best and title_similarity(best["title"], posting["title"]) >= MIN_TITLE_SIMILARITY:
                links[posting["id"]] = best["id"]
        return links, boards

    def _board(self, key: str, name: str, titles: list[str]) -> BoardResult | None:
        cached = self.store.board_lookup(key)
        fresh = cached and utcnow() - cached["checked_at"] < timedelta(days=RECHECK_DAYS)
        if fresh and not cached["platform"]:
            return None
        if fresh:
            company = Company(name=name, platform=cached["platform"], token=cached["token"])
            return self._fetch(company)
        for token in slug_guesses(name):
            for platform in ATS_PLATFORMS:
                board = self._fetch(Company(name=name, platform=platform, token=token))
                if board and _is_theirs(board, key, titles):
                    self.store.save_board(key, name, platform.value, token)
                    log.info("找到 %s 的職缺板：%s/%s", name, platform.value, token)
                    return board
        self.store.save_board(key, name, None, None)
        return None

    def _fetch(self, company: Company) -> BoardResult | None:
        try:
            platform = Platform(company.platform)
            return BoardResult(company, FETCHERS[platform].fetch(company, self.client))
        except (FetchError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return None


def _is_theirs(board: BoardResult, key: str, titles: list[str]) -> bool:
    """A guessed board belongs to the company only if it lists one of the jobs seen on the job
    site, and (on Greenhouse, which names the company) under the same company name."""
    named = {company_key(p.company) for p in board.postings if p.company != board.company.name}
    if named and key not in named:
        return False
    return any(
        title_similarity(p.title, title) >= MIN_TITLE_SIMILARITY
        for p in board.postings
        for title in titles
    )
