import pytest

from job_radar.apply.classify import classify
from job_radar.apply.history import block_of, entry_index, month_choice
from job_radar.apply.models import Category, FieldKind, FormField
from job_radar.prefill import scanner
from job_radar.prefill.filler import fill_answers
from job_radar.prefill.safe_page import search_queries
from tests.conftest import form_url

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def field(label, html_id, kind=FieldKind.TEXT, section="", options=()):
    return FormField(
        field_id=html_id,
        kind=kind,
        label=label,
        html_id=html_id,
        section=section,
        options=list(options),
    )


def by_label(answers):
    return {a.field.label: a for a in answers}


def test_block_and_entry_come_from_section_or_id():
    assert block_of(field("Start date month", "start-date-month-1")) == "employment"
    assert entry_index(field("Start date month", "start-date-month-1")) == 1
    assert block_of(field("School", "school--0")) == "education"
    assert block_of(field("Start date", "x", section="Education")) == "education"
    assert block_of(field("Start date", "x", section="Work Experience")) == "employment"
    assert block_of(field("When can you start?", "question_77")) is None
    assert entry_index(field("Current role", "current-role-0_1", FieldKind.CHECKBOX)) == 0


def test_month_choice_accepts_names_abbreviations_and_numbers():
    assert month_choice(MONTHS, 3) == "March"
    assert month_choice(["Jan", "Feb", "Mar."], 3) == "Mar."
    assert month_choice(["01", "02", "03"], 3) == "03"
    assert month_choice(["Spring", "Fall"], 3) is None


def test_employment_block_is_answered_from_applicant_yaml(profile):
    fields = [
        field("Company name", "company-name-0", section="Employment"),
        field("Title", "title-0", section="Employment"),
        field("Start date month", "start-date-month-0", FieldKind.COMBOBOX, "Employment", MONTHS),
        field("Start date year", "start-date-year-0", section="Employment"),
        field("End date month", "end-date-month-0", FieldKind.COMBOBOX, "Employment"),
        field("Current role", "current-role-0_1", FieldKind.CHECKBOX, "Employment"),
        field("Start date month", "start-date-month-1", FieldKind.COMBOBOX, "Employment"),
        field("End date year", "end-date-year-1", section="Employment"),
        field("Company name", "company-name-5", section="Employment"),
    ]
    decided, remaining = classify(fields, profile, resume_available=True)
    got = {a.field.field_id: a for a in decided}
    assert got["company-name-0"].value == "Example Labs"
    assert got["title-0"].value == "Data Science Intern"
    assert got["start-date-month-0"].value == "June"
    assert got["start-date-year-0"].value == "2025"
    assert got["start-date-year-0"].source == "employment[0]"
    # A current job has no end date; "current role" is ticked from applicant.yaml.
    assert got["end-date-month-0"].category == Category.USER
    assert got["current-role-0_1"].category == Category.AUTO
    assert got["current-role-0_1"].value == "true"
    # The second entry, and a month dropdown without known options: type the month's name.
    assert got["start-date-month-1"].value == "January"
    assert got["end-date-year-1"].value == "2024"
    # No sixth job in applicant.yaml: the basic "company" rule answers with the current one.
    assert got["company-name-5"].source == "basic.current_company"
    assert not remaining


def test_education_block_maps_degree_wording(profile):
    degrees = ["Bachelor's Degree", "Master's Degree", "Doctor of Philosophy (Ph.D.)"]
    fields = [
        field("School", "school--0", FieldKind.COMBOBOX, "Education"),
        field("Degree", "degree--0", FieldKind.COMBOBOX, "Education", degrees),
        field("Discipline", "discipline--0", FieldKind.COMBOBOX, "Education"),
        field("End date year", "end-date-year--0", section="Education"),
        field("Start date year", "start-date-year--0", section="Education"),
    ]
    got = {a.field.field_id: a for a in classify(fields, profile, resume_available=True)[0]}
    assert got["school--0"].value == "University of Southern California"
    assert got["degree--0"].value == "Master's Degree"
    assert got["discipline--0"].value == "Applied Data Science"
    assert got["end-date-year--0"].value == "2026"
    assert got["start-date-year--0"].category == Category.USER  # no start date on file


def test_a_graduation_date_picker_gets_a_whole_date(profile):
    # A calendar input reads only MM/DD/YYYY (Ramp); a plain text box gets MM/YYYY.
    plain = field("What is your graduation date?", "grad-plain", section="Education")
    picker = plain.model_copy(update={"field_id": "grad-picker", "picker": True})
    got = {a.field.field_id: a for a in classify([plain, picker], profile, True)[0]}
    month, year = got["grad-plain"].value.split("/")
    assert got["grad-picker"].value == f"{month}/01/{year}"


@pytest.mark.browser
async def test_history_blocks_fill_on_a_greenhouse_style_form(page, profile):
    await page.goto(form_url("history_like.html"))
    fields = await scanner.scan_fields(page)
    sections = {f.label: f.section for f in fields}
    assert sections["Start date month"] == "Employment"
    assert sections["Discipline"] == "Education"
    # The job title above the form is not a section; neither is Education after its block.
    assert sections["First Name"] == ""
    assert sections["When did you start writing Python?"] == ""

    decided, _ = classify(fields, profile, resume_available=False)
    auto = [a for a in decided if a.category == Category.AUTO]
    done = by_label(await fill_answers(page, auto, resume_path=None, overwrite=False))
    for label in (
        "Company name",
        "Start date month",
        "Start date year",
        "School",
        "Degree",
        "Discipline",
    ):
        assert done[label].filled, (label, done[label].error)
    single = page.locator(".select__single-value")
    assert await single.nth(0).inner_text() == "June"
    # "Applied Data Science" is not an option; the search falls back to "Data Science".
    assert await single.nth(4).inner_text() == "Data Science"
    assert await single.nth(3).inner_text() == "Master's Degree"
    assert await page.locator("#start-date-year-0").input_value() == "2025"


def test_shortened_searches_keep_at_least_two_words():
    assert search_queries("Applied Data Science") == ["Applied Data Science", "Data Science"]
    assert search_queries("University of Southern California") == [
        "University of Southern California",
        "Southern California",
    ]
    assert search_queries("Yes") == ["Yes"]


@pytest.mark.browser
@pytest.mark.parametrize(
    ("fallbacks", "picked"),
    [
        (["Data Science", "Computer Science"], "Data Science"),
        (["Robotics", "Computer Science"], "Computer Science"),
    ],
)
async def test_discipline_falls_back_in_order(page, profile, fallbacks, picked):
    entry = profile.applicant.education[0]
    entry.major, entry.major_fallbacks = "Quantum Basket Weaving", fallbacks
    await page.goto(form_url("history_like.html"))
    fields = [f for f in await scanner.scan_fields(page) if f.label == "Discipline"]
    decided, _ = classify(fields, profile, resume_available=False)
    assert decided[0].alternatives == fallbacks
    done = await fill_answers(page, decided, resume_path=None, overwrite=False)
    assert done[0].filled, done[0].error
    assert await page.locator(".select__single-value").nth(4).inner_text() == picked


@pytest.mark.browser
async def test_a_school_missing_from_the_list_is_not_swapped_for_a_similar_name(page, profile):
    # Greenhouse lists "National Taipei University of Technology" but not National Taipei
    # University: a different school, so nothing is picked.
    profile.applicant.education[0].school = "National Taipei University"
    await page.goto(form_url("history_like.html"))
    fields = [f for f in await scanner.scan_fields(page) if f.label == "School"]
    decided, _ = classify(fields, profile, resume_available=False)
    done = await fill_answers(page, decided, resume_path=None, overwrite=False)
    assert not done[0].filled and "National Taipei University" in done[0].error
    assert await page.locator(".select__single-value").nth(2).inner_text() == ""
