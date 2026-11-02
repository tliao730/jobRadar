"""The controlled Chrome: side-panel extension and shutdown behaviour."""

import asyncio

import pytest

from job_radar.desktop import prepare_extension
from job_radar.prefill.browser import BrowserManager

pytestmark = pytest.mark.browser


async def test_extension_loads_into_chrome(tmp_path, page):  # `page` skips when Chrome is missing
    extension = prepare_extension(tmp_path / "data", "http://127.0.0.1:8765")
    closed = []
    browser = BrowserManager(
        tmp_path / "profile",
        channel="chrome",
        headless=True,
        extension_dir=extension,
        on_close=lambda: closed.append(True),
    )
    context = await browser._ensure_context()
    for _ in range(50):
        if any(w.url.endswith("/background.js") for w in context.service_workers):
            break
        await asyncio.sleep(0.1)
    assert any(w.url.endswith("/background.js") for w in context.service_workers)
    await browser.close()
    assert closed == [True]


async def test_closing_every_tab_counts_as_closing_the_browser(tmp_path, page):
    closed = []
    browser = BrowserManager(
        tmp_path / "profile", channel="chrome", headless=True, on_close=lambda: closed.append(1)
    )
    context = await browser._ensure_context()
    extra = await context.new_page()
    await extra.close()
    assert closed == []  # the first tab is still open
    for remaining in list(context.pages):
        await remaining.close()
    for _ in range(50):
        if closed:
            break
        await asyncio.sleep(0.1)
    assert closed == [1]
    await browser.close()
