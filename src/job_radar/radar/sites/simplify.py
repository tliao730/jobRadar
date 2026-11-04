"""Simplify's job lists on GitHub (SimplifyJobs/New-Grad-Positions and the internship repos):
one public JSON file per repo with every listing, no login and no bot check.

Each listing links straight to the company's application page, so a Greenhouse / Lever /
Ashby link is fillable as is and nothing is guessed from company names. The file is the
whole list, so a listing missing from it (or marked inactive) is closed right away.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from job_radar.radar.models import Platform, Posting, Sources
from job_radar.radar.sites.base import SiteBlocked, SiteSearch

LISTINGS_URL = "https://raw.githubusercontent.com/{repo}/dev/.github/scripts/listings.json"
_NO_INFO = {"", "other"}  # Simplify's sponsorship value when it does not know


class SimplifyLists(SiteSearch):
    platform = Platform.SIMPLIFY
    needs_queries = False
    direct_links = True
    complete = True

    def requests(self, sources: Sources) -> Iterator[tuple[str, dict, str]]:
        for repo in sources.simplify.repos:
            yield LISTINGS_URL.format(repo=repo), {}, repo

    def parse(self, response: httpx.Response, sources: Sources) -> list[Posting]:
        if response.status_code != 200:
            raise SiteBlocked(f"HTTP {response.status_code}（repo 名稱錯了，或檔案搬家了）")
        try:
            listings = response.json()
        except ValueError as exc:
            raise SiteBlocked("清單格式改變，讀不懂") from exc
        if not isinstance(listings, list):
            raise SiteBlocked("清單格式改變，讀不懂")
        # The internship repos list internships; the new-grad repo, new-grad roles.
        level = "Internship" if "intern" in response.url.path.lower() else "New Grad"
        postings = []
        for item in listings:
            if not isinstance(item, dict) or not item.get("active") or not item.get("url"):
                continue
            if not item.get("is_visible", True) or not item.get("id") or not item.get("title"):
                continue
            notes = []
            sponsorship = str(item.get("sponsorship") or "")
            if sponsorship.lower() not in _NO_INFO:
                notes.append(f"Sponsorship: {sponsorship}")  # read by the sponsorship filter
            if item.get("degrees"):
                notes.append(f"Degrees: {', '.join(map(str, item['degrees']))}")
            postings.append(
                Posting(
                    id=f"simplify:{item['id']}",
                    platform=self.platform,
                    company=str(item.get("company_name") or ""),
                    token="",
                    title=str(item["title"]),
                    location="; ".join(map(str, item.get("locations") or [])),
                    url=item["url"],
                    apply_url=item["url"],
                    description="\n".join(notes),
                    posted_at=_time(item.get("date_posted")),
                    seniority=level,
                )
            )
        return postings


def _time(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
