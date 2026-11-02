"""Data shapes shared by intake, classification, drafting, prefill and storage."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Source(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    JOBRIGHT = "jobright"
    OTHER = "other"


class JobRef(BaseModel):
    job_id: str  # "{source}:{source_job_id}"
    source: Source
    source_job_id: str
    url: str  # what the user pasted
    apply_url: str  # what the browser opens
    board_token: str | None = None
    company: str = ""
    title: str = ""
    location: str = ""
    description_text: str = ""
    # Greenhouse only: the board API's application questions, used to learn dropdown options.
    ats_questions: list[dict] = Field(default_factory=list)


class AppStatus(StrEnum):
    QUEUED = "queued"  # added, not filled yet
    PREFILLED = "prefilled"  # basics filled; questions waiting for the user
    READY = "ready"  # confirmed answers filled; waiting for the user to submit
    APPLIED = "applied"
    SKIPPED = "skipped"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Application(BaseModel):
    job: JobRef
    status: AppStatus
    resume_variant: str | None = None
    llm_cost_usd: float = 0.0
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None = None
    notes: str = ""


class FieldKind(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    TEL = "tel"
    URL = "url"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    COMBOBOX = "combobox"
    RADIO = "radio"
    CHECKBOXES = "checkboxes"
    CHECKBOX = "checkbox"
    FILE = "file"


TEXT_KINDS = frozenset(
    {
        FieldKind.TEXT,
        FieldKind.TEXTAREA,
        FieldKind.EMAIL,
        FieldKind.TEL,
        FieldKind.URL,
        FieldKind.NUMBER,
        FieldKind.DATE,
    }
)
CHOICE_KINDS = frozenset(
    {FieldKind.SELECT, FieldKind.COMBOBOX, FieldKind.RADIO, FieldKind.CHECKBOXES}
)


class FormField(BaseModel):
    field_id: str  # data-jr-id set by the scanner; groups use "g-" + first option's id
    frame_index: int = 0
    kind: FieldKind
    label: str
    name: str = ""
    html_id: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)
    option_ids: list[str] = Field(default_factory=list)  # radio / checkbox group members
    max_length: int | None = None
    value: str = ""
    placeholder: str = ""
    autocomplete: str = ""
    accept: str = ""
    section: str = ""  # heading of the form part it sits in, e.g. "Employment"
    picker: bool = False  # a text input that opens a calendar (react-datepicker)

    @property
    def hints(self) -> str:
        """name / id / autocomplete, lowercased, for attribute-based matching."""
        return " ".join(p for p in (self.name, self.html_id, self.autocomplete) if p).lower()


class Category(StrEnum):
    AUTO = "auto"  # filled from the profile or the answer bank
    SUGGESTED = "suggested"  # proposed from facts; the user confirms before it is filled
    THOUGHT = "thought"  # needs the user's thinking; comes with a draft
    USER = "user"  # the user decides personally (EEO, consent, attestations)
    FAILED = "failed"  # could not be handled automatically


class FieldAnswer(BaseModel):
    field: FormField
    category: Category
    value: str | list[str] = ""
    source: str = ""  # e.g. "basic.email", "answers", "learned", "eeo", "llm"
    note: str = ""
    facts_used: list[str] = Field(default_factory=list)
    filled: bool = False
    error: str = ""  # why writing this answer into the page failed
    # Fallback answers tried in order when `value` is not among a dropdown's options.
    alternatives: list[str] = Field(default_factory=list)
    # Names (schools) must match an option exactly: "X University of Technology" is not X.
    exact: bool = False
    # You confirmed this answer with ③; a re-scan (e.g. after the tab was closed) fills it again.
    confirmed: bool = False


class FormState(BaseModel):
    job_id: str
    page_url: str = ""
    scanned_at: datetime = Field(default_factory=utcnow)
    resume_variant: str | None = None
    resume_path: str | None = None
    blockers: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    answers: list[FieldAnswer] = Field(default_factory=list)
    llm_cost_usd: float = 0.0
    llm_error: str = ""
