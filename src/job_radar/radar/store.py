"""data/jobs.duckdb: every posting seen, per-company fetch results, and runs.

Connections are opened per operation and retried while another process holds the file (the
scheduled fetch and the assistant's page both use it), so a write never blocks for long.
Postings missing from a board are closed only when that board was fetched successfully.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from job_radar.radar.models import Company, Posting
from job_radar.radar.sites import SearchResult

log = logging.getLogger(__name__)

# Append-only: each entry upgrades the schema by one version. Never edit a shipped entry.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE jobs (
        id VARCHAR PRIMARY KEY,
        platform VARCHAR NOT NULL,
        company VARCHAR NOT NULL,
        token VARCHAR NOT NULL,
        title VARCHAR NOT NULL,
        location VARCHAR NOT NULL DEFAULT '',
        url VARCHAR NOT NULL,
        apply_url VARCHAR NOT NULL,
        description VARCHAR NOT NULL DEFAULT '',
        content_hash VARCHAR NOT NULL,
        remote BOOLEAN,
        posted_at TIMESTAMP,
        first_seen_at TIMESTAMP NOT NULL,
        last_seen_at TIMESTAMP NOT NULL,
        content_changed_at TIMESTAMP NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        closed_at TIMESTAMP,
        is_baseline BOOLEAN NOT NULL DEFAULT FALSE
    );
    CREATE TABLE fetch_results (
        run_id VARCHAR NOT NULL,
        company VARCHAR NOT NULL,
        platform VARCHAR NOT NULL,
        token VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        job_count INTEGER NOT NULL DEFAULT 0,
        error VARCHAR NOT NULL DEFAULT '',
        fetched_at TIMESTAMP NOT NULL
    );
    CREATE TABLE runs (
        run_id VARCHAR PRIMARY KEY,
        command VARCHAR NOT NULL,
        started_at TIMESTAMP NOT NULL,
        finished_at TIMESTAMP,
        stats JSON
    );
    CREATE TABLE dismissed (
        id VARCHAR PRIMARY KEY,
        dismissed_at TIMESTAMP NOT NULL
    );
    """,
    """
    ALTER TABLE jobs ADD COLUMN seniority VARCHAR DEFAULT '';
    ALTER TABLE jobs ADD COLUMN ats_id VARCHAR;
    CREATE TABLE company_boards (
        company_key VARCHAR PRIMARY KEY,
        company VARCHAR NOT NULL,
        platform VARCHAR,
        token VARCHAR,
        checked_at TIMESTAMP NOT NULL
    );
    """,
]

LOCK_WAIT_S = 20
SUSPECT_MIN_PREVIOUS = 5  # 0 jobs now after ≥ 5 last time looks like a broken board, not a purge
SEARCH_EXPIRY_DAYS = 14  # a job-site result not seen again for this long is treated as gone


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC).replace(tzinfo=None) if value and value.tzinfo else value


@dataclass
class BoardResult:
    company: Company
    postings: list[Posting] = field(default_factory=list)
    error: str = ""


@dataclass
class RunStats:
    run_id: str
    new: int = 0
    updated: int = 0
    closed: int = 0
    reopened: int = 0
    ok: int = 0
    failed: list[str] = field(default_factory=list)
    suspect: list[str] = field(default_factory=list)


# DuckDB lets a process open a database file only once at a time: a fetch thread and a page
# request (or the resolver's worker threads) opening it together fail with "already attached".
_FILE_LOCKS: dict[Path, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _file_lock(path: Path) -> threading.RLock:
    with _FILE_LOCKS_GUARD:
        return _FILE_LOCKS.setdefault(path.resolve(), threading.RLock())


class RadarStore:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "jobs.duckdb"
        self._lock = _file_lock(self.path)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:  # other threads of this process wait; other processes retry below
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    con = duckdb.connect(str(self.path))
                    break
                except duckdb.IOException as exc:
                    if "lock" not in str(exc).lower() or time.monotonic() > deadline:
                        raise
                    time.sleep(0.5)
            try:
                yield con
            finally:
                con.close()

    def _migrate(self) -> None:
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
            current = con.execute("SELECT max(version) FROM schema_version").fetchone()[0] or 0
            for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
                log.info("套用 jobs 資料庫 migration v%d", version)
                con.execute("BEGIN")
                con.execute(sql)
                con.execute("INSERT INTO schema_version VALUES (?)", [version])
                con.execute("COMMIT")

    # --- writing a run ------------------------------------------------------------

    def record_run(
        self,
        command: str,
        results: list[BoardResult],
        started: datetime,
        searches: list[SearchResult] = (),
    ) -> RunStats:
        stats = RunStats(run_id=uuid.uuid4().hex[:12])
        now = utcnow()
        with self._connect() as con:
            con.execute("BEGIN")
            for result in results:
                self._record_board(con, stats, result, now)
            for search in searches:
                self._record_search(con, stats, search, now)
            con.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                [stats.run_id, command, started, now, json.dumps(stats.__dict__)],
            )
            con.execute("COMMIT")
        return stats

    def _record_board(self, con, stats: RunStats, result: BoardResult, now: datetime) -> None:
        company = result.company
        platform = company.platform.value
        previous = self._previous_count(con, platform, company.token)
        status, error = "ok", result.error
        if error:
            status = "error"
            stats.failed.append(f"{company.name}：{error}")
        elif not result.postings and previous and previous >= SUSPECT_MIN_PREVIOUS:
            status, error = "suspect", f"這次 0 筆（上次 {previous} 筆）"
            stats.suspect.append(company.name)
        self._fetch_result(con, stats, company.name, platform, company.token, status, result, now)
        if status != "ok":
            return
        stats.ok += 1
        # The first fetch of a board is its baseline, not "new" in reports. A posting missing
        # from a board that was fetched successfully has been taken down.
        self._upsert(con, stats, platform, company.token, result.postings, now, previous is None)
        self._close(con, stats, platform, company.token, {p.id for p in result.postings}, now)

    def _record_search(self, con, stats: RunStats, result: SearchResult, now: datetime) -> None:
        """Job-site results are a moving window: keep what was found (even when the search
        stopped early) and expire postings only after they go unseen for a while."""
        platform = result.platform.value
        previous = self._previous_count(con, platform, "")
        status = "error" if result.error else "ok"
        if result.error:
            stats.failed.append(f"{platform}：{result.error}")
        else:
            stats.ok += 1
        self._fetch_result(con, stats, platform, platform, "", status, result, now)
        self._upsert(con, stats, platform, "", result.postings, now, previous is None)
        con.execute(
            "UPDATE jobs SET is_active = FALSE, closed_at = ? WHERE platform = ? AND is_active"
            f" AND last_seen_at < ? - INTERVAL {SEARCH_EXPIRY_DAYS} DAY",
            [now, platform, now],
        )

    def _previous_count(self, con, platform: str, token: str) -> int | None:
        row = con.execute(
            "SELECT job_count FROM fetch_results WHERE platform = ? AND token = ? AND status = 'ok'"
            " ORDER BY fetched_at DESC LIMIT 1",
            [platform, token],
        ).fetchone()
        return row[0] if row else None

    def _fetch_result(self, con, stats, name, platform, token, status, result, now) -> None:
        con.execute(
            "INSERT INTO fetch_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                stats.run_id,
                name,
                platform,
                token,
                status,
                len(result.postings),
                result.error or ("" if status == "ok" else status),
                now,
            ],
        )

    def _upsert(self, con, stats, platform, token, postings, now, baseline: bool) -> None:
        existing = {
            row[0]: (row[1], row[2])
            for row in con.execute(
                "SELECT id, content_hash, is_active FROM jobs WHERE platform = ? AND token = ?",
                [platform, token],
            ).fetchall()
        }
        fresh = [p for p in postings if p.id not in existing]
        if fresh:
            con.executemany(
                "INSERT INTO jobs (id, platform, company, token, title, location, url, apply_url,"
                " description, content_hash, remote, posted_at, first_seen_at, last_seen_at,"
                " content_changed_at, is_active, closed_at, is_baseline, seniority)"
                f" VALUES ({', '.join(['?'] * 15)}, TRUE, NULL, ?, ?) ON CONFLICT DO NOTHING",
                [
                    [
                        p.id,
                        platform,
                        p.company,
                        p.token,
                        p.title,
                        p.location,
                        p.url,
                        p.apply_url,
                        p.description,
                        p.content_hash,
                        p.remote,
                        _naive(p.posted_at),
                        now,
                        now,
                        now,
                        baseline,
                        p.seniority,
                    ]
                    for p in fresh
                ],
            )
        stats.new += 0 if baseline else len(fresh)
        for p in postings:
            if p.id not in existing:
                continue
            old_hash, active = existing[p.id]
            if old_hash == p.content_hash and active:
                continue
            stats.updated += old_hash != p.content_hash
            stats.reopened += not active
            con.execute(
                "UPDATE jobs SET company = ?, title = ?, location = ?, url = ?, apply_url = ?,"
                " description = ?, content_hash = ?, remote = ?, seniority = ?,"
                " posted_at = coalesce(?, posted_at), content_changed_at = ?,"
                " is_active = TRUE, closed_at = NULL WHERE id = ?",
                [
                    p.company,
                    p.title,
                    p.location,
                    p.url,
                    p.apply_url,
                    p.description,
                    p.content_hash,
                    p.remote,
                    p.seniority,
                    _naive(p.posted_at),
                    now,
                    p.id,
                ],
            )
        seen = [p.id for p in postings]
        con.execute("UPDATE jobs SET last_seen_at = ? WHERE list_contains(?, id)", [now, seen])

    def _close(self, con, stats, platform: str, token: str, seen: set[str], now) -> None:
        active = con.execute(
            "SELECT id FROM jobs WHERE platform = ? AND token = ? AND is_active", [platform, token]
        ).fetchall()
        closed = [row[0] for row in active if row[0] not in seen]
        if closed:
            con.execute(
                "UPDATE jobs SET is_active = FALSE, closed_at = ? WHERE list_contains(?, id)",
                [now, closed],
            )
        stats.closed += len(closed)

    def link_ats(self, links: dict[str, str]) -> None:
        """Point job-site postings at the ATS job they were matched to."""
        if not links:
            return
        with self._connect() as con:
            con.executemany(
                "UPDATE jobs SET ats_id = ? WHERE id = ?",
                [[ats, job] for job, ats in links.items()],
            )

    # --- company ATS boards (found from job-site company names) ---------------------

    def board_lookup(self, company_key: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT company, platform, token, checked_at FROM company_boards"
                " WHERE company_key = ?",
                [company_key],
            ).fetchone()
        return (
            dict(zip(("company", "platform", "token", "checked_at"), row, strict=True))
            if row
            else None
        )

    def save_board(
        self, company_key: str, company: str, platform: str | None, token: str | None
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO company_boards VALUES (?, ?, ?, ?, ?) ON CONFLICT (company_key) DO"
                " UPDATE SET company = excluded.company, platform = excluded.platform,"
                " token = excluded.token, checked_at = excluded.checked_at",
                [company_key, company, platform, token, utcnow()],
            )

    def found_boards(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT company, platform, token FROM company_boards WHERE platform IS NOT NULL"
                " ORDER BY company"
            ).fetchall()
        return [dict(zip(("company", "platform", "token"), r, strict=True)) for r in rows]

    # --- reading ----------------------------------------------------------------------

    def active(self) -> list[dict]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT id, platform, company, token, title, location, url, apply_url, description,"
                " remote, posted_at, first_seen_at, is_baseline, seniority, ats_id FROM jobs"
                " WHERE is_active"
            )
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    def dismissed(self) -> set[str]:
        with self._connect() as con:
            return {row[0] for row in con.execute("SELECT id FROM dismissed").fetchall()}

    def dismiss(self, job_id: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO dismissed VALUES (?, ?) ON CONFLICT DO NOTHING", [job_id, utcnow()]
            )

    def last_run(self) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                # Boards fetched while matching job-site postings are not a run of their own.
                "SELECT run_id, finished_at, stats FROM runs WHERE command != 'discover'"
                " ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {"run_id": row[0], "finished_at": row[1], **json.loads(row[2] or "{}")}
