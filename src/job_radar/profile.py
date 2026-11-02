"""The applicant's own facts: profile/applicant.yaml, highlights.yaml, resumes, learned answers."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader

log = logging.getLogger(__name__)

LEARNED_FILE = "answers_learned.yaml"


class ProfileError(RuntimeError):
    """The profile is missing or invalid; the message tells the user how to fix it."""


class Basic(BaseModel):
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    email: str = ""
    phone: str = ""
    country: str = ""
    city: str = ""
    state: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    current_company: str = ""
    current_title: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    # What to pick in a discipline / field-of-study list that has no option for `major`, in order.
    major_fallbacks: list[str] = Field(default_factory=list)
    start: str = ""
    end: str = ""
    gpa: str = ""


class Employment(BaseModel):
    company: str = ""
    title: str = ""
    location: str = ""
    start: str = ""  # YYYY-MM
    end: str = ""  # YYYY-MM; empty or "present" for the current job

    @property
    def current(self) -> bool:
        return self.end.strip().lower() in ("", "present", "current", "now")


class AnswerRule(BaseModel):
    """Answer `answer` to any question whose label matches the regex `match`."""

    match: str
    answer: str | list[str] = ""
    note: str = ""

    def is_set(self) -> bool:
        return bool(self.answer if isinstance(self.answer, str) else any(self.answer))

    def matches(self, label: str) -> bool:
        try:
            return re.search(self.match, label, re.IGNORECASE) is not None
        except re.error:
            log.warning("答案庫的 regex 無效：%s", self.match)
            return False


class Applicant(BaseModel):
    basic: Basic = Field(default_factory=Basic)
    education: list[Education] = Field(default_factory=list)
    employment: list[Employment] = Field(default_factory=list)  # most recent first
    answers: list[AnswerRule] = Field(default_factory=list)
    eeo: dict[str, str] = Field(default_factory=dict)


class Highlight(BaseModel):
    id: str
    context: str = ""
    did: str
    results: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")


class Profile:
    def __init__(
        self,
        profile_dir: Path,
        applicant: Applicant,
        highlights: list[Highlight],
        learned: list[AnswerRule],
    ) -> None:
        self.profile_dir = profile_dir
        self.applicant = applicant
        self.highlights = highlights
        self.learned = learned

    @property
    def resumes_dir(self) -> Path:
        return self.profile_dir / "resumes"

    def resume_variants(self) -> dict[str, Path]:
        if not self.resumes_dir.is_dir():
            return {}
        return {p.stem: p for p in sorted(self.resumes_dir.glob("*.pdf"))}

    def answer_rules(self) -> list[AnswerRule]:
        """Learned answers first: they come from the user's latest decisions."""
        return [r for r in [*self.learned, *self.applicant.answers] if r.is_set()]

    def facts_for_llm(self, resume_path: Path | None) -> str:
        """Everything the drafting model may cite, with contact details left out."""
        a = self.applicant
        basic = {
            "name": a.basic.full_name,
            "preferred_name": a.basic.preferred_name,
            "location": a.basic.location
            or ", ".join(p for p in (a.basic.city, a.basic.state) if p),
            "country": a.basic.country,
            "current_company": a.basic.current_company,
            "current_title": a.basic.current_title,
        }
        parts = [
            "## applicant",
            yaml.safe_dump({k: v for k, v in basic.items() if v}, allow_unicode=True).strip(),
        ]
        if a.education:
            edu = [e.model_dump(exclude_defaults=True) for e in a.education if e.school]
            parts += ["## education", yaml.safe_dump(edu, allow_unicode=True).strip()]
        known = [{"question_pattern": r.match, "answer": r.answer} for r in self.answer_rules()]
        if known:
            parts += ["## known_answers", yaml.safe_dump(known, allow_unicode=True).strip()]
        if self.highlights:
            hl = [h.model_dump(exclude_defaults=True) for h in self.highlights]
            parts += ["## highlights", yaml.safe_dump(hl, allow_unicode=True).strip()]
        if resume_path is not None:
            text = resume_text(resume_path)
            text = _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))
            parts += ["## resume", text or "(resume text could not be extracted)"]
        return "\n\n".join(parts)

    def save_learned(self, rule: AnswerRule) -> None:
        self.learned = [r for r in self.learned if r.match != rule.match]
        self.learned.insert(0, rule)
        path = self.profile_dir / LEARNED_FILE
        header = "# 由申請助手自動維護：在介面勾選「記住這個答案」時寫入。可以手動修改或刪除。\n"
        body = yaml.safe_dump(
            [r.model_dump(exclude_defaults=True) for r in self.learned],
            allow_unicode=True,
            sort_keys=False,
        )
        path.write_text(header + body, encoding="utf-8")


def resume_text(path: Path) -> str:
    stat = path.stat()
    return _resume_text_cached(str(path), stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _resume_text_cached(path: str, _mtime_ns: int) -> str:
    try:
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many exception types for malformed files
        log.warning("無法讀取履歷 PDF %s：%s", path, exc)
        return ""
    return re.sub(r"[ \t]+", " ", text).strip()


def label_rule(label: str) -> str:
    """A regex matching this exact question label, tolerant of spacing and case."""
    words = [re.escape(w) for w in label.split()]
    return r"^\s*" + r"\s+".join(words) + r"\s*$"


def _load_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path} 不是有效的 YAML：{exc}") from exc


def _load_list(path: Path) -> list:
    if not path.exists():
        return []
    data = _load_yaml(path) or []
    if not isinstance(data, list):
        raise ProfileError(f"{path} 應該是一個清單")
    return data


def load_profile(profile_dir: Path) -> Profile:
    applicant_path = profile_dir / "applicant.yaml"
    if not applicant_path.exists():
        raise ProfileError(
            f"找不到 {applicant_path}。先執行 `uv run job-radar init-profile`，再填寫基本資料。"
        )
    try:
        applicant = Applicant.model_validate(_load_yaml(applicant_path) or {})
        highlights = [
            Highlight.model_validate(h) for h in _load_list(profile_dir / "highlights.yaml")
        ]
        learned = [AnswerRule.model_validate(r) for r in _load_list(profile_dir / LEARNED_FILE)]
    except ValidationError as exc:
        raise ProfileError(f"profile 格式錯誤：{exc}") from exc
    return Profile(profile_dir, applicant, highlights, learned)
