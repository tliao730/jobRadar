"""Jobright's logged-out search page: the first 20 results per query, server-rendered in
`__NEXT_DATA__`. The apply link needs a login, so postings point at the Jobright page."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx

from job_radar.radar.models import Platform, Posting, Sources
from job_radar.radar.sites.base import SiteBlocked, SiteSearch

SEARCH_URL = "https://jobright.ai/jobs/search"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class JobrightSearch(SiteSearch):
    platform = Platform.JOBRIGHT

    def requests(self, sources: Sources) -> Iterator[tuple[str, dict, str]]:
        for query in sources.queries:
            yield SEARCH_URL, {"value": query}, query

    def parse(self, response: httpx.Response, sources: Sources) -> list[Posting]:
        if "challenge" in response.headers.get("location", ""):
            # Since 2026-11 every search is sent to /_jr/security/challenge: a bot check we stop at.
            raise SiteBlocked("要求真人驗證（反爬蟲驗證頁），暫時無法自動抓取")
        m = _NEXT_DATA.search(response.text)
        if response.status_code != 200 or not m:
            # Throttled requests get a "303 See Other" body with status 200.
            raise SiteBlocked("回傳的不是搜尋結果（多半是限流）")
        try:
            jobs = json.loads(m.group(1))["props"]["pageProps"].get("jobList") or []
        except (ValueError, KeyError) as exc:
            raise SiteBlocked(f"搜尋結果格式改變：{exc}") from exc
        cutoff = datetime.now(UTC) - timedelta(days=sources.days)
        postings = []
        for item in jobs:
            job = item.get("jobResult") or {}
            company = item.get("companyResult") or {}
            if not job.get("jobId") or not job.get("jobTitle"):
                continue
            posted = _time(job.get("publishTime"))
            if posted and posted < cutoff:
                continue
            url = f"https://jobright.ai/jobs/info/{job['jobId']}"
            postings.append(
                Posting(
                    id=f"jobright:{job['jobId']}",
                    platform=self.platform,
                    company=company.get("companyName") or "",
                    token="",
                    title=job["jobTitle"],
                    location=job.get("jobLocation") or "",
                    url=url,
                    apply_url=url,
                    description=_text(job),
                    posted_at=posted,
                    remote=(job.get("workModel") == "Remote") or None,
                    seniority=job.get("jobSeniority") or "",
                )
            )
        return postings


def _time(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _text(job: dict) -> str:
    parts = [job.get("jobSummary") or ""]
    for key in ("coreResponsibilities", "qualifications", "detailQualifications"):
        value = job.get(key)
        if isinstance(value, list):
            parts += [str(v) for v in value]
        elif isinstance(value, str):
            parts.append(value)
    return "\n".join(p for p in parts if p and p != "None")
