"""The application flow, independent of the web layer.

add URLs → open the apply page → fill basics and draft the remaining questions →
fill the answers the user confirmed → the user submits in the browser → mark as applied.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections import defaultdict
from pathlib import Path

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from pydantic import BaseModel

from job_radar.apply.classify import classify, enrich_options, normalize_label
from job_radar.apply.drafts import draft_answers
from job_radar.apply.history import block_of, entry_index
from job_radar.apply.intake import USER_AGENT, IntakeError, fetch_job_details, parse_job_url
from job_radar.apply.models import (
    Application,
    AppStatus,
    Category,
    FieldAnswer,
    FormField,
    FormState,
)
from job_radar.apply.store import Store
from job_radar.config import AppConfig, describe_anthropic_credential
from job_radar.llm import LLMError, StructuredLLM
from job_radar.prefill import scanner
from job_radar.prefill.browser import BrowserError, BrowserManager
from job_radar.prefill.filler import fill_answers
from job_radar.prefill.safe_page import FillError, SafePage, UnsafeActionError
from job_radar.profile import AnswerRule, Profile, ProfileError, label_rule, load_profile

log = logging.getLogger(__name__)

JOB_OVERRIDE_RESUME = "resume.pdf"
MAX_HISTORY_ENTRIES = 3  # jobs / schools filled per form, most recent first
NO_LLM_NOTE = "還沒接模型，請自己填寫；勾「記住這個答案」，之後遇到同一題會自動填"
_ACTIVE = {AppStatus.QUEUED, AppStatus.PREFILLED, AppStatus.READY}


class ApplyError(RuntimeError):
    """A user-facing failure; the message says what to do next."""


class ConfirmedAnswer(BaseModel):
    field_id: str
    value: str | list[str]
    remember: bool = False


class ApplyService:
    def __init__(
        self,
        cfg: AppConfig,
        store: Store,
        browser: BrowserManager,
        llm: StructuredLLM | None,
        http: httpx.Client | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.browser = browser
        self.llm = llm
        self.http = http or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
        self._lock = asyncio.Lock()  # one browser operation at a time

    async def close(self) -> None:
        await self.browser.close()
        self.http.close()
        self.store.close()

    # --- profile ----------------------------------------------------------------

    def load_profile(self) -> Profile:
        try:
            return load_profile(self.cfg.profile_dir)
        except ProfileError as exc:
            raise ApplyError(str(exc)) from exc

    def profile_status(self) -> dict:
        llm = {
            "model": self._model_name(),
            "drafts": self.llm is not None,
            "credential": describe_anthropic_credential(self.cfg.home),
        }
        try:
            profile = load_profile(self.cfg.profile_dir)
        except ProfileError as exc:
            return {"ok": False, "error": str(exc), "resumes": [], "highlights": 0, **llm}
        missing = [
            k
            for k in ("first_name", "last_name", "email", "phone")
            if not getattr(profile.applicant.basic, k)
        ]
        return {
            "ok": True,
            "error": f"applicant.yaml 尚未填寫：{', '.join(missing)}" if missing else "",
            "resumes": sorted(profile.resume_variants()),
            "highlights": len(profile.highlights),
            **llm,
        }

    def _model_name(self) -> str | None:
        return self.llm.model if self.llm else None

    # --- queue ------------------------------------------------------------------

    def add_urls(self, text: str) -> tuple[list[Application], list[str]]:
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", text)))
        if not urls:
            return [], ["沒有找到網址"]
        added, errors = [], []
        for url in urls:
            try:
                job = parse_job_url(url)
            except IntakeError as exc:
                errors.append(str(exc))
                continue
            job = fetch_job_details(job, self.http)
            app, _ = self.store.add(job)
            added.append(app)
        return added, errors

    def list_applications(self) -> list[Application]:
        return self.store.list()

    def get(self, job_id: str) -> Application:
        app = self.store.get(job_id)
        if app is None:
            raise ApplyError(f"找不到職缺 {job_id}")
        return app

    def detail(self, job_id: str) -> dict:
        app = self.get(job_id)
        try:
            variants = sorted(self.load_profile().resume_variants())
        except ApplyError:
            variants = []
        has_override = (self.store.folder(job_id) / JOB_OVERRIDE_RESUME).exists()
        return {
            "application": app,
            "form": self.store.load_form(job_id),
            "resumes": variants,
            "suggested_resume": self.suggested_variant(app.job.title, variants),
            "job_resume_override": has_override,
            "folder": str(self.store.folder(job_id)),
            "events": self.store.events(job_id),
            "page_open": self.page_open(job_id),
        }

    def page_open(self, job_id: str) -> bool:
        """Whether the job's application tab is still open in the controlled Chrome."""
        return self.browser.current_page(job_id) is not None

    def job_for_url(self, url: str) -> str | None:
        """Which application the browser tab showing `url` belongs to (for the side panel)."""
        job_id = self.browser.job_for_url(url)
        return job_id if job_id and self.store.get(job_id) else None

    async def adopt_tab(self, url: str) -> Application:
        """Add the job open in the current tab and use that tab for it."""
        added, errors = await asyncio.to_thread(self.add_urls, url)
        if not added:
            raise ApplyError(errors[0] if errors else "無法加入這個網址")
        app = added[0]
        self.browser.adopt(app.job.job_id, url)
        return app

    async def show_home(self, url: str) -> None:
        try:
            await self.browser.show(url)
        except BrowserError as exc:
            raise ApplyError(str(exc)) from exc

    def set_status(self, job_id: str, status: AppStatus, note: str = "") -> Application:
        self.get(job_id)
        return self.store.set_status(job_id, status, note)

    # --- resume -------------------------------------------------------------------

    def suggested_variant(self, title: str, variants: list[str]) -> str | None:
        for rule in self.cfg.apply.resume_rules:
            if rule.variant in variants and re.search(rule.title_pattern, title or "", re.I):
                return rule.variant
        return None

    def resume_choice(
        self, app: Application, requested: str | None, profile: Profile
    ) -> tuple[str | None, Path | None]:
        override = self.store.folder(app.job.job_id) / JOB_OVERRIDE_RESUME
        if override.exists():
            return "job", override
        variants = profile.resume_variants()
        candidates = [
            requested,
            app.resume_variant,
            self.suggested_variant(app.job.title, sorted(variants)),
            self.cfg.apply.default_resume,
        ]
        for name in candidates:
            if name and name in variants:
                return name, variants[name]
        if variants:
            name = sorted(variants)[0]
            return name, variants[name]
        return None, None

    # --- browser steps ----------------------------------------------------------

    async def open(self, job_id: str) -> Application:
        app = self.get(job_id)
        async with self._lock:
            try:
                page = await self.browser.open(job_id, app.job.apply_url)
            except BrowserError as exc:
                raise ApplyError(str(exc)) from exc
            await scanner.settle(page)
            await self._capture_job_text(app, page)
        return self.get(job_id)

    async def prefill(self, job_id: str, resume_variant: str | None = None) -> FormState:
        """Scan the job's tab (opening it if it was closed), fill what the profile answers and
        the answers confirmed with ③ before, and draft the rest."""
        previous = self.store.load_form(job_id)
        app = await asyncio.to_thread(self._refresh_job, self.get(job_id))
        profile = self.load_profile()
        variant, resume_path = self.resume_choice(app, resume_variant, profile)
        self.store.set_resume_variant(job_id, variant)
        state = FormState(
            job_id=job_id,
            resume_variant=variant,
            resume_path=str(resume_path) if resume_path else None,
        )

        async with self._lock:
            page = self.browser.current_page(job_id)
            try:
                if page is None:
                    page = await self.browser.open(job_id, app.job.apply_url)
                await scanner.settle(page)
            except BrowserError as exc:
                raise ApplyError(str(exc)) from exc
            await self._capture_job_text(app, page)
            app = self.get(job_id)
            state.page_url = page.url
            state.blockers, state.notices = await scanner.detect(page)
            if not state.blockers and not await scanner.wait_until_interactive(page):
                state.blockers.append(scanner.NOT_HYDRATED)
            if state.blockers:
                state.answers = _kept(previous)
                self.store.save_form(state)
                return state
            fields = enrich_options(await scanner.scan_fields(page), app.job.ats_questions)
            if not fields:
                state.notices.append(
                    "等了 20 秒，這個頁面還是沒有出現表單欄位。如果要先按「Apply」才會出現申請表，"
                    "請在瀏覽器點進去後，再按一次「填寫基本資料」；如果表單其實已經在畫面上，再按一次即可。"
                )
                state.answers = _kept(previous)
                self.store.save_form(state)
                return state
            decided, remaining = classify(fields, profile, resume_available=resume_path is not None)
            auto = [a for a in decided if a.category == Category.AUTO]
            filled = {
                a.field.field_id: a
                for a in await fill_answers(page, auto, resume_path=resume_path, overwrite=False)
            }
            decided = [filled.get(a.field.field_id, a) for a in decided]
            more_fields, more_decided, more_remaining = await self._add_history_entries(
                page, fields, profile, resume_path, app
            )
            fields += more_fields
            decided += more_decided
            remaining += more_remaining
            restored, remaining = _restore_confirmed(previous, remaining)
            if restored:
                restored = await fill_answers(
                    page, restored, resume_path=resume_path, overwrite=False
                )

        reused, to_draft = _reuse_previous(previous, remaining)
        drafted = await self._draft(app, to_draft, profile, resume_path, state)
        order = {f.field_id: i for i, f in enumerate(fields)}
        state.answers = sorted(
            [*decided, *restored, *reused, *drafted],
            key=lambda a: order.get(a.field.field_id, len(order)),
        )
        self.store.save_form(state)
        # Whatever was not filled is answered on the site itself, so a filled form is ready to
        # check and send (PREFILLED is left over from when answers were typed in here).
        if app.status in (AppStatus.QUEUED, AppStatus.PREFILLED):
            self.store.set_status(job_id, AppStatus.READY)
        return state

    async def _add_history_entries(
        self,
        page: Page,
        fields: list[FormField],
        profile: Profile,
        resume_path: Path | None,
        app: Application,
    ) -> tuple[list[FormField], list[FieldAnswer], list[FormField]]:
        """Press a block's "Add another" for each extra job / school in applicant.yaml, then
        classify and fill the fields that appear. Returns (new fields, decided, remaining)."""
        new_fields: list[FormField] = []
        decided: list[FieldAnswer] = []
        remaining: list[FormField] = []
        safe = SafePage(page)
        blocks = (("employment", profile.applicant.employment),
                  ("education", profile.applicant.education))  # fmt: skip
        for block, entries in blocks:
            wanted = min(len(entries), MAX_HISTORY_ENTRIES)
            for _ in range(wanted):
                current = [f for f in [*fields, *new_fields] if block_of(f) == block]
                shown = {entry_index(f) for f in current}
                if not current or len(shown) >= wanted:
                    break
                current.sort(key=entry_index)
                last = current[-1]
                button = await scanner.add_entry_button(page, current)
                if not button:
                    break
                known = {f.field_id for f in [*fields, *new_fields]}
                try:
                    async with safe.guarded():
                        await safe.click_control(last.frame_index, button)
                except (FillError, UnsafeActionError, PlaywrightError) as exc:
                    log.warning("無法新增一筆%s：%s", block, exc)
                    break
                added = await _wait_for_new_fields(page, known, app.job.ats_questions)
                if not added:
                    break
                more, rest = classify(added, profile, resume_available=resume_path is not None)
                auto = [a for a in more if a.category == Category.AUTO]
                filled = {
                    a.field.field_id: a
                    for a in await fill_answers(
                        page, auto, resume_path=resume_path, overwrite=False
                    )
                }
                new_fields += added
                decided += [filled.get(a.field.field_id, a) for a in more]
                remaining += rest
        return new_fields, decided, remaining

    def _refresh_job(self, app: Application) -> Application:
        """Re-read the ATS API, so jobs added earlier pick up the current JD and questions
        (and anything the parser learned since, e.g. Greenhouse demographic options)."""
        fresh = fetch_job_details(app.job, self.http)
        if fresh == app.job:
            return app
        self.store.update_job(fresh)
        return self.get(app.job.job_id)

    async def _draft(
        self,
        app: Application,
        fields: list[FormField],
        profile: Profile,
        resume_path: Path | None,
        state: FormState,
    ) -> list[FieldAnswer]:
        if not fields:
            return []
        if self.llm is None:
            return [
                FieldAnswer(field=f, category=Category.THOUGHT, note=NO_LLM_NOTE) for f in fields
            ]
        facts = profile.facts_for_llm(resume_path)
        try:
            answers, usage, truncated = await asyncio.to_thread(
                draft_answers, self.llm, app.job, fields, facts, self.cfg.llm.max_jd_chars
            )
        except LLMError as exc:
            state.llm_error = str(exc)
            return [
                FieldAnswer(field=f, category=Category.THOUGHT, note="草稿產生失敗，請自行填寫")
                for f in fields
            ]
        state.llm_cost_usd = usage.cost_usd
        self.store.add_cost(app.job.job_id, usage.cost_usd)
        if truncated:
            state.notices.append(
                f"JD 超過 {self.cfg.llm.max_jd_chars} 字元，草稿只參考了前段內容。"
            )
        return answers

    async def fill_confirmed(self, job_id: str, confirmed: list[ConfirmedAnswer]) -> FormState:
        app = self.get(job_id)
        state = self.store.load_form(job_id)
        if state is None:
            raise ApplyError("請先按「填寫基本資料」")
        by_id = {a.field.field_id: a for a in state.answers}
        wanted = {c.field_id: c for c in confirmed if c.field_id in by_id and _has_value(c.value)}
        if not wanted:
            raise ApplyError("沒有要填入的答案")
        to_fill = [
            by_id[fid].model_copy(update={"value": c.value, "confirmed": True})
            for fid, c in wanted.items()
        ]

        async with self._lock:
            page = self.browser.current_page(job_id)
            if page is None:
                raise ApplyError("這個職缺的瀏覽器分頁已關閉：請按「開啟申請頁」再「填寫基本資料」")
            if not await scanner.wait_until_interactive(page):
                raise ApplyError(scanner.NOT_HYDRATED)
            resume = Path(state.resume_path) if state.resume_path else None
            results = {
                a.field.field_id: a
                for a in await fill_answers(page, to_fill, resume_path=resume, overwrite=True)
            }

        state.answers = [results.get(a.field.field_id, a) for a in state.answers]
        self._remember(
            [results[fid] for fid, c in wanted.items() if c.remember and results[fid].filled]
        )
        self.store.save_form(state)
        if app.status in _ACTIVE and any(a.filled for a in results.values()):
            self.store.set_status(job_id, AppStatus.READY)
        return state

    def _remember(self, answers: list[FieldAnswer]) -> None:
        if not answers:
            return
        profile = self.load_profile()
        for answer in answers:
            profile.save_learned(
                AnswerRule(match=label_rule(answer.field.label), answer=answer.value)
            )
            log.info("已記住答案：%s", answer.field.label)

    async def _capture_job_text(self, app: Application, page: Page) -> None:
        """For jobs without an ATS API (LinkedIn, Indeed, ...), keep the page text as the JD."""
        if app.job.description_text and app.job.title:
            return
        update: dict = {}
        if not app.job.description_text:
            update["description_text"] = await scanner.page_text(page)
        if not app.job.title:
            with contextlib.suppress(PlaywrightError):
                update["title"] = (await page.title())[:200]
        if any(update.values()):
            self.store.update_job(app.job.model_copy(update=update))


async def _wait_for_new_fields(
    page: Page, known: set[str], questions: list[dict], timeout_s: float = 5
) -> list[FormField]:
    """Fields that appeared after pressing "Add another" (the block renders them shortly)."""
    for _ in range(int(timeout_s / 0.25)):
        fields = enrich_options(await scanner.scan_fields(page), questions)
        added = [f for f in fields if f.field_id not in known]
        if added:
            return added
        await asyncio.sleep(0.25)
    return []


def _has_value(value: str | list[str]) -> bool:
    return bool(value.strip()) if isinstance(value, str) else any(v.strip() for v in value)


def _was_confirmed(answer: FieldAnswer) -> bool:
    # Forms saved before `confirmed` existed: an open question that got filled went through ③.
    return answer.confirmed or (
        answer.filled and answer.category in (Category.THOUGHT, Category.SUGGESTED)
    )


def _restore_confirmed(
    previous: FormState | None, fields: list[FormField]
) -> tuple[list[FieldAnswer], list[FormField]]:
    """Answers confirmed with ③ on an earlier scan, matched to this scan's fields by question
    (repeated questions in order), so a re-opened tab gets them back."""
    if previous is None:
        return [], fields
    pending: dict[tuple, list[FieldAnswer]] = defaultdict(list)
    for a in previous.answers:
        if _was_confirmed(a) and _has_value(a.value):
            pending[(normalize_label(a.field.label), a.field.kind)].append(a)
    restored, rest = [], []
    for field in fields:
        queue = pending.get((normalize_label(field.label), field.kind))
        if queue:
            fresh = {"field": field, "filled": False, "error": "", "confirmed": True}
            restored.append(queue.pop(0).model_copy(update=fresh))
        else:
            rest.append(field)
    return restored, rest


def _kept(previous: FormState | None) -> list[FieldAnswer]:
    """A scan that found nothing to fill (blocked, form not there yet) keeps the earlier answers,
    unfilled, so the next scan can still bring back the confirmed ones."""
    if previous is None:
        return []
    return [
        a.model_copy(update={"filled": False, "error": "", "confirmed": _was_confirmed(a)})
        for a in previous.answers
    ]


def _reuse_previous(
    previous: FormState | None, fields: list[FormField]
) -> tuple[list[FieldAnswer], list[FormField]]:
    """Re-scanning the same form should not pay for drafts we already have."""
    if previous is None:
        return [], fields
    known = {
        (normalize_label(a.field.label), a.field.kind): a
        for a in previous.answers
        if a.source == "llm" and (a.value or a.category == Category.USER)
    }
    reused, fresh = [], []
    for field in fields:
        hit = known.get((normalize_label(field.label), field.kind))
        if hit:
            reused.append(hit.model_copy(update={"field": field, "filled": False, "error": ""}))
        else:
            fresh.append(field)
    return reused, fresh
