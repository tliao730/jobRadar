"""Read a page: what blocks automation (login, CAPTCHA), which form fields exist, its text."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from pydantic import ValidationError

from job_radar.apply.models import FormField
from job_radar.prefill import js

log = logging.getLogger(__name__)

CAPTCHA_FRAME = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare\.com|turnstile", re.I)

BLOCKER_MESSAGES = {
    "login": "這個頁面要求登入：請在瀏覽器手動登入後，再按一次「填寫基本資料」。",
    "captcha_page": "網站正在進行真人驗證：請在瀏覽器手動完成後，再按一次「填寫基本資料」。",
    "captcha_challenge": "畫面上出現 CAPTCHA 驗證：請手動完成後，再按一次「填寫基本資料」。",
}
NOT_HYDRATED = (
    "頁面還沒準備好（網站程式沒有載入完成），為了不弄壞表單，這次沒有填寫："
    "請重新整理頁面，等它完全載入後再按一次「填寫基本資料」。"
)
HYDRATION_TIMEOUT_MS = 25000  # a busy page (several tabs loading, cold cache) can take ~20 s
FORM_WAIT_MS = 20000

NOTICE_MESSAGES = {
    "captcha_widget": "這個表單有 CAPTCHA，送出前請自己完成驗證。",
}


async def detect(page: Page) -> tuple[list[str], list[str]]:
    """Returns (blocker messages, notice messages)."""
    try:
        found = await page.evaluate(js("detect.js"))
    except PlaywrightError as exc:
        log.warning("無法檢查頁面狀態：%s", exc)
        return [], []
    blockers = [BLOCKER_MESSAGES[b] for b in found["blockers"] if b in BLOCKER_MESSAGES]
    notices = [NOTICE_MESSAGES[n] for n in found["notices"] if n in NOTICE_MESSAGES]
    return blockers, notices


async def settle(page: Page) -> None:
    """Give client-rendered forms (e.g. Ashby) a moment to appear."""
    with contextlib.suppress(PlaywrightError):
        await page.wait_for_load_state("networkidle", timeout=6000)


async def wait_until_interactive(page: Page) -> bool:
    """Wait for the form to appear and, if React renders it, to hydrate; False when a React
    form never hydrates.

    Client-rendered pages (Ashby) draw their form seconds after load, longer on a cold cache.
    Typing into a server-rendered React form before it hydrates can crash the app, after which
    dropdowns never open (and text values never reach the app's state). A page that shows no
    form within FORM_WAIT_MS counts as ready: the caller reports that it found no fields.
    """
    start = time.monotonic()
    while True:
        states = []
        for frame in page.frames:
            if CAPTCHA_FRAME.search(frame.url or ""):
                continue
            try:
                states.append(await frame.evaluate(js("hydration.js")))
            except PlaywrightError:
                continue
        controls = sum(s["total"] for s in states)
        pending = [s for s in states if not s["ready"]]
        waited_ms = (time.monotonic() - start) * 1000
        if controls and not pending:
            return True
        if not controls and waited_ms >= FORM_WAIT_MS:
            return True
        if pending and waited_ms >= HYDRATION_TIMEOUT_MS:
            log.warning("表單沒有完成 hydration：%s", pending)
            return False
        await asyncio.sleep(0.25)


async def add_entry_button(page: Page, block: list[FormField]) -> str:
    """data-jr-id of the "Add another" button of the block made of `block` ('' if none)."""
    field = block[-1]
    ids = [i for f in block for i in (f.option_ids or [f.field_id])]
    try:
        frame = page.frames[field.frame_index]
        button_id = f"b{field.frame_index}-{field.field_id}"
        return await frame.evaluate(js("add_entry.js"), [ids[-1], button_id, ids])
    except (PlaywrightError, IndexError):
        return ""


async def scan_fields(page: Page) -> list[FormField]:
    fields: list[FormField] = []
    for index, frame in enumerate(page.frames):
        if CAPTCHA_FRAME.search(frame.url or ""):
            continue
        try:
            raw = await frame.evaluate(js("extract_fields.js"), index)
        except PlaywrightError as exc:
            log.debug("略過無法讀取的 frame %s：%s", frame.url, exc)
            continue
        for item in raw:
            try:
                fields.append(FormField.model_validate(item))
            except ValidationError as exc:
                log.warning("略過格式異常的欄位：%s", exc)
    return fields


async def page_text(page: Page, limit: int = 20000) -> str:
    try:
        text = await page.inner_text("body", timeout=5000)
    except PlaywrightError:
        return ""
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()[:limit]
