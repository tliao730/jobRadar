"""Command-line entry point: `job-radar ...`."""

from __future__ import annotations

import logging
import os
import secrets
import shutil
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from job_radar.apply.models import AppStatus
from job_radar.config import AppConfig, has_anthropic_credential, load_config

app = typer.Typer(help="Job Radar：申請助手與職缺追蹤", no_args_is_help=True)
apply_app = typer.Typer(help="申請助手", no_args_is_help=True)
app.add_typer(apply_app, name="apply")
console = Console()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="顯示除錯訊息")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, markup=False)],
    )
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _service(cfg: AppConfig, extension_dir: Path | None = None):
    from job_radar.apply.service import ApplyService
    from job_radar.apply.store import Store
    from job_radar.llm import AnthropicLLM
    from job_radar.prefill.browser import BrowserManager

    llm = None
    if has_anthropic_credential():
        llm = AnthropicLLM(
            model=cfg.env.tailor_model,
            effort=cfg.llm.effort,
            max_tokens=cfg.llm.max_tokens,
            prices=cfg.llm.prices,
            fallbacks=cfg.llm.fallbacks,
        )
    else:
        logging.getLogger(__name__).info("沒有 Anthropic 金鑰：只填答案庫，不產生草稿")
    browser = BrowserManager(
        cfg.browser_profile_dir, cfg.browser.channel, extension_dir=extension_dir
    )
    return ApplyService(cfg, Store(cfg.data_dir), browser, llm)


def _show_running(cfg: AppConfig) -> bool:
    """If an assistant is already running, bring its window forward and return True."""
    import httpx

    from job_radar.desktop import read_session

    session = read_session(cfg.data_dir)
    if session is None:
        return False
    base = f"http://{cfg.ui.host}:{session.port}"
    try:
        httpx.get(f"{base}/healthz", timeout=1).raise_for_status()
        httpx.post(f"{base}/api/show", headers={"X-JR-Token": session.token}, timeout=30)
    except httpx.HTTPError:
        return False
    return True


@app.command()
def ui(
    port: int | None = typer.Option(None, help="埠號（預設讀 config/settings.yaml）"),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="在程式控制的 Chrome 開啟主頁；關掉那個視窗即結束"
    ),
) -> None:
    """啟動申請助手（已在執行時，把視窗叫回前面）。"""
    import uvicorn

    from job_radar.desktop import Session, prepare_extension, remove_session, write_session
    from job_radar.web.app import create_app

    cfg = load_config()
    if _show_running(cfg):
        console.print("申請助手已在執行，已切換到它的視窗。")
        return
    port = port or cfg.ui.port
    url = f"http://{cfg.ui.host}:{port}/"
    token = secrets.token_urlsafe(24)
    service = _service(cfg, extension_dir=prepare_extension(cfg.data_dir, url.rstrip("/")))
    web = create_app(
        service,
        token=token,
        home_url=url,
        show_on_start=open_browser,
        fetch_due_at=daily_fetch_time(),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            web, host=cfg.ui.host, port=port, log_level="warning", timeout_graceful_shutdown=5
        )
    )
    if open_browser:
        service.browser.on_close = lambda: setattr(server, "should_exit", True)
    write_session(cfg.data_dir, Session(port=port, token=token, pid=os.getpid()))
    console.print(f"申請助手：[bold]{url}[/bold]（關掉 Job Radar 的 Chrome 視窗或按 Ctrl+C 結束）")
    try:
        server.run()
    finally:
        remove_session(cfg.data_dir, token)


@app.command("install-app")
def install_app(
    dock: bool = typer.Option(True, "--dock/--no-dock", help="同時加到 Dock"),
) -> None:
    """建立 ~/Applications/Job Radar.app（點一下就啟動申請助手）。"""
    from job_radar.desktop import add_to_dock
    from job_radar.desktop import install_app as build

    uv = shutil.which("uv")
    if uv is None:
        console.print("[red]找不到 uv，請先安裝 uv[/red]")
        raise typer.Exit(1)
    cfg = load_config()
    app_path = build(cfg.root, Path(uv).resolve(), Path.home() / "Applications")
    console.print(f"已建立 {app_path}")
    if dock:
        added = add_to_dock(app_path)
        console.print("已加到 Dock。" if added else "Dock 上已經有了。")


@app.command("init-profile")
def init_profile() -> None:
    """建立 profile/ 範本（已存在的檔案不會被覆蓋）。"""
    cfg = load_config()
    target = cfg.profile_dir
    (target / "resumes").mkdir(parents=True, exist_ok=True)
    templates = resources.files("job_radar.profile_templates")
    personal_radar = ("filters.yaml", "sources.yaml", "companies.yaml")  # over config/
    for name in ("applicant.yaml", "highlights.yaml", *personal_radar):
        dest = target / name
        if dest.exists():
            console.print(f"保留既有的 {dest}")
            continue
        with resources.as_file(templates / name) as src:
            shutil.copy(src, dest)
        console.print(f"已建立 {dest}")
    console.print(
        f"\n下一步：\n  1. 填寫 {target / 'applicant.yaml'}\n"
        f"  2. 把履歷 PDF 放進 {target / 'resumes'}（檔名就是版本名稱，例如 ds.pdf、mle.pdf）\n"
        f"  3. 在 {target / 'highlights.yaml'} 寫下經歷素材\n"
        f"  4. 要找的層級、職務、公司跟共用設定不同時，改 {target} 裡的 filters.yaml、"
        "sources.yaml、companies.yaml\n"
        "  5. uv run job-radar ui"
    )


@apply_app.command("add")
def apply_add(urls: list[str]) -> None:
    """把職缺網址加入申請清單。"""
    import httpx

    from job_radar.apply.intake import USER_AGENT, IntakeError, fetch_job_details, parse_job_url
    from job_radar.apply.store import Store

    cfg = load_config()
    store = Store(cfg.data_dir)
    with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
        for url in urls:
            try:
                job = fetch_job_details(parse_job_url(url), client)
            except IntakeError as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            app_, created = store.add(job)
            verb = "已加入" if created else "已存在"
            console.print(f"{verb} {app_.job.job_id}：{app_.job.company} {app_.job.title}")
    store.close()


@apply_app.command("list")
def apply_list() -> None:
    """列出申請清單。"""
    from job_radar.apply.store import Store

    store = Store(load_config().data_dir)
    table = Table("job_id", "狀態", "公司", "職稱", "更新時間 (UTC)")
    for a in store.list():
        table.add_row(
            a.job.job_id,
            a.status.value,
            a.job.company,
            a.job.title,
            a.updated_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
    store.close()


@app.command()
def track(job_id: str, status: AppStatus, note: str = typer.Option("", help="備註")) -> None:
    """更新申請狀態，例如：job-radar track greenhouse:123 interviewing"""
    from job_radar.apply.store import Store

    store = Store(load_config().data_dir)
    try:
        app_ = store.set_status(job_id, status, note)
    except KeyError:
        console.print(f"[red]找不到 {job_id}[/red]")
        raise typer.Exit(1) from None
    finally:
        store.close()
    console.print(f"{app_.job.job_id} → {app_.status.value}")


# --- job radar ---------------------------------------------------------------------


def daily_fetch_time() -> tuple[int, int]:
    """When the daily fetch is due: the installed schedule's time, else 08:30."""
    from job_radar.desktop import scheduled_time
    from job_radar.radar.service import DAILY_AT

    return scheduled_time(Path.home() / "Library" / "LaunchAgents") or DAILY_AT


@app.command()
def fetch(
    if_stale: bool = typer.Option(
        False, "--if-stale", help="最近一次排程時間（例如今天 08:30）之後已經抓過就略過"
    ),
) -> None:
    """抓取公司清單（config/ 與 profile/ 的 companies.yaml）每家公司的職缺（ATS 公開 API）。"""
    from job_radar.radar.service import RadarService

    radar = RadarService(load_config())
    if if_stale:
        hour, minute = daily_fetch_time()
        if not radar.stale((hour, minute)):
            logging.getLogger(__name__).info("%02d:%02d 之後已經抓過，略過", hour, minute)
            return
    stats = radar.fetch()
    console.print(
        f"成功 {stats.ok} 個職缺板：新增 {stats.new}、更新 {stats.updated}、下架 {stats.closed}"
    )
    for failure in stats.failed:
        console.print(f"[red]失敗[/red] {failure}")
    for name in stats.suspect:
        console.print(f"[yellow]可疑[/yellow] {name}：這次 0 筆，沒有據此下架")


@app.command("check-companies")
def check_companies() -> None:
    """逐一驗證公司清單（config/ 與 profile/ 的 companies.yaml）的公司代號。"""
    import httpx

    from job_radar.apply.intake import USER_AGENT
    from job_radar.radar.service import RadarService

    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        for company, result in RadarService(load_config()).check_companies(client):
            color = "green" if result.startswith("ok") else "red"
            console.print(
                f"{company.name}（{company.platform}/{company.token}）[{color}]{result}[/]"
            )


@app.command()
def radar(
    limit: int = typer.Option(20, help="顯示幾筆"),
    show_excluded: bool = typer.Option(False, "--excluded", help="也列出被排除的職缺與原因"),
) -> None:
    """列出最適合的職缺（排除已在申請清單裡的）。"""
    from job_radar.apply.store import Store
    from job_radar.radar.service import RadarService

    cfg = load_config()
    store = Store(cfg.data_dir)
    applied = {a.job.job_id for a in store.list()}
    store.close()
    matches = RadarService(cfg).matches(skip_ids=applied)
    shown = [m for m in matches if show_excluded or not m.excluded][:limit]
    table = Table("分數", "公司", "職稱", "地點", "符合技能", "排除原因")
    for m in shown:
        table.add_row(
            str(m.score),
            m.company,
            m.title,
            m.location[:30],
            ", ".join(m.matched_skills[:5]),
            m.excluded,
        )
    console.print(table)
    console.print(f"推薦 {sum(not m.excluded for m in matches)} / 共 {len(matches)} 個職缺")


@app.command("install-schedule")
def install_schedule(
    time_of_day: str = typer.Option("08:30", "--at", help="每天幾點抓取（HH:MM，本地時間）"),
    remove: bool = typer.Option(False, "--remove", help="取消每日抓取"),
) -> None:
    """每天自動執行 `job-radar fetch`（macOS launchd；錯過的在醒來、登入或打開助手時補抓）。"""
    from job_radar.desktop import install_schedule as install
    from job_radar.desktop import remove_schedule

    agents = Path.home() / "Library" / "LaunchAgents"
    if remove:
        console.print("已取消每日抓取。" if remove_schedule(agents) else "本來就沒有設定。")
        return
    hour, minute = (int(x or 0) for x in time_of_day.partition(":")[::2])
    uv = shutil.which("uv")
    if uv is None:
        console.print("[red]找不到 uv，請先安裝 uv[/red]")
        raise typer.Exit(1)
    plist = install(load_config().root, Path(uv).resolve(), hour, minute, agents)
    console.print(f"每天 {hour:02d}:{minute:02d} 抓取職缺（{plist}），紀錄在 data/logs/fetch.log")


@app.command()
def inspect(
    url: str,
    fill: bool = typer.Option(False, "--fill", help="也實際填寫自動那一輪（不會送出）"),
    headed: bool = typer.Option(False, "--headed", help="開有畫面的 Chrome"),
) -> None:
    """在暫時的 Chrome 開一個申請頁，列出每個欄位的區塊、分類與答案（除錯用，不會送出）。"""
    import asyncio
    import tempfile

    import httpx

    from job_radar.apply.classify import classify, enrich_options
    from job_radar.apply.intake import USER_AGENT, IntakeError, fetch_job_details, parse_job_url
    from job_radar.apply.models import Category
    from job_radar.prefill import scanner
    from job_radar.prefill.browser import BrowserManager
    from job_radar.prefill.filler import fill_answers
    from job_radar.profile import load_profile

    cfg = load_config()
    profile = load_profile(cfg.profile_dir)
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
            job = fetch_job_details(parse_job_url(url), client)
    except IntakeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    resume = next(iter(profile.resume_variants().values()), None)

    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = BrowserManager(Path(tmp), cfg.browser.channel, headless=not headed)
            try:
                page = await browser.open("inspect", job.apply_url)
                await scanner.settle(page)
                blockers, notices = await scanner.detect(page)
                ready = await scanner.wait_until_interactive(page)
                console.print(f"{page.url}\n可互動：{ready}  阻擋：{blockers}  提醒：{notices}")
                fields = enrich_options(await scanner.scan_fields(page), job.ats_questions)
                decided, remaining = classify(fields, profile, resume_available=resume is not None)
                if fill and ready:
                    auto = [a for a in decided if a.category == Category.AUTO]
                    done = {
                        a.field.field_id: a
                        for a in await fill_answers(page, auto, resume_path=resume, overwrite=False)
                    }
                    decided = [done.get(a.field.field_id, a) for a in decided]
                table = Table("區塊", "題目", "類型", "分類", "答案", "結果")
                by_id = {a.field.field_id: a for a in decided}
                for f in fields:
                    a = by_id.get(f.field_id)
                    category = a.category.value if a else "（交給草稿）"
                    value = a.value if a else ""
                    value = "; ".join(value) if isinstance(value, list) else value
                    result = ("✓" if a.filled else a.error or a.note) if a else ""
                    table.add_row(
                        f.section[:16],
                        f.label[:50],
                        f.kind.value,
                        category,
                        str(value)[:30],
                        result[:50],
                    )
                console.print(table)
            finally:
                await browser.close()

    asyncio.run(run())
