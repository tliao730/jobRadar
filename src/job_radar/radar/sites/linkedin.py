"""LinkedIn's logged-out job search (jobs-guest). Cards only: title, company, location, date.

The guest detail endpoint rate-limits within a couple of requests and hides the company's
apply link behind a sign-in modal, so details are not fetched; the JD comes from the ATS job
the card is matched to.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from job_radar.radar.models import Platform, Posting, Sources
from job_radar.radar.sites.base import SiteBlocked, SiteSearch

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)(?=data-entity-urn=|\Z)', re.S)


def _field(card: str, pattern: str) -> str:
    m = re.search(pattern, card, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


class LinkedInSearch(SiteSearch):
    platform = Platform.LINKEDIN

    def requests(self, sources: Sources) -> Iterator[tuple[str, dict, str]]:
        for query in sources.queries:
            for page in range(self.config(sources).pages_per_query):
                yield (
                    SEARCH_URL,
                    {
                        "keywords": query,
                        "location": sources.location,
                        "f_TPR": f"r{sources.days * 86400}",
                        "start": page * 10,
                    },
                    query,
                )

    def parse(self, response: httpx.Response, sources: Sources) -> list[Posting]:
        if "authwall" in str(response.url) or "/login" in str(response.url):
            raise SiteBlocked("要求登入")
        if response.status_code != 200:
            raise SiteBlocked(f"HTTP {response.status_code}")
        postings = []
        for job_id, card in _CARD.findall(response.text):
            title = _field(card, r'base-search-card__title">(.*?)</h3>')
            if not title:
                continue
            posted = _field(card, r'<time[^>]*datetime="([^"]+)"')
            url = f"https://www.linkedin.com/jobs/view/{job_id}"
            postings.append(
                Posting(
                    id=f"linkedin:{job_id}",
                    platform=self.platform,
                    company=_field(card, r'base-search-card__subtitle">(.*?)</h4>'),
                    token="",
                    title=title,
                    location=_field(card, r'job-search-card__location">(.*?)</span>'),
                    url=url,
                    apply_url=url,
                    posted_at=_date(posted),
                )
            )
        return postings


def _date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
