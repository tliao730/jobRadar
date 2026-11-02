"""Deterministic decisions about form fields, made before any LLM call.

- basic profile fields (name, email, phone, links...) are filled from applicant.yaml
- employment / education blocks are filled from its `employment` and `education` lists
- questions matching the answer bank are filled from it
- demographic / EEO / consent / attestation questions are left for the user
- the resume upload gets the chosen resume PDF
Everything else is returned as "remaining" for the drafting step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_radar.apply.history import answer_history
from job_radar.apply.models import TEXT_KINDS, Category, FieldAnswer, FieldKind, FormField
from job_radar.profile import Basic, Profile

_TEXTISH = TEXT_KINDS
_PLACE = TEXT_KINDS | {FieldKind.SELECT, FieldKind.COMBOBOX}


@dataclass(frozen=True)
class BasicRule:
    key: str  # Basic attribute (or "full_name")
    label: str  # regex on the normalized label
    attrs: str = ""  # regex on name / id / autocomplete, checked one attribute at a time
    kinds: frozenset[FieldKind] = _TEXTISH


# First match wins, so more specific rules come first.
BASIC_RULES: tuple[BasicRule, ...] = (
    BasicRule("preferred_name", r"preferred (first )?name|nickname", r"preferred_?name"),
    BasicRule(
        "first_name", r"^(legal )?first name|^given name|^first$", r"first_?name|given-name|^fname$"
    ),
    BasicRule(
        "last_name",
        r"^(legal )?last name|^surname|^family name|^last$",
        r"last_?name|family-name|^lname$",
    ),
    BasicRule(
        "full_name",
        r"^(full |legal |your )?name$|full (legal )?name|legal name",
        r"^(full_?)?name$",
    ),
    BasicRule("email", r"\be-?mail\b", r"e-?mail"),
    BasicRule("phone", r"phone|mobile|\bcell\b", r"phone|^tel$|^tel-"),
    BasicRule("linkedin", r"linked ?in", r"linkedin"),
    BasicRule("github", r"git ?hub", r"github"),
    BasicRule(
        "website", r"website|portfolio|personal (site|url|page)|\bblog\b", r"website|portfolio"
    ),
    BasicRule(
        "current_company",
        r"current (company|employer)|^(company|employer)( name)?$|most recent (company|employer)",
        r"^org$|current_?company",
    ),
    BasicRule("current_title", r"current (job )?title|^(job )?title$", r"current_?title"),
    BasicRule(
        "location",
        r"^(current )?location|where are you (currently )?(located|based)"
        r"|city,? (and )?state|^address$",
        r"location",
        _PLACE,
    ),
    BasicRule("city", r"^city$", r"(^|_)city$", _PLACE),
    BasicRule("state", r"^state( ?/ ?province)?$", r"(^|_)state$", _PLACE),
    BasicRule("country", r"^country( of residence)?$", r"country", _PLACE),
)

SENSITIVE = re.compile(
    r"gender|\bsex\b|\brace\b|ethnic|hispanic|latin[oax]|veteran|disabilit|sexual orientation"
    r"|transgender|lgbt|pronoun|demographic|diversity|self[- ]?identif|\beeo"
    r"|date of birth|birth ?date|\bage\b|religio|marital|criminal|convicted|felony",
    re.IGNORECASE,
)
CONSENT = re.compile(
    r"\bi (certify|acknowledge|agree|consent|confirm|attest|understand)\b"
    r"|terms (and|&) conditions|privacy (policy|notice)|\bconsent\b|signature|sign (here|below)"
    r"|arbitrat|acknowledg"
    r"|e-?sign",
    re.IGNORECASE,
)
RESUME = re.compile(r"resume|résumé|\bcv\b|curriculum", re.IGNORECASE)
COVER_LETTER = re.compile(r"cover ?letter", re.IGNORECASE)


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().lower()


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def choose_option(options: list[str], desired: str, exact: bool = False) -> str | None:
    """Map a desired answer onto one of the field's options, or None if nothing fits.
    With `exact`, only an option that equals the answer (ignoring case and punctuation)."""
    d = _norm(desired)
    if not d:
        return None
    normed = [(o, _norm(o)) for o in options if _norm(o)]
    for option, n in normed:
        if n == d:
            return option
    if exact:
        return None
    for option, n in normed:
        if n.startswith(d + " "):
            return option
    for option, n in normed:
        if f" {d} " in f" {n} ":
            return option
    for option, n in normed:
        if len(n) >= 4 and f" {n} " in f" {d} ":
            return option
    return _same_meaning(normed, d)


_FILLER = {"i", "am", "a", "an", "the", "or", "and", "of", "to", "my", "be", "is", "are"}
_NEGATION = {"no", "not", "non", "never", "don", "t"}


def _same_meaning(normed: list[tuple[str, str]], desired: str) -> str | None:
    """Sentence answers worded differently ("I am not a protected veteran" vs "No, I am not a
    veteran or active member"): most of the desired content words appear in exactly one option,
    and both say no, or both don't."""
    want = set(desired.split()) - _FILLER
    if len(want) < 3:
        return None
    negative = bool(want & _NEGATION)
    hits = []
    for option, n in normed:
        words = set(n.split()) - _FILLER
        if bool(words & _NEGATION) != negative:
            continue
        shared = len((want - _NEGATION) & words) / len(want - _NEGATION)
        if shared >= 0.5:
            hits.append((shared, option))
    hits.sort(reverse=True)
    if hits and (len(hits) == 1 or hits[0][0] > hits[1][0]):
        return hits[0][1]
    return None


def _basic_value(basic: Basic, key: str) -> str:
    return basic.full_name if key == "full_name" else getattr(basic, key, "")


def _match_basic(field: FormField) -> BasicRule | None:
    label = normalize_label(field.label)
    attrs = [a.lower() for a in (field.name, field.html_id, field.autocomplete) if a]
    for rule in BASIC_RULES:
        if field.kind not in rule.kinds:
            continue
        if re.search(rule.label, label) or (
            rule.attrs and any(re.search(rule.attrs, a) for a in attrs)
        ):
            return rule
    return None


def _value_for(field: FormField, answer: str | list[str]) -> tuple[str | list[str], str]:
    """Fit an answer to the field's kind. Returns (value, problem); problem is "" when it fits."""
    wanted = answer if isinstance(answer, list) else [answer]
    if field.kind in (FieldKind.SELECT, FieldKind.RADIO) or (
        field.kind == FieldKind.COMBOBOX and field.options
    ):
        choice = choose_option(field.options, wanted[0])
        return (choice, "") if choice else (wanted[0], f"答案「{wanted[0]}」不在選項中")
    if field.kind == FieldKind.CHECKBOXES:
        picked = [c for w in wanted if (c := choose_option(field.options, w))]
        missing = [w for w in wanted if not choose_option(field.options, w)]
        return picked, (f"答案「{'、'.join(missing)}」不在選項中" if missing else "")
    if field.kind == FieldKind.CHECKBOX:
        return ("true" if _norm(wanted[0]) in {"yes", "true", "checked", "1"} else "false"), ""
    return "; ".join(wanted) if isinstance(answer, list) else answer, ""


def enrich_options(fields: list[FormField], ats_questions: list[dict]) -> list[FormField]:
    """Greenhouse dropdowns hide their options until opened; the board API lists them."""
    by_name = {
        f["name"]: f.get("values") or []
        for q in ats_questions
        for f in q.get("fields", [])
        if f.get("name")
    }
    out = []
    for field in fields:
        values = by_name.get(field.html_id) or by_name.get(field.name)
        if field.kind == FieldKind.COMBOBOX and not field.options and values:
            field = field.model_copy(update={"options": values})
        out.append(field)
    return out


def classify(
    fields: list[FormField], profile: Profile, resume_available: bool
) -> tuple[list[FieldAnswer], list[FormField]]:
    decided: list[FieldAnswer] = []
    remaining: list[FormField] = []
    basic = profile.applicant.basic
    rules = profile.answer_rules()

    for field in fields:
        label = field.label.strip()
        if not label:
            if field.required:
                decided.append(
                    FieldAnswer(
                        field=field,
                        category=Category.FAILED,
                        note="無法辨識這個必填欄位的題目，請在瀏覽器手動處理",
                    )
                )
            continue
        text = f"{label} {field.name}"

        if field.kind == FieldKind.FILE:
            decided.append(_file_answer(field, resume_available))
            continue

        # Rules the user wrote (or chose to remember) win over every heuristic below.
        bank = next((r for r in rules if r.matches(label)), None)
        if bank:
            fitted, problem = _value_for(field, bank.answer)
            source = "learned" if bank in profile.learned else "answers"
            decided.append(
                FieldAnswer(
                    field=field,
                    category=Category.SUGGESTED if problem else Category.AUTO,
                    value=fitted,
                    source=source,
                    note=problem,
                )
            )
            continue

        if SENSITIVE.search(text) or SENSITIVE.search(field.section):
            decided.append(_sensitive_answer(field, profile))
            continue

        history = answer_history(field, profile.applicant)
        if history:
            decided.append(history)
            continue

        rule = _match_basic(field)
        if rule:
            value = _basic_value(basic, rule.key)
            if value:
                fitted, problem = _value_for(field, value)
                decided.append(
                    FieldAnswer(
                        field=field,
                        category=Category.SUGGESTED if problem else Category.AUTO,
                        value=fitted,
                        source=f"basic.{rule.key}",
                        note=problem,
                    )
                )
            else:
                decided.append(
                    FieldAnswer(
                        field=field,
                        category=Category.USER,
                        source=f"basic.{rule.key}",
                        note=f"applicant.yaml 的 basic.{rule.key} 沒有填",
                    )
                )
            continue

        if CONSENT.search(text) or field.kind == FieldKind.CHECKBOX:
            decided.append(
                FieldAnswer(
                    field=field, category=Category.USER, note="同意、聲明或勾選類題目，由你自己決定"
                )
            )
            continue

        remaining.append(field)
    return decided, remaining


def _file_answer(field: FormField, resume_available: bool) -> FieldAnswer:
    text = f"{field.label} {field.name} {field.html_id}"
    if RESUME.search(text) and not COVER_LETTER.search(text):
        if resume_available:
            return FieldAnswer(field=field, category=Category.AUTO, value="resume", source="resume")
        return FieldAnswer(
            field=field,
            category=Category.FAILED,
            note="找不到履歷 PDF：請放到 profile/resumes/，或放在這個職缺的資料夾",
        )
    if COVER_LETTER.search(text):
        return FieldAnswer(field=field, category=Category.USER, note="cover letter 檔案請自行上傳")
    return FieldAnswer(field=field, category=Category.USER, note="這個檔案請自行上傳")


def _sensitive_answer(field: FormField, profile: Profile) -> FieldAnswer:
    text = f"{field.label} {field.name}".lower()
    for keyword, answer in profile.applicant.eeo.items():
        if answer and keyword.lower() in text:
            fitted, problem = _value_for(field, answer)
            if not problem:
                return FieldAnswer(field=field, category=Category.AUTO, value=fitted, source="eeo")
    return FieldAnswer(
        field=field, category=Category.USER, note="人口統計或自願揭露題，留給你自己選"
    )
