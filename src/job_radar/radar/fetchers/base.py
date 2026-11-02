"""Shared HTTP behaviour for ATS job-board APIs; subclasses only map the payload."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import httpx

from job_radar.radar.models import Company, Platform, Posting

log = logging.getLogger(__name__)

RETRIES = 3


class FetchError(RuntimeError):
    """The board could not be fetched this time (network, 5xx, rate limit)."""


class TokenNotFound(FetchError):
    """404: the company's board token is wrong or the board was removed."""


class Fetcher(ABC):
    platform: Platform

    @abstractmethod
    def board_url(self, token: str) -> str: ...

    @abstractmethod
    def parse(self, company: Company, payload) -> list[Posting]: ...

    def fetch(self, company: Company, client: httpx.Client) -> list[Posting]:
        return self.parse(company, self.get_json(client, self.board_url(company.token)))

    def get_json(self, client: httpx.Client, url: str):
        for attempt in range(RETRIES + 1):
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                error = f"連線失敗：{exc}"
            else:
                if response.status_code == 404:
                    raise TokenNotFound(f"找不到職缺板（404）：{url}")
                if response.status_code == 429 or response.status_code >= 500:
                    error = f"HTTP {response.status_code}"
                else:
                    response.raise_for_status()
                    return response.json()
            if attempt < RETRIES:
                time.sleep(2**attempt)
        raise FetchError(f"{error}：{url}")


def from_epoch_ms(value) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, UTC) if isinstance(value, int | float) else None


def from_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
