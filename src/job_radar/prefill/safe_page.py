"""The only way prefill code touches a page.

SafePage can fill, select, check, upload, and click elements that are not submit controls.
It has no way to submit a form, and while it operates, a page-level guard blocks form
submission outright (including implicit submission from key events). The person reviews
the form and presses the site's submit button themselves.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Locator, Page

from job_radar.apply.classify import choose_option
from job_radar.apply.models import FormField
from job_radar.prefill import js

log = logging.getLogger(__name__)

SUBMIT_WORDS = re.compile(r"submit|apply|send|送出|提交|申請|投遞", re.IGNORECASE)
CLICK_TIMEOUT_MS = 5000
OPTIONS_WAIT_MS = 3000
SLOW_OPTIONS_WAIT_MS = 6000  # second try: a long list (countries) can be slow on a busy machine


_STOPWORDS = {"of", "the", "and", "in", "at", "for", "&"}


def search_queries(value: str, limit: int = 3) -> list[str]:
    """The value, then shorter tails of it for search boxes that need a closer match."""
    words = value.split()
    queries = [value]
    for start in range(1, len(words)):
        tail = words[start:]
        if tail[0].lower() in _STOPWORDS:
            continue
        if len(tail) >= 2:  # one word ("Science") matches too many unrelated options
            queries.append(" ".join(tail))
    return queries[:limit]


def _shows(shown: str, choice: str) -> bool:
    """Whether a dropdown showing `shown` has `choice` selected ("+1" for "United States +1")."""
    a, b = shown.strip().casefold(), choice.strip().casefold()
    return bool(a) and (a == b or a in b or b in a)


class UnsafeActionError(RuntimeError):
    """Refused: the action could submit the application."""


class FillError(RuntimeError):
    """A field could not be filled; the message is shown to the user."""


class SafePage:
    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def page(self) -> Page:
        return self._page

    def frame(self, index: int) -> Frame:
        frames = self._page.frames
        if index >= len(frames):
            raise FillError("找不到欄位所在的 frame，頁面可能已重新載入，請重新掃描")
        return frames[index]

    @asynccontextmanager
    async def guarded(self) -> AsyncIterator[None]:
        await self._set_guard(True)
        try:
            yield
        finally:
            await self._set_guard(False)

    async def _set_guard(self, on: bool) -> None:
        for frame in self._page.frames:
            # A frame that is detaching or navigating has no form left to guard.
            with contextlib.suppress(PlaywrightError):
                await frame.evaluate(js("guard.js"), on)

    def _locator(self, frame_index: int, element_id: str) -> Locator:
        return self.frame(frame_index).locator(f'[data-jr-id="{element_id}"]')

    async def _existing(self, frame_index: int, element_id: str) -> Locator:
        loc = self._locator(frame_index, element_id)
        if await loc.count() == 0:
            raise FillError("找不到這個欄位，頁面可能已重新載入，請重新掃描")
        return loc.first

    async def _safe_click(self, loc: Locator) -> None:
        info = await loc.evaluate(js("describe_element.js"))
        button_like = info["tag"] in ("button", "a") or info["role"] in ("button", "link")
        if info["submit"] or (button_like and SUBMIT_WORDS.search(info["text"] or "")):
            raise UnsafeActionError(f"拒絕點擊可能送出申請的元素：{info['text'][:60]!r}")
        await loc.click(timeout=CLICK_TIMEOUT_MS)

    # --- field operations -------------------------------------------------------

    async def fill_text(self, field: FormField, value: str) -> None:
        loc = await self._existing(field.frame_index, field.field_id)
        await loc.fill(value)
        if field.picker:
            await self._commit_date(field, value)

    async def _commit_date(self, field: FormField, value: str) -> None:
        """Typing into a date picker opens its calendar, which then stays open over the fields
        around it (Ramp, 2026-10-26: the next checkbox click landed on the calendar). Clicking
        the day it read from the text commits the date the site's way and closes it."""
        frame = self.frame(field.frame_index)
        found = await frame.evaluate(js("datepicker.js"), field.field_id)
        if found["day"]:
            await self.click_control(field.frame_index, found["day"])
        elif found["open"]:
            raise FillError(
                f"日曆看不懂「{value}」：請寫成 月/日/年（例如 05/01/2027），或直接在日曆上點日期"
            )

    async def select_native(self, field: FormField, option: str) -> None:
        loc = await self._existing(field.frame_index, field.field_id)
        await loc.select_option(label=option)

    async def set_checkbox(self, field: FormField, checked: bool) -> None:
        loc = await self._existing(field.frame_index, field.field_id)
        await self._set_checked(loc, checked)

    async def _set_checked(self, loc: Locator, checked: bool) -> None:
        try:
            await loc.set_checked(checked, force=True)
        except PlaywrightError as exc:
            # Some React boxes change on their next render, after Playwright has looked; what
            # counts is the state a moment later.
            if "did not change its state" not in (exc.message or ""):
                raise
            await self._page.wait_for_timeout(300)
            if await loc.is_checked() != checked:
                raise FillError(
                    "點了但勾選狀態沒有改變：可能被別的東西（例如日曆小視窗）蓋住，請手動勾選"
                ) from exc

    async def check_options(self, field: FormField, chosen: list[str]) -> None:
        """Radio: check the one chosen option. Checkboxes: make exactly `chosen` checked."""
        wanted = {o for o in chosen if o in field.options}
        if not wanted:
            raise FillError(f"選項「{'、'.join(chosen)}」不在這題的選項中")
        for option, element_id in zip(field.options, field.option_ids, strict=False):
            loc = await self._existing(field.frame_index, element_id)
            if option in wanted:
                await self._set_checked(loc, True)
            elif field.kind == "checkboxes":
                await self._set_checked(loc, False)

    async def upload(self, field: FormField, path: Path) -> None:
        loc = await self._existing(field.frame_index, field.field_id)
        await loc.set_input_files(str(path))

    async def click_control(self, frame_index: int, element_id: str) -> None:
        """Click a button such as "Add another"; refused if it could submit the form."""
        await self._safe_click(await self._existing(frame_index, element_id))

    async def choose_combobox(self, field: FormField, value: str, exact: bool = False) -> str:
        """Type into a searchable dropdown and click the matching option. Returns its text.

        If the full value finds nothing, shorter queries are tried ("Applied Data Science"
        → "Data Science"); an option is only taken if it matches the full value."""
        loc = await self._existing(field.frame_index, field.field_id)
        saw_options = False
        for attempt, query in enumerate(search_queries(value)):
            await loc.fill(query)  # typing opens searchable dropdowns such as react-select
            options = await self._visible_options(field.frame_index, loc)
            if options is None and attempt == 0:
                # Some dropdowns only open on click; a click blocked by an overlay just means
                # this attempt found nothing.
                with contextlib.suppress(PlaywrightError):
                    await self._safe_click(loc)
                    await loc.fill(query)
                    options = await self._visible_options(
                        field.frame_index, loc, SLOW_OPTIONS_WAIT_MS
                    )
            if options is None:
                continue
            saw_options = True
            # Ashby lists a school as "Name\nCountry\ndomain": the first line is what to match.
            texts = [(t.strip().splitlines() or [""])[0] for t in await options.all_inner_texts()]
            choice = choose_option(texts, value, exact) or (
                None if exact else choose_option(texts, value.split(",")[0])
            )
            if choice is not None and attempt > 0 and len(choice.split()) < 2:
                choice = None  # a shortened query must not settle for a one-word option
            if choice is not None:
                try:
                    await self._safe_click(options.nth(texts.index(choice)))
                except PlaywrightError:
                    # A click can time out although the option took (reported on Greenhouse
                    # forms, 2026-10-26); what the dropdown shows afterwards decides.
                    if not _shows(await loc.evaluate(js("combobox_shows.js")), choice):
                        raise
                    log.info("「%s」的選項點擊逾時，但已顯示「%s」", field.label, choice)
                return choice
        await loc.fill("")
        if saw_options and exact:
            raise FillError(f"清單裡沒有「{value}」（只有名稱相近的），請手動選擇，例如 Other")
        if saw_options:
            raise FillError(f"沒有符合「{value}」的選項，請手動選擇")
        raise FillError(f"輸入「{value}」後沒有出現選項，請手動選擇")

    async def _visible_options(
        self, frame_index: int, loc: Locator, wait_ms: int = OPTIONS_WAIT_MS
    ) -> Locator | None:
        listbox_id = await loc.get_attribute("aria-controls") or await loc.get_attribute(
            "aria-owns"
        )
        frame = self.frame(frame_index)
        scope = frame.locator(f'[id="{listbox_id}"]') if listbox_id else frame
        options = scope.locator('[role="option"]')
        try:
            await options.first.wait_for(state="visible", timeout=wait_ms)
        except PlaywrightError:
            return None
        return options

    async def blocked_submissions(self) -> int:
        total = 0
        for frame in self._page.frames:
            with contextlib.suppress(PlaywrightError):
                total += int(await frame.evaluate("() => window.__jrBlocked || 0"))
        return total
