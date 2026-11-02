import pytest

from job_radar.apply.classify import choose_option, classify, enrich_options
from job_radar.apply.models import Category, FieldKind, FormField
from job_radar.profile import AnswerRule


def field(label: str, kind: FieldKind = FieldKind.TEXT, **extra) -> FormField:
    return FormField(field_id=f"f0-{abs(hash(label)) % 10000}", kind=kind, label=label, **extra)


def by_label(answers):
    return {a.field.label: a for a in answers}


def test_basic_fields_come_from_the_profile(profile):
    fields = [
        field("First Name", autocomplete="given-name"),
        field("Last Name"),
        field("Full name", name="name"),
        field("Email", FieldKind.EMAIL),
        field("Phone", FieldKind.TEL),
        field("LinkedIn Profile"),
        field("Current company", name="org"),
        field("Country", FieldKind.COMBOBOX),
    ]
    decided, remaining = classify(fields, profile, resume_available=True)
    got = by_label(decided)
    assert not remaining
    assert got["First Name"].value == "Jane"
    assert got["Last Name"].value == "Doe"
    assert got["Full name"].value == "Jane Doe"
    assert got["Email"].value == "jane@example.com"
    assert got["Phone"].source == "basic.phone"
    assert got["LinkedIn Profile"].value.endswith("/janedoe")
    assert got["Current company"].value == "Example Labs"
    assert got["Country"].value == "United States"
    assert all(a.category == Category.AUTO for a in decided)


def test_missing_profile_value_is_left_for_the_user(profile):
    decided, _ = classify([field("Website")], profile, resume_available=True)
    assert decided[0].category == Category.USER
    assert "basic.website" in decided[0].note


def test_answer_bank_maps_onto_options(profile):
    radio = field(
        "Are you legally authorized to work in the US?",
        FieldKind.RADIO,
        options=["Yes, I am authorized", "No, I am not"],
        option_ids=["a", "b"],
    )
    select = field(
        "Will you require visa sponsorship?",
        FieldKind.SELECT,
        options=["I will need sponsorship", "Not applicable"],
    )
    decided, _ = classify([radio, select], profile, resume_available=True)
    got = by_label(decided)
    assert got[radio.label].category == Category.AUTO
    assert got[radio.label].value == "Yes, I am authorized"
    # "Yes" has no matching option here, so the user confirms instead of a wrong guess.
    assert got[select.label].category == Category.SUGGESTED
    assert "不在選項中" in got[select.label].note


def test_empty_answer_bank_entries_are_ignored(profile):
    _, remaining = classify([field("How did you hear about us?")], profile, resume_available=True)
    assert [f.label for f in remaining] == ["How did you hear about us?"]


def test_learned_answers_win_and_are_labelled(profile):
    profile.learned = [AnswerRule(match="sponsorship", answer="No")]
    q = field("Do you require visa sponsorship?", FieldKind.SELECT, options=["Yes", "No"])
    decided, _ = classify([q], profile, resume_available=True)
    assert decided[0].value == "No"
    assert decided[0].source == "learned"


@pytest.mark.parametrize(
    "label",
    [
        "Gender",
        "Are you Hispanic/Latino?",
        "Veteran Status",
        "Disability status",
        "What is your age range?",
        "Pronouns",
    ],
)
def test_demographic_questions_are_left_for_the_user(profile, label):
    decided, remaining = classify(
        [field(label, FieldKind.SELECT, options=["A", "B"])], profile, resume_available=True
    )
    assert not remaining
    assert decided[0].category == Category.USER


def test_eeo_preferences_fill_when_an_option_matches(profile):
    profile.applicant.eeo = {"gender": "Decline to self-identify"}
    q = field("Gender", FieldKind.SELECT, options=["Male", "Female", "Decline to self-identify"])
    decided, _ = classify([q], profile, resume_available=True)
    assert decided[0].category == Category.AUTO
    assert decided[0].source == "eeo"


def test_eeo_signature_fields_are_not_mistaken_for_name(profile):
    q = field("Name", name="eeo[disabilitySignature]")
    decided, _ = classify([q], profile, resume_available=True)
    assert decided[0].category == Category.USER


@pytest.mark.parametrize(
    "label",
    [
        "I certify that the information is true",
        "Agreement to Arbitrate",
        "I acknowledge the privacy notice",
    ],
)
def test_consent_and_attestations_are_left_for_the_user(profile, label):
    decided, remaining = classify(
        [field(label, FieldKind.SELECT, options=["Yes", "No"])], profile, resume_available=True
    )
    assert not remaining
    assert decided[0].category == Category.USER


def test_single_checkboxes_are_the_users_call(profile):
    decided, _ = classify(
        [field("Send me future job alerts", FieldKind.CHECKBOX)], profile, resume_available=True
    )
    assert decided[0].category == Category.USER


def test_resume_upload(profile):
    resume = field("Resume/CV", FieldKind.FILE)
    cover = field("Cover Letter", FieldKind.FILE)
    decided, _ = classify([resume, cover], profile, resume_available=True)
    got = by_label(decided)
    assert got["Resume/CV"].category == Category.AUTO
    assert got["Cover Letter"].category == Category.USER

    decided, _ = classify([resume], profile, resume_available=False)
    assert decided[0].category == Category.FAILED


def test_open_questions_go_to_drafting(profile):
    q = field("Why Example Co?", FieldKind.TEXTAREA, required=True)
    decided, remaining = classify([q], profile, resume_available=True)
    assert not decided
    assert remaining == [q]


def test_unlabelled_fields(profile):
    decided, remaining = classify(
        [field("", required=True), FormField(field_id="x", kind=FieldKind.TEXT, label="")],
        profile,
        resume_available=True,
    )
    assert [a.category for a in decided] == [Category.FAILED]
    assert not remaining


@pytest.mark.parametrize(
    ("options", "desired", "expected"),
    [
        (["Yes", "No"], "yes", "Yes"),
        (
            ["No, I do not need sponsorship", "Yes, I will need sponsorship"],
            "No",
            "No, I do not need sponsorship",
        ),
        (["Not applicable", "No"], "No", "No"),
        (["Not applicable", "Yes"], "No", None),
        (["United States +1", "Canada +1"], "United States", "United States +1"),
        (["United States"], "United States of America", "United States"),
        (["Male", "Female"], "", None),
        # Same meaning, different wording: most content words shared and the negation agrees.
        (
            ["Yes, I am a veteran or active member", "No, I am not a veteran or active member"],
            "I am not a protected veteran",
            "No, I am not a veteran or active member",
        ),
        (
            ["Yes, I am a protected veteran", "I prefer not to say"],
            "I am not a protected veteran",
            None,
        ),
        (["Asian (Not Hispanic or Latino)", "White"], "Asian", "Asian (Not Hispanic or Latino)"),
    ],
)
def test_choose_option(options, desired, expected):
    assert choose_option(options, desired) == expected


def test_enrich_options_uses_greenhouse_questions():
    combo = FormField(
        field_id="f0-1", kind=FieldKind.COMBOBOX, label="Visa?", html_id="question_1003"
    )
    other = FormField(field_id="f0-2", kind=FieldKind.TEXT, label="Why?", html_id="question_1004")
    questions = [{"label": "Visa?", "fields": [{"name": "question_1003", "values": ["Yes", "No"]}]}]
    enriched = enrich_options([combo, other], questions)
    assert enriched[0].options == ["Yes", "No"]
    assert enriched[1].options == []


def test_diversity_sections_are_left_to_me(profile):
    field = FormField(
        field_id="f1", kind=FieldKind.COMBOBOX, label="I identify as", section="Diversity"
    )
    decided, remaining = classify([field], profile, resume_available=True)
    assert decided[0].category == Category.USER and not remaining
