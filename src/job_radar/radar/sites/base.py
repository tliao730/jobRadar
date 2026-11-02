"""Shared behaviour for searching a job site politely: paced requests, and stopping the site
for the rest of the run on a rate limit, login wall or challenge page (results so far kept)."""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

from job_radar.radar.models import Platform, Posting, SiteConfig, Sources

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class SiteBlocked(RuntimeError):
    """The site rate-limited us or wants a login / challenge: stop searching it this run."""


@dataclass
class SearchResult:
    platform: Platform
    postings: list[Posting] = field(default_factory=list)
    error: str = ""  # why the search stopped early; postings found before that are kept
    requests: int = 0


class SiteSearch(ABC):
    platform: Platform

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    @abstractmethod
    def requests(self, sources: Sources) -> Iterator[tuple[str, dict, str]]:
        """(url, params, query) for every page to fetch, in order."""

    @abstractmethod
    def parse(self, response: httpx.Response, sources: Sources) -> list[Posting]:
        """Postings on one page; raises SiteBlocked when the page is not a result page."""

    def config(self, sources: Sources) -> SiteConfig:
        return getattr(sources, self.platform.value)

    def search(self, sources: Sources, client: httpx.Client) -> SearchResult:
        result = SearchResult(self.platform)
        site = self.config(sources)
        seen: set[str] = set()
        exhausted: set[str] = set()  # queries whose last page came back empty
        try:
            for url, params, query in self.requests(sources):
                if query in exhausted:
                    continue
                if result.requests:
                    self.sleep(random.uniform(*site.delay_seconds))
                result.requests += 1
                try:
                    response = client.get(url, params=params, headers=BROWSER_HEADERS)
                except httpx.HTTPError as exc:
                    raise SiteBlocked(f"連線失敗：{exc}") from exc
                if response.status_code in (429, 999):
                    raise SiteBlocked(f"被限流（HTTP {response.status_code}）")
                page = self.parse(response, sources)
                if not page:
                    exhausted.add(query)
                for posting in page:
                    if posting.id not in seen:
                        seen.add(posting.id)
                        result.postings.append(posting)
        except SiteBlocked as exc:
            result.error = str(exc)
            log.warning("%s 停止搜尋：%s（已取得 %d 筆）", self.platform, exc, len(result.postings))
        return result
