"""Fetch every enabled board, record the run, and rank what is worth applying to."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from itertools import repeat

import httpx

from job_radar.apply.intake import USER_AGENT
from job_radar.config import AppConfig
from job_radar.profile import ProfileError, load_profile
from job_radar.radar.fetchers import FETCHERS, FetchError
from job_radar.radar.match import Match, Matcher, my_skills
from job_radar.radar.models import ATS_PLATFORMS, Company, RadarConfig, load_radar_config
from job_radar.radar.resolve import Resolver
from job_radar.radar.sites import SITES
from job_radar.radar.store import BoardResult, RadarStore, RunStats, utcnow

log = logging.getLogger(__name__)

REQUEST_GAP_S = 1.0  # between requests to the same platform
STALE_HOURS = 20  # a daily fetch is due again
ATS_VALUES = {p.value for p in ATS_PLATFORMS}


class RadarService:
    def __init__(self, cfg: AppConfig, store: RadarStore | None = None) -> None:
        self.cfg = cfg
        self.store = store or RadarStore(cfg.data_dir)
        self._fetching = threading.Lock()
        self._evaluating = threading.Lock()  # a page request waits for a warm-up, not redo it
        self._cache: tuple[tuple, list[Match]] | None = None

    def radar_config(self) -> RadarConfig:
        return load_radar_config(self.cfg.root / "config")

    @property
    def fetching(self) -> bool:
        return self._fetching.locked()

    def stale(self, hours: float = STALE_HOURS) -> bool:
        """No fetch in the last `hours` (the Mac was off at 08:30, which launchd never makes up)."""
        run = self.store.last_run()
        return run is None or utcnow() - run["finished_at"] > timedelta(hours=hours)

    def fetch(
        self, client: httpx.Client | None = None, command: str = "fetch", sites: bool = True
    ) -> RunStats:
        """Fetch all enabled ATS boards (one platform per thread, so each host sees ≤ 1 req/s)
        and, with `sites`, search the job sites alongside; then match site postings to ATS jobs."""
        if not self._fetching.acquire(blocking=False):
            raise RuntimeError("已經在抓取職缺")
        try:
            radar = self.radar_config()
            companies = [c for c in radar.companies if c.enabled]
            searchers = [
                SITES[p]
                for p in SITES
                if sites and radar.sources.queries and getattr(radar.sources, p.value).enabled
            ]
            started = utcnow()
            own_client = client is None
            client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
            try:
                by_platform: dict[str, list[Company]] = defaultdict(list)
                for c in companies:
                    by_platform[c.platform].append(c)
                workers = len(by_platform) + len(searchers) or 1
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    # map() queues every task at once, so boards and job sites run side by side.
                    batches = pool.map(self._fetch_boards, by_platform.values(), repeat(client))
                    found = pool.map(lambda site: site.search(radar.sources, client), searchers)
                    results = [r for batch in batches for r in batch]
                    searches = list(found)
                stats = self.store.record_run(command, results, started, searches)
                if searches:
                    self._link_site_postings(client, companies)
            finally:
                if own_client:
                    client.close()
            log.info(
                "抓取完成：%d 個來源成功，新增 %d、更新 %d、下架 %d；失敗 %d",
                stats.ok, stats.new, stats.updated, stats.closed, len(stats.failed),
            )  # fmt: skip
            for failure in stats.failed:
                log.warning("抓取失敗：%s", failure)
            return stats
        finally:
            self._fetching.release()

    def _link_site_postings(self, client: httpx.Client, companies: list[Company]) -> None:
        active = self.store.active()
        ats = [j for j in active if j["platform"] in ATS_VALUES]
        pending = [j for j in active if j["platform"] not in ATS_VALUES and not j["ats_id"]]
        links, boards = Resolver(self.store, client).resolve(pending, ats, companies)
        if boards:
            self.store.record_run("discover", boards, utcnow())
        self.store.link_ats(links)
        log.info("職缺網站的 %d 筆對到 ATS 職缺（共 %d 筆待比對）", len(links), len(pending))

    def found_companies(self) -> list[dict]:
        """ATS boards found through job-site company names that are not in companies.yaml."""
        tracked = {(c.platform.value, c.token) for c in self.radar_config().companies}
        return [b for b in self.store.found_boards() if (b["platform"], b["token"]) not in tracked]

    def add_company(self, name: str, platform: str, token: str) -> None:
        """Append a company to config/companies.yaml (comments and order are kept)."""
        path = self.cfg.root / "config" / "companies.yaml"
        Company(name=name, platform=platform, token=token)  # validate
        if (platform, token) in {
            (c.platform.value, c.token) for c in self.radar_config().companies
        }:
            return
        line = f"  - {{name: {json.dumps(name)}, platform: {platform}, token: {token}}}\n"
        text = path.read_text("utf-8") if path.exists() else "companies:\n"
        path.write_text(text + ("" if text.endswith("\n") else "\n") + line, encoding="utf-8")

    def _fetch_boards(self, companies: list[Company], client: httpx.Client) -> list[BoardResult]:
        results = []
        for i, company in enumerate(companies):
            if i:
                time.sleep(REQUEST_GAP_S)
            try:
                postings = FETCHERS[company.platform].fetch(company, client)
                results.append(BoardResult(company, postings))
            except (FetchError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                # One broken board is recorded and skipped; it never stops the run.
                results.append(BoardResult(company, error=f"{type(exc).__name__}: {exc}"))
        return results

    def check_companies(self, client: httpx.Client) -> list[tuple[Company, str]]:
        """(company, "ok: N 個職缺" or the error) for every company in the list."""
        out = []
        for company in self.radar_config().companies:
            try:
                n = len(FETCHERS[company.platform].fetch(company, client))
                out.append((company, f"ok：{n} 個職缺"))
            except (FetchError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                out.append((company, str(exc)))
        return out

    def matches(self, skip_ids: set[str] = frozenset()) -> list[Match]:
        """Active postings, evaluated and sorted best first (excluded ones last), minus those
        dismissed or in `skip_ids`. Evaluation is cached until a fetch or a config/profile edit."""
        with self._evaluating:
            key = self._cache_key()
            if self._cache is None or self._cache[0] != key:
                self._cache = (key, self._evaluate_all())
        hidden = self.store.dismissed() | set(skip_ids)
        return [m for m in self._cache[1] if m.id not in hidden]

    def _cache_key(self) -> tuple:
        run = self.store.last_run()
        # Only what my_skills reads: remembering an answer (answers_learned.yaml) or editing
        # applicant.yaml must not cost a ~4 s re-evaluation of every job.
        profile = self.cfg.profile_dir
        watched = [self.cfg.root / "config" / n for n in ("filters.yaml", "skills.yaml")]
        watched += [profile / "highlights.yaml", profile / "skills.yaml"]
        if (profile / "resumes").is_dir():
            watched += sorted((profile / "resumes").glob("*.pdf"))
        return (
            run and run["run_id"],
            tuple((str(p), p.stat().st_mtime) for p in watched if p.exists()),
        )

    def _evaluate_all(self) -> list[Match]:
        radar = self.radar_config()
        try:
            profile = load_profile(self.cfg.profile_dir)
            mine = my_skills(profile, self.cfg.profile_dir, radar.skills)
        except ProfileError:
            mine = set()
        matcher = Matcher(radar.filters, radar.skills, mine)
        now = utcnow()
        jobs = self.store.active()
        ats_ids = {j["id"] for j in jobs if j["platform"] in ATS_VALUES}
        also_on: dict[str, set[str]] = defaultdict(set)
        listed = []
        for job in jobs:
            if job["platform"] not in ATS_VALUES and job["ats_id"] in ats_ids:
                also_on[job["ats_id"]].add(job["platform"])  # shown as the ATS job instead
            else:
                listed.append(job)
        found = [matcher.evaluate(job, now) for job in listed]
        for m in found:
            m.also_on = sorted(also_on.get(m.id, ()))
        found.sort(key=lambda m: (bool(m.excluded), m.manual, -m.score, m.company, m.title))
        return merge_locations(found)


def merge_locations(matches: list[Match]) -> list[Match]:
    """One entry per company + title (the best-ranked one); the rest become other_locations."""
    best: dict[tuple[str, str], Match] = {}
    out = []
    for m in matches:
        key = (m.company.lower(), m.title.lower())
        if key in best:
            if m.location and m.location != best[key].location:
                best[key].other_locations.append(m.location)
            continue
        best[key] = m
        out.append(m)
    return out
