"""Job sites read without logging in (LinkedIn, Jobright, Simplify); `SITES[platform]` picks one."""

from job_radar.radar.models import Platform
from job_radar.radar.sites.base import SearchResult, SiteBlocked, SiteSearch
from job_radar.radar.sites.jobright import JobrightSearch
from job_radar.radar.sites.linkedin import LinkedInSearch
from job_radar.radar.sites.simplify import SimplifyLists

SITES: dict[Platform, SiteSearch] = {
    Platform.LINKEDIN: LinkedInSearch(),
    Platform.JOBRIGHT: JobrightSearch(),
    Platform.SIMPLIFY: SimplifyLists(),
}

__all__ = ["SITES", "SearchResult", "SiteBlocked", "SiteSearch"]
