from __future__ import annotations

import html

from job_radar.apply.intake import greenhouse_apply_url, html_to_text
from job_radar.radar.fetchers.base import Fetcher, from_iso
from job_radar.radar.models import Company, Platform, Posting

BOARD_HOST = "job-boards.greenhouse.io"


class GreenhouseFetcher(Fetcher):
    platform = Platform.GREENHOUSE

    def board_url(self, token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    def parse(self, company: Company, payload) -> list[Posting]:
        postings = []
        for job in payload.get("jobs") or []:
            job_id = str(job["id"])
            postings.append(
                Posting(
                    id=f"greenhouse:{job_id}",
                    platform=self.platform,
                    company=job.get("company_name") or company.name,
                    token=company.token,
                    title=job.get("title") or "",
                    location=(job.get("location") or {}).get("name", ""),
                    url=job.get("absolute_url") or "",
                    apply_url=greenhouse_apply_url(
                        "job-boards.greenhouse.io", company.token, job_id
                    ),
                    # `content` is entity-encoded HTML; `updated_at` is not the publish date.
                    description=html_to_text(html.unescape(job.get("content") or "")),
                    posted_at=from_iso(job.get("first_published")),
                )
            )
        return postings
