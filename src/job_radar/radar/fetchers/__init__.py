"""One fetcher per ATS platform; `FETCHERS[platform]` picks it."""

from job_radar.radar.fetchers.ashby import AshbyFetcher
from job_radar.radar.fetchers.base import Fetcher, FetchError, TokenNotFound
from job_radar.radar.fetchers.greenhouse import GreenhouseFetcher
from job_radar.radar.fetchers.lever import LeverFetcher
from job_radar.radar.models import Platform

FETCHERS: dict[Platform, Fetcher] = {
    Platform.GREENHOUSE: GreenhouseFetcher(),
    Platform.LEVER: LeverFetcher(),
    Platform.ASHBY: AshbyFetcher(),
}

__all__ = ["FETCHERS", "FetchError", "Fetcher", "TokenNotFound"]
