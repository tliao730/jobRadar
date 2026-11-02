"""Write answers into the page, strictly through SafePage."""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from job_radar.apply.classify import choose_option
from job_radar.apply.models import TEXT_KINDS, FieldAnswer, FieldKind
from job_radar.prefill.safe_page import FillError, SafePage, UnsafeActionError

log = logging.getLogger(__name__)

PAGE_CLOSED = "申請頁在填寫途中被關閉：請按「開啟申請頁」後再按一次 ②"


async def fill_answers(
    page: Page, answers: list[FieldAnswer], *, resume_path: Path | None, overwrite: bool
) -> list[FieldAnswer]:
    """Fill each answer; failures are recorded on the answer, never raised.

    overwrite=False keeps whatever a field already contains (used for the automatic pass,
    so re-running it never clobbers what you typed). overwrite=True is for answers you
    confirmed in the UI.
    """
    safe = SafePage(page)
    done: list[FieldAnswer] = []
    async with safe.guarded():
        for answer in answers:
            if page.is_closed():
                done.append(answer.model_copy(update={"filled": False, "error": PAGE_CLOSED}))
                continue
            done.append(await _fill_one(safe, answer, resume_path, overwrite))
    blocked = 0 if page.is_closed() else await safe.blocked_submissions()
    if blocked:
        log.warning("填寫過程中擋下了 %d 次表單送出", blocked)
    return done


async def _fill_one(
    safe: SafePage, answer: FieldAnswer, resume_path: Path | None, overwrite: bool
) -> FieldAnswer:
    field = answer.field
    value = answer.value
    text = value if isinstance(value, str) else "; ".join(value)
    try:
        if field.kind == FieldKind.FILE:
            if resume_path is None:
                raise FillError("找不到要上傳的履歷 PDF")
            if field.value and not overwrite:
                return _done(answer, note=f"已有上傳的檔案（{field.value}），未重新上傳")
            await safe.upload(field, resume_path)
            return _done(answer, value=resume_path.name)

        if field.value and not overwrite and field.kind != FieldKind.CHECKBOX:
            if field.value.strip().lower() == text.strip().lower():
                return _done(answer)
            return answer.model_copy(
                update={
                    "error": "",
                    "filled": False,
                    "note": _join(answer.note, f"欄位原本就有內容「{field.value[:40]}」，未覆寫"),
                }
            )

        if field.kind in TEXT_KINDS:
            await safe.fill_text(field, text)
        elif field.kind == FieldKind.SELECT:
            option = choose_option(field.options, text)
            if option is None:
                raise FillError(f"「{text}」不在選項中")
            await safe.select_native(field, option)
            value = option
        elif field.kind == FieldKind.COMBOBOX:
            value = await _choose_with_fallbacks(
                safe, field, [text, *answer.alternatives], answer.exact
            )
        elif field.kind in (FieldKind.RADIO, FieldKind.CHECKBOXES):
            wanted = value if isinstance(value, list) else [text]
            chosen = [o for w in wanted if (o := choose_option(field.options, w))]
            await safe.check_options(field, chosen or wanted)
            value = (
                chosen if field.kind == FieldKind.CHECKBOXES else (chosen[0] if chosen else text)
            )
        elif field.kind == FieldKind.CHECKBOX:
            await safe.set_checkbox(field, text.strip().lower() in {"true", "yes", "1", "checked"})
        return _done(answer, value=value)
    except (FillError, UnsafeActionError) as exc:
        return answer.model_copy(update={"filled": False, "error": str(exc)})
    except PlaywrightError as exc:
        if safe.page.is_closed():
            return answer.model_copy(update={"filled": False, "error": PAGE_CLOSED})
        message = exc.message or str(exc)
        log.warning("填寫「%s」失敗：%s", field.label, message)  # with Playwright's call log
        first_line = message.splitlines()[0]
        return answer.model_copy(update={"filled": False, "error": f"瀏覽器操作失敗：{first_line}"})


async def _choose_with_fallbacks(
    safe: SafePage, field, choices: list[str], exact: bool = False
) -> str:
    """The first of `choices` the dropdown offers ("Data Science", else "Computer Science")."""
    for i, choice in enumerate(choices):
        try:
            return await safe.choose_combobox(field, choice, exact)
        except FillError:
            if i == len(choices) - 1:
                raise
    raise FillError("沒有可以選的答案")


def _done(
    answer: FieldAnswer, *, value: str | list[str] | None = None, note: str = ""
) -> FieldAnswer:
    update: dict = {"filled": True, "error": "", "note": _join(answer.note, note)}
    if value is not None:
        update["value"] = value
    return answer.model_copy(update=update)


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)
