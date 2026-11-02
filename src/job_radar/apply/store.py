"""Application state: data/applications.duckdb plus one folder per job under data/applications/."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

import duckdb

from job_radar.apply.models import Application, AppStatus, FormState, JobRef, utcnow

log = logging.getLogger(__name__)

# Append-only: each entry upgrades the schema by one version. Never edit a shipped entry.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE applications (
        job_id VARCHAR PRIMARY KEY,
        status VARCHAR NOT NULL,
        job_snapshot JSON NOT NULL,
        resume_variant VARCHAR,
        llm_cost_usd DOUBLE NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL,
        applied_at TIMESTAMP,
        notes VARCHAR NOT NULL DEFAULT ''
    );
    CREATE TABLE application_events (
        job_id VARCHAR NOT NULL,
        from_status VARCHAR,
        to_status VARCHAR NOT NULL,
        occurred_at TIMESTAMP NOT NULL,
        note VARCHAR NOT NULL DEFAULT ''
    );
    """,
]

_COLUMNS = (
    "job_id, status, job_snapshot, resume_variant, llm_cost_usd, created_at, updated_at, "
    "applied_at, notes"
)


class Store:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.apps_dir = data_dir / "applications"
        self.apps_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._con = duckdb.connect(str(data_dir / "applications.duckdb"))
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def _migrate(self) -> None:
        with self._lock:
            self._con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
            row = self._con.execute("SELECT max(version) FROM schema_version").fetchone()
            current = row[0] or 0
            for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
                log.info("套用 applications 資料庫 migration v%d", version)
                self._con.execute("BEGIN")
                try:
                    self._con.execute(sql)
                    self._con.execute("INSERT INTO schema_version VALUES (?)", [version])
                    self._con.execute("COMMIT")
                except duckdb.Error:
                    self._con.execute("ROLLBACK")
                    raise

    # --- applications -------------------------------------------------------------

    def add(self, job: JobRef) -> tuple[Application, bool]:
        """Insert a job; returns (application, created). Existing jobs keep their status."""
        existing = self.get(job.job_id)
        if existing:
            if job.description_text and not existing.job.description_text:
                self.update_job(job)
                existing = self.get(job.job_id) or existing
            return existing, False
        now = utcnow()
        with self._lock:
            self._con.execute(
                f"INSERT INTO applications ({_COLUMNS}) VALUES (?, ?, ?, NULL, 0, ?, ?, NULL, '')",
                [job.job_id, AppStatus.QUEUED.value, job.model_dump_json(), now, now],
            )
            self._con.execute(
                "INSERT INTO application_events VALUES (?, NULL, ?, ?, 'added')",
                [job.job_id, AppStatus.QUEUED.value, now],
            )
        self.write_jd(job)
        app = self.get(job.job_id)
        assert app is not None
        return app, True

    def get(self, job_id: str) -> Application | None:
        with self._lock:
            row = self._con.execute(
                f"SELECT {_COLUMNS} FROM applications WHERE job_id = ?", [job_id]
            ).fetchone()
        return _to_app(row) if row else None

    def list(self) -> list[Application]:
        with self._lock:
            rows = self._con.execute(
                f"SELECT {_COLUMNS} FROM applications ORDER BY updated_at DESC"
            ).fetchall()
        return [_to_app(r) for r in rows]

    def update_job(self, job: JobRef) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE applications SET job_snapshot = ?, updated_at = ? WHERE job_id = ?",
                [job.model_dump_json(), utcnow(), job.job_id],
            )
        self.write_jd(job)

    def set_status(self, job_id: str, status: AppStatus, note: str = "") -> Application:
        app = self.get(job_id)
        if app is None:
            raise KeyError(job_id)
        now = utcnow()
        applied_at = now if status == AppStatus.APPLIED and app.applied_at is None else None
        with self._lock:
            self._con.execute(
                "UPDATE applications SET status = ?, updated_at = ?, "
                "applied_at = coalesce(applied_at, ?) WHERE job_id = ?",
                [status.value, now, applied_at, job_id],
            )
            if status != app.status or note:
                self._con.execute(
                    "INSERT INTO application_events VALUES (?, ?, ?, ?, ?)",
                    [job_id, app.status.value, status.value, now, note],
                )
        updated = self.get(job_id)
        assert updated is not None
        return updated

    def set_resume_variant(self, job_id: str, variant: str | None) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE applications SET resume_variant = ? WHERE job_id = ?", [variant, job_id]
            )

    def add_cost(self, job_id: str, usd: float) -> None:
        if usd <= 0:
            return
        with self._lock:
            self._con.execute(
                "UPDATE applications SET llm_cost_usd = llm_cost_usd + ? WHERE job_id = ?",
                [usd, job_id],
            )

    def events(self, job_id: str) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT from_status, to_status, occurred_at, note FROM application_events "
                "WHERE job_id = ? ORDER BY occurred_at, rowid",
                [job_id],
            ).fetchall()
        return [{"from": r[0], "to": r[1], "at": r[2], "note": r[3]} for r in rows]

    # --- per-job folder ---------------------------------------------------------

    def folder(self, job_id: str) -> Path:
        path = self.apps_dir / re.sub(r"[^\w.-]+", "_", job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_jd(self, job: JobRef) -> None:
        if not job.description_text:
            return
        header = f"# {job.title or job.job_id}\n\n{job.company} · {job.location}\n\n{job.url}\n\n"
        (self.folder(job.job_id) / "jd.md").write_text(
            header + job.description_text, encoding="utf-8"
        )

    def save_form(self, state: FormState) -> None:
        (self.folder(state.job_id) / "form.json").write_text(
            state.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_form(self, job_id: str) -> FormState | None:
        path = self.folder(job_id) / "form.json"
        if not path.exists():
            return None
        return FormState.model_validate_json(path.read_text(encoding="utf-8"))


def _to_app(row: tuple) -> Application:
    snapshot = row[2] if isinstance(row[2], dict) else json.loads(row[2])
    return Application(
        job=JobRef.model_validate(snapshot),
        status=AppStatus(row[1]),
        resume_variant=row[3],
        llm_cost_usd=row[4] or 0.0,
        created_at=row[5],
        updated_at=row[6],
        applied_at=row[7],
        notes=row[8] or "",
    )
