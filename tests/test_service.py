"""End-to-end flow through ApplyService on a local Greenhouse-style form."""

import httpx
import pytest

from job_radar.apply.models import AppStatus, Category, JobRef, Source
from job_radar.apply.service import NO_LLM_NOTE, ApplyError, ApplyService, ConfirmedAnswer
from job_radar.apply.store import Store
from job_radar.config import AppConfig, PathsConfig
from job_radar.prefill.browser import BrowserManager
from job_radar.profile import load_profile
from tests.conftest import form_url

pytestmark = pytest.mark.browser

IN_PERSON = "Are you open to working in-person in one of our offices 25% of the time?"


@pytest.fixture
async def service(tmp_path, profile_dir, fake_llm, page):  # `page` skips when Chrome is missing
    cfg = AppConfig(
        root=tmp_path,
        paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "data")),
    )
    browser = BrowserManager(tmp_path / "browser-profile", channel="chrome", headless=True)
    svc = ApplyService(cfg, Store(cfg.data_dir), browser, fake_llm, http=httpx.Client())
    yield svc
    await svc.close()


def add_fixture_job(service: ApplyService) -> str:
    url = form_url("greenhouse_like.html")
    job = JobRef(
        job_id="greenhouse:fixture",
        source=Source.GREENHOUSE,
        source_job_id="fixture",
        url=url,
        apply_url=url,
        company="Example Co",
        title="Data Scientist",
        description_text="Build ranking models and run experiments.",
        ats_questions=[
            {"label": IN_PERSON, "fields": [{"name": "question_1002", "values": ["Yes", "No"]}]}
        ],
    )
    service.store.add(job)
    return job.job_id


async def test_prefill_then_fill_confirmed(service, fake_llm, profile_dir):
    job_id = add_fixture_job(service)

    state = await service.prefill(job_id)
    got = {a.field.label: a for a in state.answers}
    assert got["First Name"].category == Category.AUTO and got["First Name"].filled
    assert got["Resume/CV"].filled
    assert got["Gender"].category == Category.USER
    assert got["Why Example Co?"].category == Category.THOUGHT
    assert got["Why Example Co?"].value == "Draft: Why Example Co?"
    # Options came from the Greenhouse API, so the model could pick a valid one.
    assert got[IN_PERSON].category == Category.SUGGESTED and got[IN_PERSON].value == "Yes"
    assert service.get(job_id).status == AppStatus.READY  # the rest is answered on the site
    assert service.get(job_id).llm_cost_usd > 0
    assert len(fake_llm.calls) == 1
    assert "jane@example.com" not in fake_llm.calls[0]["user"]

    page = service.browser.current_page(job_id)
    assert await page.input_value("#first_name") == "Jane"

    why = got["Why Example Co?"].field.field_id
    in_person = got[IN_PERSON].field.field_id
    state = await service.fill_confirmed(
        job_id,
        [
            ConfirmedAnswer(field_id=why, value="I like ranking problems.", remember=True),
            ConfirmedAnswer(field_id=in_person, value="Yes"),
        ],
    )
    assert await page.input_value("#question_1004") == "I like ranking problems."
    shell = page.locator(".select-shell", has=page.locator("#question_1002"))
    assert (await shell.locator(".select__single-value").text_content()).strip() == "Yes"
    assert service.get(job_id).status == AppStatus.READY
    assert not await page.evaluate("window.__submitted")
    assert load_profile(profile_dir).learned[0].answer == "I like ranking problems."

    # Re-scanning reuses the drafts (and the remembered answer) instead of paying again.
    state = await service.prefill(job_id)
    assert len(fake_llm.calls) == 1
    again = {a.field.label: a for a in state.answers}
    assert again["Why Example Co?"].category == Category.AUTO
    assert again["Why Example Co?"].source == "learned"


async def test_fill_requires_a_scan_first(service):
    job_id = add_fixture_job(service)
    with pytest.raises(ApplyError, match="填寫基本資料"):
        await service.fill_confirmed(job_id, [ConfirmedAnswer(field_id="x", value="y")])


async def test_blocked_pages_are_reported_without_filling(service):
    url = form_url("login.html")
    service.store.add(
        JobRef(
            job_id="other:login", source=Source.OTHER, source_job_id="login", url=url, apply_url=url
        )
    )
    state = await service.prefill("other:login")
    assert state.blockers and not state.answers
    assert service.get("other:login").status == AppStatus.QUEUED


async def test_without_a_model_open_questions_are_left_to_me(service):
    service.llm = None
    job_id = add_fixture_job(service)
    state = await service.prefill(job_id)
    got = {a.field.label: a for a in state.answers}
    assert got["First Name"].filled
    assert got["Why Example Co?"].category == Category.THOUGHT
    assert got["Why Example Co?"].value == "" and got["Why Example Co?"].note == NO_LLM_NOTE
    assert state.llm_error == ""
    assert service.profile_status()["drafts"] is False


async def test_side_panel_finds_the_job_by_its_tab(service):
    job_id = add_fixture_job(service)
    await service.prefill(job_id)
    page = service.browser.current_page(job_id)
    assert service.job_for_url(page.url) == job_id
    assert service.job_for_url(page.url + "#section") == job_id
    assert service.job_for_url("https://elsewhere.example/") is None


async def test_a_tab_opened_by_hand_can_be_adopted(service):
    url = form_url("lever_like.html")
    context = await service.browser._ensure_context()
    page = await context.new_page()
    await page.goto(url)
    assert service.browser.job_for_url(url) is None
    assert service.browser.adopt("lever:by-hand", url)
    assert service.browser.job_for_url(url) == "lever:by-hand"
    assert service.browser.current_page("lever:by-hand") is page


async def test_show_reuses_the_home_tab(service):
    home = form_url("login.html")
    await service.show_home(home)
    context = await service.browser._ensure_context()
    count = len(context.pages)
    await service.show_home(home)
    assert len(context.pages) == count
    assert any(p.url == home for p in context.pages)


def add_late_hydration_job(service: ApplyService, query: str) -> str:
    url = form_url("late_hydration.html") + query
    job = JobRef(
        job_id="greenhouse:late",
        source=Source.GREENHOUSE,
        source_job_id="late",
        url=url,
        apply_url=url,
        company="Example Co",
        title="Data Scientist",
        description_text="Build models.",
    )
    service.store.add(job)
    return job.job_id


async def test_waits_for_the_page_to_hydrate_before_typing(service):
    # Typing into a server-rendered React form before it hydrates kills the whole app
    # (React #426/#345): every dropdown then fails while text fields look filled.
    job_id = add_late_hydration_job(service, "?ms=1500")
    state = await service.prefill(job_id)
    got = {a.field.label: a for a in state.answers}
    assert got["Country"].filled, got["Country"].error
    page = service.browser.current_page(job_id)
    assert not await page.evaluate("window.__crashed")


async def test_waits_even_before_react_marks_its_root(service):
    # Only the framework's inline data exists yet (slow bundle download): still a React page.
    job_id = add_late_hydration_job(service, "?ms=1500&late_root")
    state = await service.prefill(job_id)
    got = {a.field.label: a for a in state.answers}
    assert got["Country"].filled, got["Country"].error
    page = service.browser.current_page(job_id)
    assert not await page.evaluate("window.__crashed")


async def test_a_form_that_never_hydrates_is_left_alone(service, monkeypatch):
    monkeypatch.setattr("job_radar.prefill.scanner.HYDRATION_TIMEOUT_MS", 1500)
    job_id = add_late_hydration_job(service, "?never")
    state = await service.prefill(job_id)
    assert state.blockers and "重新整理" in state.blockers[0]
    assert state.answers == []
    page = service.browser.current_page(job_id)
    assert await page.locator("#first_name").input_value() == ""


async def test_waits_for_a_client_rendered_form_to_appear(service):
    url = form_url("late_render.html") + "?ms=2500"
    job = JobRef(
        job_id="ashby:late",
        source=Source.ASHBY,
        source_job_id="late",
        url=url,
        apply_url=url,
        company="Ramp",
        title="Applied Scientist Intern",
    )
    service.store.add(job)
    state = await service.prefill(job.job_id)
    got = {a.field.label: a for a in state.answers}
    assert not state.notices, state.notices
    assert got["First Name"].filled and got["Email"].filled


async def test_adds_another_entry_for_each_extra_job_and_ticks_the_current_one(service):
    url = form_url("history_like.html")
    job = JobRef(
        job_id="greenhouse:history",
        source=Source.GREENHOUSE,
        source_job_id="history",
        url=url,
        apply_url=url,
        company="Example Co",
        title="Data Scientist",
    )
    service.store.add(job)
    state = await service.prefill(job.job_id)
    page = service.browser.current_page(job.job_id)
    # applicant.yaml (conftest) lists two jobs and one school.
    assert await page.locator("#company-name-0").input_value() == "Example Labs"
    assert await page.locator("#company-name-1").input_value() == "Acme Analytics"
    assert await page.locator("#title-1").input_value() == "Analyst"
    assert await page.locator("#end-date-year-1").input_value() == "2024"
    assert await page.locator("#current-role-0_1").is_checked()
    assert not await page.locator("#current-role-1_1").is_checked()
    assert await page.locator("#school--1").count() == 0  # one school: no "Add another"
    got = {a.field.html_id: a for a in state.answers}
    assert got["company-name-1"].filled and got["current-role-0_1"].filled
    assert not await page.evaluate("window.__submitted || false")


async def test_adds_another_school_even_when_the_field_is_deeply_nested(service, profile_dir):
    import yaml

    from tests.conftest import APPLICANT

    data = {
        **APPLICANT,
        "education": [
            *APPLICANT["education"],
            {
                "school": "University of California, Los Angeles",
                "degree": "B.S.",
                "major": "Statistics",
                "start": "2019-09",
                "end": "2023-06",
            },
        ],
        "employment": APPLICANT["employment"][:1],
    }
    (profile_dir / "applicant.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
    url = form_url("history_like.html")
    job = JobRef(
        job_id="greenhouse:school",
        source=Source.GREENHOUSE,
        source_job_id="school",
        url=url,
        apply_url=url,
        company="Example Co",
        title="Data Scientist",
    )
    service.store.add(job)
    await service.prefill(job.job_id)
    page = service.browser.current_page(job.job_id)
    assert await page.locator("#school--1").count() == 1
    assert (
        await page.locator(".education--form")
        .nth(1)
        .locator(".select__single-value")
        .first.inner_text()
        == "University of California, Los Angeles"
    )
    assert await page.locator("#company-name-1").count() == 0  # one job: the other block untouched


async def confirm_two_answers(service: ApplyService, job_id: str) -> tuple[str, str]:
    state = await service.prefill(job_id)
    got = {a.field.label: a.field.field_id for a in state.answers}
    await service.fill_confirmed(
        job_id,
        [
            ConfirmedAnswer(field_id=got["Why Example Co?"], value="I like ranking problems."),
            ConfirmedAnswer(field_id=got[IN_PERSON], value="No"),
        ],
    )
    return got["Why Example Co?"], got[IN_PERSON]


async def test_a_closed_tab_comes_back_with_the_answers_i_confirmed(service, fake_llm):
    job_id = add_fixture_job(service)
    await confirm_two_answers(service, job_id)
    assert service.get(job_id).status == AppStatus.READY

    await service.browser.current_page(job_id).close()  # closed by accident
    assert not service.page_open(job_id)

    state = await service.prefill(job_id)  # re-opens the page
    page = service.browser.current_page(job_id)
    assert await page.input_value("#first_name") == "Jane"
    assert await page.input_value("#question_1004") == "I like ranking problems."
    shell = page.locator(".select-shell", has=page.locator("#question_1002"))
    assert (await shell.locator(".select__single-value").text_content()).strip() == "No"
    got = {a.field.label: a for a in state.answers}
    assert got["Why Example Co?"].confirmed and got["Why Example Co?"].filled
    assert got["Why Example Co?"].category == Category.THOUGHT
    assert service.get(job_id).status == AppStatus.READY  # not moved back to 待回答
    assert len(fake_llm.calls) == 1  # nothing drafted again
    assert not await page.evaluate("window.__submitted")


async def test_a_scan_that_finds_nothing_keeps_the_confirmed_answers(service, monkeypatch):
    job_id = add_fixture_job(service)
    await confirm_two_answers(service, job_id)
    await service.browser.current_page(job_id).close()

    async def never(_page):
        return False

    monkeypatch.setattr("job_radar.prefill.scanner.wait_until_interactive", never)
    state = await service.prefill(job_id)
    assert state.blockers
    kept = {a.field.label: a for a in state.answers}
    assert kept["Why Example Co?"].confirmed and not kept["Why Example Co?"].filled

    monkeypatch.undo()
    await service.prefill(job_id)
    page = service.browser.current_page(job_id)
    assert await page.input_value("#question_1004") == "I like ranking problems."
