"""Local web UI for the application assistant.

Bound to 127.0.0.1 only. Every API call must carry the per-session token embedded in the
page, so other websites open in your browser cannot drive this server (no CORS is enabled,
and the token cannot be read cross-origin). TrustedHostMiddleware blocks DNS rebinding.
Pages may not be framed by websites: `/panel` only inside the Chrome side-panel extension.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from job_radar.apply.models import AppStatus
from job_radar.apply.service import ApplyError, ApplyService, ConfirmedAnswer
from job_radar.radar.match import NEW_DAYS
from job_radar.radar.service import RadarService

log = logging.getLogger(__name__)


class AddRequest(BaseModel):
    urls: str


class PrefillRequest(BaseModel):
    resume_variant: str | None = None


class FillRequest(BaseModel):
    answers: list[ConfirmedAnswer]


class StatusRequest(BaseModel):
    status: AppStatus
    note: str = ""


class TabRequest(BaseModel):
    url: str


class DismissRequest(BaseModel):
    id: str


class CompanyRequest(BaseModel):
    name: str
    platform: str
    token: str


def create_app(
    service: ApplyService,
    token: str | None = None,
    home_url: str | None = None,
    show_on_start: bool = False,
    radar: RadarService | None = None,
    fetch_due_at: tuple[int, int] | None = None,
) -> FastAPI:
    """`home_url` is where this server is reachable; with `show_on_start` the main page opens
    in the controlled Chrome as soon as the server accepts connections. With `fetch_due_at`
    (the daily fetch time), starting up makes up a daily fetch the Mac missed."""
    token = token or secrets.token_urlsafe(24)
    web_root = resources.files("job_radar.web")
    radar = radar or RadarService(service.cfg)
    background: set[asyncio.Task] = set()

    async def show_when_ready() -> None:
        host, port = home_url.split("//", 1)[1].rstrip("/").rsplit(":", 1)
        for _ in range(100):
            try:
                _, writer = await asyncio.open_connection(host, int(port))
            except OSError:
                await asyncio.sleep(0.1)
                continue
            writer.close()
            break
        try:
            await service.show_home(home_url)
        except ApplyError as exc:
            log.error("%s", exc)

    async def warm_radar() -> None:
        # Ranking every job takes seconds; do it before anyone opens 推薦職缺.
        try:
            await run_in_threadpool(radar.matches)
        except Exception:  # the page request will retry and report it
            log.exception("預先計算推薦職缺失敗")

    async def fetch_jobs() -> None:
        try:
            await run_in_threadpool(radar.fetch, None, "ui")
        except RuntimeError as exc:
            log.warning("%s", exc)
        await warm_radar()

    def in_background(coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)
        return task

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(show_when_ready()) if show_on_start and home_url else None
        # Opening the assistant makes up a missed daily fetch (the Mac was off at 08:30).
        stale = fetch_due_at is not None and await run_in_threadpool(radar.stale, fetch_due_at)
        warming = in_background(fetch_jobs() if stale else warm_radar())
        yield
        # Let a warm-up still running in its thread finish before the process exits.
        await asyncio.wait({warming}, timeout=10)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await service.close()

    app = FastAPI(title="Job Radar 申請助手", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.mount("/static", StaticFiles(directory=str(web_root / "static")), name="static")

    def require_token(x_jr_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_jr_token, token):
            raise HTTPException(status_code=403, detail="token 不符：請重新整理頁面")

    @app.exception_handler(ApplyError)
    async def apply_error(_: Request, exc: ApplyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # The controlled Chrome keeps its cache across runs and would keep an old app.js for days
    # (heuristic freshness), so pages and assets are revalidated and script URLs carry a
    # version that changes with their content.
    static_dir = web_root / "static"
    version = hashlib.sha256(
        b"".join(f.read_bytes() for f in sorted(static_dir.iterdir(), key=lambda f: f.name))
    ).hexdigest()[:10]

    @app.middleware("http")
    async def no_stale_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith(("/static/", "/panel")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    def page(name: str, frame_ancestors: str) -> HTMLResponse:
        html = (web_root / "templates" / name).read_text("utf-8")
        html = html.replace("__JR_TOKEN__", token).replace("__JR_VERSION__", version)
        csp = f"frame-ancestors {frame_ancestors}"
        return HTMLResponse(html, headers={"Content-Security-Policy": csp})

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return page("index.html", "'none'")

    @app.get("/panel", response_class=HTMLResponse)
    async def panel() -> HTMLResponse:
        return page("panel.html", "chrome-extension:")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    api = [Depends(require_token)]

    @app.post("/api/show", dependencies=api)
    async def show() -> dict:
        if not home_url:
            raise HTTPException(status_code=404, detail="沒有設定首頁網址")
        await service.show_home(home_url)
        return {"ok": True}

    @app.get("/api/tab", dependencies=api)
    async def tab(url: str) -> dict:
        return {"job_id": service.job_for_url(url)}

    @app.post("/api/tab/adopt", dependencies=api)
    async def adopt(body: TabRequest) -> dict:
        app_ = await service.adopt_tab(body.url)
        return {"job_id": app_.job.job_id}

    @app.get("/api/status", dependencies=api)
    async def status() -> dict:
        return service.profile_status()

    @app.get("/api/applications", dependencies=api)
    async def list_applications() -> list[dict]:
        return [
            {
                **a.model_dump(mode="json", exclude={"job": {"description_text", "ats_questions"}}),
                "page_open": service.page_open(a.job.job_id),
            }
            for a in service.list_applications()
        ]

    @app.post("/api/applications", dependencies=api)
    async def add_applications(body: AddRequest) -> dict:
        added, errors = await run_in_threadpool(service.add_urls, body.urls)
        return {"added": [a.job.job_id for a in added], "errors": errors}

    @app.get("/api/applications/{job_id}", dependencies=api)
    async def detail(job_id: str) -> dict:
        data = service.detail(job_id)
        app_dump = data["application"].model_dump(mode="json", exclude={"job": {"ats_questions"}})
        form = data["form"].model_dump(mode="json") if data["form"] else None
        return {**data, "application": app_dump, "form": form}

    @app.post("/api/applications/{job_id}/open", dependencies=api)
    async def open_job(job_id: str) -> dict:
        app_ = await service.open(job_id)
        return {"ok": True, "title": app_.job.title}

    @app.post("/api/applications/{job_id}/prefill", dependencies=api)
    async def prefill(job_id: str, body: PrefillRequest) -> dict:
        state = await service.prefill(job_id, body.resume_variant)
        return state.model_dump(mode="json")

    @app.post("/api/applications/{job_id}/fill", dependencies=api)
    async def fill(job_id: str, body: FillRequest) -> dict:
        state = await service.fill_confirmed(job_id, body.answers)
        return state.model_dump(mode="json")

    @app.get("/api/radar", dependencies=api)
    async def radar_list(limit: int = 60, manual_limit: int = 30) -> dict:
        applied = {a.job.job_id for a in service.list_applications()}
        matches = await run_in_threadpool(radar.matches, applied)
        picked = [m for m in matches if not m.excluded]
        fillable = [m for m in picked if not m.manual]
        manual = [m for m in picked if m.manual]
        return {
            "fetching": radar.fetching,
            "last_run": await run_in_threadpool(radar.store.last_run),
            "total": len(matches),
            "recommended": len(picked),
            "items": [m.__dict__ for m in fillable[:limit]],
            "manual": [m.__dict__ for m in manual[:manual_limit]],
            "manual_total": len(manual),
            "new_recommended": sum(m.is_new for m in picked),
            "new_days": NEW_DAYS,
            "found_companies": await run_in_threadpool(radar.found_companies),
        }

    @app.post("/api/radar/fetch", dependencies=api)
    async def radar_fetch() -> dict:
        if radar.fetching:
            return {"started": False}

        in_background(fetch_jobs())
        return {"started": True}

    @app.post("/api/radar/companies", dependencies=api)
    async def radar_add_company(body: CompanyRequest) -> dict:
        try:
            await run_in_threadpool(radar.add_company, body.name, body.platform, body.token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"公司資料不正確：{exc}") from exc
        return {"ok": True}

    @app.post("/api/radar/dismiss", dependencies=api)
    async def radar_dismiss(body: DismissRequest) -> dict:
        await run_in_threadpool(radar.store.dismiss, body.id)
        return {"ok": True}

    @app.post("/api/applications/{job_id}/status", dependencies=api)
    async def set_status(job_id: str, body: StatusRequest) -> dict:
        app_ = service.set_status(job_id, body.status, body.note)
        return app_.model_dump(mode="json", exclude={"job": {"description_text", "ats_questions"}})

    return app
