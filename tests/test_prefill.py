"""Browser-level tests against local HTML fixtures (no network)."""

import pytest

from job_radar.apply.classify import classify
from job_radar.apply.models import Category, FieldAnswer, FieldKind
from job_radar.prefill import scanner
from job_radar.prefill.filler import fill_answers
from job_radar.prefill.safe_page import SafePage, UnsafeActionError
from tests.conftest import form_url

pytestmark = pytest.mark.browser


async def single_value(page, input_id: str) -> str:
    shell = page.locator(".select-shell", has=page.locator(f"#{input_id}"))
    return (await shell.locator(".select__single-value").text_content()).strip()


async def test_scan_greenhouse_style_form(page):
    await page.goto(form_url("greenhouse_like.html"))
    fields = await scanner.scan_fields(page)
    by = {f.label: f for f in fields}
    assert list(by) == [
        "First Name",
        "Last Name",
        "Email",
        "Country",
        "Phone",
        "Resume/CV",
        "LinkedIn Profile",
        "Are you open to working in-person in one of our offices 25% of the time?",
        "Do you require visa sponsorship?",
        "Why Example Co?",
        "When is the earliest you would want to start working with us?",
        "Gender",
    ]  # the aria-hidden helper input is skipped
    assert by["Country"].kind == FieldKind.COMBOBOX and by["Country"].required
    assert by["Resume/CV"].kind == FieldKind.FILE and by["Resume/CV"].required
    assert by["Why Example Co?"].kind == FieldKind.TEXTAREA
    assert by["Why Example Co?"].max_length == 2000
    assert not by["LinkedIn Profile"].required


async def test_scan_lever_style_form(page):
    await page.goto(form_url("lever_like.html"))
    fields = await scanner.scan_fields(page)
    by = {f.label: f for f in fields}
    assert by["Resume/CV"].kind == FieldKind.FILE
    assert by["Full name"].required
    assert by["Pronouns"].kind == FieldKind.CHECKBOXES
    assert by["Pronouns"].options == ["He/him", "She/her", "They/them"]
    eligibility = by["Are you eligible to work in the United States?"]
    assert eligibility.kind == FieldKind.CHECKBOXES and eligibility.options == ["Yes", "No"]
    sponsorship = by["Will you now or in the future require visa sponsorship?"]
    assert sponsorship.kind == FieldKind.RADIO and sponsorship.required
    assert by["Gender"].options == ["Male", "Female", "Decline to self-identify"]
    assert by["Additional information"].kind == FieldKind.TEXTAREA
    assert not any("auto-read" in f.label for f in fields)  # hidden status text is ignored


async def test_automatic_pass_fills_basics_and_never_submits(page, profile):
    await page.goto(form_url("greenhouse_like.html"))
    fields = await scanner.scan_fields(page)
    decided, remaining = classify(fields, profile, resume_available=True)
    auto = [a for a in decided if a.category == Category.AUTO]
    results = await fill_answers(
        page, auto, resume_path=profile.resume_variants()["ds"], overwrite=False
    )

    assert all(a.filled for a in results), [(a.field.label, a.error) for a in results]
    assert await page.input_value("#first_name") == "Jane"
    assert await page.input_value("#email") == "jane@example.com"
    assert await page.input_value("#phone") == "+1 213 555 0100"
    assert await single_value(page, "country") == "United States +1"
    assert await single_value(page, "question_1003") == "Yes"  # answer bank: sponsorship
    assert await page.evaluate("document.getElementById('resume').files[0].name") == "ds.pdf"
    start_date = "When is the earliest you would want to start working with us?"
    assert {f.label for f in remaining} >= {"Why Example Co?", start_date}
    assert not await page.evaluate("window.__submitted")


async def test_existing_values_survive_the_automatic_pass(page, profile):
    await page.goto(form_url("greenhouse_like.html"))
    await page.fill("#first_name", "Janet")
    fields = await scanner.scan_fields(page)
    decided, _ = classify(fields, profile, resume_available=True)
    first = next(a for a in decided if a.field.label == "First Name")
    [result] = await fill_answers(page, [first], resume_path=None, overwrite=False)
    assert await page.input_value("#first_name") == "Janet"
    assert not result.filled and "未覆寫" in result.note


async def test_confirmed_answers_fill_every_kind(page):
    await page.goto(form_url("lever_like.html"))
    by = {f.label: f for f in await scanner.scan_fields(page)}
    answers = [
        FieldAnswer(
            field=by["Additional information"],
            category=Category.THOUGHT,
            value="Happy to share more.",
        ),
        FieldAnswer(
            field=by["Will you now or in the future require visa sponsorship?"],
            category=Category.SUGGESTED,
            value="yes",
        ),
        FieldAnswer(field=by["Pronouns"], category=Category.USER, value=["She/her", "They/them"]),
        FieldAnswer(field=by["Gender"], category=Category.USER, value="Decline to self-identify"),
    ]
    results = await fill_answers(page, answers, resume_path=None, overwrite=True)
    assert all(a.filled for a in results), [(a.field.label, a.error) for a in results]
    assert await page.input_value("textarea[name=comments]") == "Happy to share more."
    assert await page.is_checked("input[name='cards[card-1][field1]'][value=Yes]")
    assert await page.is_checked("input[name=pronouns][value='She/her']")
    assert not await page.is_checked("input[name=pronouns][value='He/him']")
    assert await page.input_value("select[name='eeo[gender]']") == "Decline to self-identify"
    assert not await page.evaluate("window.__submitted")


async def test_unknown_option_is_reported_not_guessed(page):
    await page.goto(form_url("greenhouse_like.html"))
    by = {f.label: f for f in await scanner.scan_fields(page)}
    answer = FieldAnswer(
        field=by["Do you require visa sponsorship?"],
        category=Category.SUGGESTED,
        value="Maybe later",
    )
    [result] = await fill_answers(page, [answer], resume_path=None, overwrite=True)
    assert not result.filled and "手動選擇" in result.error
    assert await single_value(page, "question_1003") == ""


async def test_safe_page_refuses_submit_controls(page):
    await page.goto(form_url("greenhouse_like.html"))
    safe = SafePage(page)
    with pytest.raises(UnsafeActionError):
        await safe._safe_click(page.locator("button[type=submit]"))
    # A <button> without a type attribute inside a form is a submit button too.
    await page.evaluate(
        "document.getElementById('application-form')"
        ".insertAdjacentHTML('beforeend', '<button id=\"save\">Save draft</button>')"
    )
    with pytest.raises(UnsafeActionError):
        await safe._safe_click(page.locator("#save"))
    assert not await page.evaluate("window.__submitted")


async def test_guard_blocks_submission_only_while_filling(page):
    await page.goto(form_url("greenhouse_like.html"))
    safe = SafePage(page)
    form = "document.getElementById('application-form')"
    async with safe.guarded():
        await page.evaluate(f"{form}.requestSubmit()")
        await page.evaluate(f"{form}.submit()")
    assert not await page.evaluate("window.__submitted")
    assert await safe.blocked_submissions() == 2
    # Outside the guard, the person's own submit goes through untouched. (noValidate skips the
    # browser's required-field check, which would otherwise stop this simulated submit.)
    await page.evaluate(f"{form}.noValidate = true; {form}.requestSubmit()")
    assert await page.evaluate("window.__submitted")


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("login.html", "登入"), ("captcha_page.html", "真人驗證"), ("greenhouse_like.html", None)],
)
async def test_detect_blockers(page, fixture, expected):
    await page.goto(form_url(fixture))
    blockers, _ = await scanner.detect(page)
    if expected is None:
        assert blockers == []
    else:
        assert len(blockers) == 1 and expected in blockers[0]


async def test_a_tab_closed_mid_fill_is_reported_plainly(page):
    from job_radar.prefill.filler import PAGE_CLOSED

    await page.goto(form_url("greenhouse_like.html"))
    fields = {f.label: f for f in await scanner.scan_fields(page)}
    answers = [
        FieldAnswer(field=fields[label], category=Category.AUTO, value="x", source="test")
        for label in ("First Name", "Last Name")
    ]
    await page.close()
    done = await fill_answers(page, answers, resume_path=None, overwrite=True)
    assert [a.error for a in done] == [PAGE_CLOSED, PAGE_CLOSED]


async def test_a_date_picker_is_committed_and_does_not_cover_the_next_field(page):
    # Ramp, 2026-10-26: the calendar stayed open over "Still Student?", so ticking it failed.
    await page.goto(form_url("datepicker_like.html"))
    by = {f.label: f for f in await scanner.scan_fields(page)}
    date = by["What is your graduation date?"]
    assert date.picker
    answers = [
        FieldAnswer(field=date, category=Category.AUTO, value="05/01/2027"),
        FieldAnswer(field=by["Still Student?"], category=Category.SUGGESTED, value="true"),
    ]
    results = await fill_answers(page, answers, resume_path=None, overwrite=True)
    assert all(a.filled for a in results), [(a.field.label, a.error) for a in results]
    assert await page.input_value("#grad") == "05/01/2027"
    assert await page.is_hidden(".react-datepicker-popper")
    assert await page.is_checked("#still")
    assert not await page.evaluate("window.__submitted")


async def test_a_date_the_calendar_cannot_read_is_reported(page):
    await page.goto(form_url("datepicker_like.html"))
    by = {f.label: f for f in await scanner.scan_fields(page)}
    answer = FieldAnswer(
        field=by["What is your graduation date?"], category=Category.THOUGHT, value="05/2027"
    )
    [result] = await fill_answers(page, [answer], resume_path=None, overwrite=True)
    assert not result.filled and "月/日/年" in result.error
