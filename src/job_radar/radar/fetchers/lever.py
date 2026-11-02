from __future__ import annotations

from job_radar.apply.intake import lever_description
from job_radar.radar.fetchers.base import Fetcher, from_epoch_ms
from job_radar.radar.models import Company, Platform, Posting


class LeverFetcher(Fetcher):
    platform = Platform.LEVER

    def board_url(self, token: str) -> str:
        return f"https://api.lever.co/v0/postings/{token}?mode=json"

    def parse(self, company: Company, payload) -> list[Posting]:
        postings = []
        for job in payload if isinstance(payload, list) else []:
            categories = job.get("categories") or {}
            url = job.get("hostedUrl") or f"https://jobs.lever.co/{company.token}/{job['id']}"
            postings.append(
                Posting(
                    id=f"lever:{job['id']}",
                    platform=self.platform,
                    company=company.name,
                    token=company.token,
                    title=job.get("text") or "",
                    location=categories.get("location") or "",
                    url=url,
                    apply_url=job.get("applyUrl") or f"{url}/apply",
                    description=lever_description(job),
                    posted_at=from_epoch_ms(job.get("createdAt")),
                    remote=(job.get("workplaceType") == "remote") or None,
                )
            )
        return postings
