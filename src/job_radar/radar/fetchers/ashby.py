from __future__ import annotations

from job_radar.apply.intake import html_to_text
from job_radar.radar.fetchers.base import Fetcher, from_iso
from job_radar.radar.models import Company, Platform, Posting


class AshbyFetcher(Fetcher):
    platform = Platform.ASHBY

    def board_url(self, token: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"

    def parse(self, company: Company, payload) -> list[Posting]:
        postings = []
        for job in payload.get("jobs") or []:
            if job.get("isListed") is False:
                continue
            url = job.get("jobUrl") or f"https://jobs.ashbyhq.com/{company.token}/{job['id']}"
            postings.append(
                Posting(
                    id=f"ashby:{job['id']}",
                    platform=self.platform,
                    company=company.name,
                    token=company.token,
                    title=job.get("title") or "",
                    location=job.get("location") or "",
                    url=url,
                    apply_url=job.get("applyUrl") or f"{url}/application",
                    description=job.get("descriptionPlain")
                    or html_to_text(job.get("descriptionHtml") or ""),
                    posted_at=from_iso(job.get("publishedAt")),
                    remote=job.get("isRemote"),
                )
            )
        return postings
