from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from job_radar.apply.drafts import DraftResult, FieldDraft
from job_radar.llm import LLMUsage
from job_radar.profile import Profile, load_profile

FIXTURES = Path(__file__).parent / "fixtures"

APPLICANT = {
    "basic": {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@example.com",
        "phone": "+1 213 555 0100",
        "country": "United States",
        "location": "Los Angeles, CA",
        "linkedin": "https://www.linkedin.com/in/janedoe",
        "github": "https://github.com/janedoe",
        "current_company": "Example Labs",
    },
    "education": [
        {
            "school": "University of Southern California",
            "degree": "M.S.",
            "major": "Applied Data Science",
            "end": "2026-05",
        }
    ],
    "employment": [
        {"company": "Example Labs", "title": "Data Science Intern", "start": "2025-06", "end": ""},
        {"company": "Acme Analytics", "title": "Analyst", "start": "2023-01", "end": "2024-08"},
    ],
    "answers": [
        {"match": "(legally )?(authorized|eligible) to work", "answer": "Yes"},
        {"match": "(require|need).*sponsorship", "answer": "Yes"},
        {"match": "how did you hear", "answer": ""},
    ],
    "eeo": {},
}

HIGHLIGHTS = [
    {
        "id": "rec-ranking",
        "context": "Data Science Intern, Example Labs (Summer 2025)",
        "did": "Rebuilt candidate ranking with LightGBM LambdaRank",
        "results": ["CTR +4.2% in a two-week A/B test"],
        "skills": ["LightGBM", "learning-to-rank", "A/B testing", "Python"],
    }
]


def make_pdf(path: Path, text: str) -> Path:
    """A one-page PDF whose text pypdf can extract."""
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 11 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "profile"
    (directory / "resumes").mkdir(parents=True)
    (directory / "applicant.yaml").write_text(
        yaml.safe_dump(APPLICANT, allow_unicode=True), encoding="utf-8"
    )
    (directory / "highlights.yaml").write_text(yaml.safe_dump(HIGHLIGHTS), encoding="utf-8")
    make_pdf(
        directory / "resumes" / "ds.pdf",
        "Jane Doe jane@example.com +1 213 555 0100 Built ranking models at Example Labs",
    )
    return directory


@pytest.fixture
def profile(profile_dir: Path) -> Profile:
    return load_profile(profile_dir)


def fields_in_prompt(user_message: str) -> list[dict]:
    block = re.search(r"<form_fields>\n(.*)</form_fields>", user_message, re.S)
    return yaml.safe_load(block.group(1)) if block else []


def default_drafts(user_message: str) -> DraftResult:
    """Choice fields get their first option; free-text fields get a recognizable draft."""
    drafts = []
    for field in fields_in_prompt(user_message):
        options = field.get("options") or []
        if field["type"] == "checkboxes":
            drafts.append(
                FieldDraft(
                    field_id=field["field_id"],
                    category="suggested",
                    answer="",
                    answers=options[:1],
                    note="",
                    facts_used=[],
                )
            )
        elif options:
            drafts.append(
                FieldDraft(
                    field_id=field["field_id"],
                    category="suggested",
                    answer=options[0],
                    answers=[],
                    note="依據履歷",
                    facts_used=["resume"],
                )
            )
        else:
            drafts.append(
                FieldDraft(
                    field_id=field["field_id"],
                    category="thought",
                    answer=f"Draft: {field['question']}",
                    answers=[],
                    note="請補充細節",
                    facts_used=["rec-ranking"],
                )
            )
    return DraftResult(drafts=drafts)


class FakeLLM:
    model = "fake-model"

    def __init__(self, respond=default_drafts) -> None:
        self.respond = respond
        self.calls: list[dict] = []

    def parse(self, *, system: str, user: str, output_model: type) -> tuple:
        self.calls.append({"system": system, "user": user, "output_model": output_model})
        return self.respond(user), LLMUsage(self.model, 1200, 300, 0.0054)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
async def page():
    """A headless Chrome page; skips when Chrome is not installed."""
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
    except PlaywrightError as exc:
        await playwright.stop()
        pytest.skip(f"Chrome 無法啟動：{exc.message.splitlines()[0]}")
    page = await browser.new_page()
    yield page
    await browser.close()
    await playwright.stop()


def form_url(name: str) -> str:
    return (FIXTURES / "forms" / name).as_uri()
