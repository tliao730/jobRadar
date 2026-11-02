"""One headed, persistent Chrome window shared by all applications.

The profile directory persists cookies, so a site you log in to once (by hand) stays
logged in. Each job gets its own tab; if a tab opens a popup (e.g. "Apply on company
site"), the popup becomes that job's current page. The assistant's own page can live in the
same window (`show`), with the side-panel extension loaded next to the job tabs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

log = logging.getLogger(__name__)

ACTION_TIMEOUT_MS = 10_000  # keeps the UI responsive when an element never becomes ready


class BrowserError(RuntimeError):
    """The browser could not be started or a page could not be opened."""


class BrowserManager:
    def __init__(
        self,
        user_data_dir: Path,
        channel: str | None,
        headless: bool = False,
        extension_dir: Path | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._user_data_dir = user_data_dir
        self._channel = channel
        self._headless = headless
        self._extension_dir = extension_dir
        self.on_close = on_close
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._pages: dict[str, list[Page]] = {}
        self._lock = asyncio.Lock()

    async def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        self._user_data_dir.mkdir(parents=True, exist_ok=True)
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        extension = {}
        if self._extension_dir:
            # Chrome no longer honours --load-extension; CDP's Extensions.loadUnpacked needs this.
            extension = {
                "ignore_default_args": ["--disable-extensions"],
                "args": ["--enable-unsafe-extension-debugging"],
            }
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self._user_data_dir),
                channel=self._channel,
                headless=self._headless,
                no_viewport=True,
                **extension,
            )
        except PlaywrightError as exc:
            hint = (
                "請確認已安裝 Google Chrome，或在 config/settings.yaml 把 browser.channel "
                "設為 null 並執行 `uv run playwright install chromium`"
                if self._channel
                else "請執行 `uv run playwright install chromium`"
            )
            raise BrowserError(f"無法啟動瀏覽器：{hint}") from exc
        self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        self._context.on("close", lambda _: self._forget_context())
        # On macOS, closing the last window leaves Chrome running; treat "no tabs" as closed.
        for existing in self._context.pages:
            existing.on("close", self._on_page_closed)
        self._context.on("page", lambda page: page.on("close", self._on_page_closed))
        if self._extension_dir:
            await self._load_extension(self._context)
        return self._context

    async def _load_extension(self, context: BrowserContext) -> None:
        try:
            cdp = await context.browser.new_browser_cdp_session()  # type: ignore[union-attr]
            await cdp.send("Extensions.loadUnpacked", {"path": str(self._extension_dir)})
        except (PlaywrightError, AttributeError) as exc:
            log.warning("無法載入側邊欄擴充功能（申請助手其他功能不受影響）：%s", exc)

    def _on_page_closed(self, _: Page) -> None:
        context = self._context
        if context is not None and not context.pages:
            log.info("所有分頁都已關閉")
            asyncio.get_running_loop().create_task(self._close_context(context))

    async def _close_context(self, context: BrowserContext) -> None:
        with contextlib.suppress(PlaywrightError):
            await context.close()

    def _forget_context(self) -> None:
        log.info("瀏覽器視窗已關閉")
        self._context = None
        self._pages.clear()
        if self.on_close:
            self.on_close()

    def _track(self, key: str, page: Page) -> None:
        self._pages.setdefault(key, []).append(page)
        page.on("popup", lambda popup: self._track(key, popup))

    async def open(self, key: str, url: str) -> Page:
        async with self._lock:
            context = await self._ensure_context()
            page = self.current_page(key)
            if page is None:
                page = await context.new_page()
                self._track(key, page)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightError as exc:
                raise BrowserError(f"無法開啟 {url}：{exc.message.splitlines()[0]}") from exc
            await page.bring_to_front()
            return page

    async def show(self, url: str) -> None:
        """Bring the assistant's own page (`url`) to the front, opening it if needed."""
        async with self._lock:
            context = await self._ensure_context()
            tracked = {id(p) for pages in self._pages.values() for p in pages}
            free = [p for p in context.pages if id(p) not in tracked and not p.is_closed()]
            page = next((p for p in free if p.url.startswith(url)), None)
            if page is None:
                page = next((p for p in free if p.url == "about:blank"), None)
                page = page or await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                except PlaywrightError as exc:
                    raise BrowserError(f"無法開啟 {url}：{exc.message.splitlines()[0]}") from exc
            await page.bring_to_front()

    def job_for_url(self, url: str) -> str | None:
        """The job whose open tab is showing `url` (most recently opened tab wins)."""
        wanted = _strip_fragment(url)
        for key in reversed(list(self._pages)):
            if any(_strip_fragment(p.url) == wanted for p in self._pages[key] if not p.is_closed()):
                return key
        return None

    def adopt(self, key: str, url: str) -> bool:
        """Make the already-open tab showing `url` the job's page (for jobs found by browsing)."""
        if self._context is None:
            return False
        wanted = _strip_fragment(url)
        for page in reversed(self._context.pages):
            if not page.is_closed() and _strip_fragment(page.url) == wanted:
                if page not in self._pages.get(key, []):
                    self._track(key, page)
                return True
        return False

    def current_page(self, key: str) -> Page | None:
        """The job's most recent open tab: a popup it opened, else its own tab."""
        pages = [p for p in self._pages.get(key, []) if not p.is_closed()]
        self._pages[key] = pages
        return pages[-1] if pages else None

    async def close(self) -> None:
        if self._context is not None:
            with contextlib.suppress(PlaywrightError):
                await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._pages.clear()


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]
