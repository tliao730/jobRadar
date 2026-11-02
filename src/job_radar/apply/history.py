"""Employment and education blocks (Greenhouse's "Employment" / "Education", Workday's work
history...): which entry and which part a field asks for, answered from applicant.yaml.

A field belongs to a block by its section heading or its id (`start-date-month-0`,
`school--0`); the trailing number picks the entry, most recent first.
"""

from __future__ import annotations

import re
from calendar import month_abbr, month_name
from datetime import date

from job_radar.apply.models import Category, FieldAnswer, FieldKind, FormField
from job_radar.profile import Applicant, Education, Employment

EMPLOYMENT_SECTION = re.compile(r"employment|work (experience|history)|^experience$", re.I)
EDUCATION_SECTION = re.compile(r"education", re.I)
EMPLOYMENT_IDS = re.compile(r"^(company|employer|title|start-date|end-date|current-role)", re.I)
EDUCATION_IDS = re.compile(r"^(school|degree|discipline|education)", re.I)
# Labels that only ever ask about education, whatever section they sit in.
EDUCATION_LABELS = re.compile(
    r"^(school|university|college|degree|discipline|major|field of study|gpa)\b"
    r"|graduation date|when (do|will) you graduate|still (a )?student",
    re.I,
)
_INDEX = re.compile(r"[-_]+(\d+)(?:_\d+)?$")

DEGREES = (  # (pattern on applicant.yaml's degree, wording Greenhouse-style lists use)
    (r"m\.?b\.?a", "Master of Business Administration (M.B.A.)"),
    (r"ph\.?\s?d|doctor of philosophy", "Doctor of Philosophy (Ph.D.)"),
    (r"^m\.?\s?(s|sc|a|eng|phil)\.?$|master", "Master's Degree"),
    (r"^b\.?\s?(s|sc|a|b\.?a|eng)\.?$|bachelor", "Bachelor's Degree"),
    (r"associate", "Associate's Degree"),
    (r"j\.?d", "Juris Doctor (J.D.)"),
)


def entry_index(field: FormField) -> int:
    m = _INDEX.search(field.html_id or field.name or "")
    return int(m.group(1)) if m else 0


def block_of(field: FormField) -> str | None:
    """ "employment", "education" or None."""
    ident = field.html_id or field.name
    if (
        EDUCATION_SECTION.search(field.section)
        or EDUCATION_IDS.search(ident)
        or EDUCATION_LABELS.search(field.label.strip())
    ):
        return "education"
    if EMPLOYMENT_SECTION.search(field.section) or EMPLOYMENT_IDS.search(ident):
        return "employment"
    return None


def answer_history(field: FormField, applicant: Applicant) -> FieldAnswer | None:
    block = block_of(field)
    if block is None:
        return None
    entries = applicant.employment if block == "employment" else applicant.education
    index = entry_index(field)
    if index >= len(entries):
        return None
    entry = entries[index]
    label = field.label.lower()
    source = f"{block}[{index}]"

    if block == "education" and field.kind == FieldKind.CHECKBOX:
        if re.search(r"student|currently (attend|enrolled)|in progress", label):
            end = _parse_month(entry.end)
            still = end is not None and end >= (date.today().year, date.today().month)
            return FieldAnswer(
                field=field,
                category=Category.SUGGESTED,
                value="true" if still else "false",
                source=source,
                note="依 applicant.yaml 的預計畢業時間判斷",
            )
        return None

    if block == "employment" and field.kind == FieldKind.CHECKBOX:
        if re.search(r"current|present|currently work", label):
            # Single checkboxes are normally left to you; "current role" is a fact from
            # applicant.yaml (end left empty), so it is filled like the dates.
            return FieldAnswer(
                field=field,
                category=Category.AUTO,
                value="true" if entry.current else "false",
                source=source,
            )
        return None

    value = _part(label, entry)
    if value is None:
        return None
    if value is DEGREE:
        # Choice lists use wording like "Master's Degree"; a text box takes what you wrote.
        choice = field.options or field.kind == FieldKind.COMBOBOX
        value = _degree(entry.degree) if choice else entry.degree
    if value is CURRENT_JOB:
        return FieldAnswer(
            field=field,
            category=Category.USER,
            source=source,
            note="目前的工作沒有結束日期：留空，勾「目前在職」那一格",
        )
    if value == "":
        return FieldAnswer(field=field, category=Category.USER, source=source, note=_EMPTY_NOTE)
    if isinstance(value, tuple):  # (year, month) of a date
        return _date_answer(field, label, value, source)
    alternatives = entry.major_fallbacks if value == getattr(entry, "major", None) else []
    exact = value == getattr(entry, "school", None)
    if field.options:
        from job_radar.apply.classify import choose_option

        choice = next(
            (c for v in [value, *alternatives] if (c := choose_option(field.options, v, exact))),
            None,
        )
        if choice is None:
            return FieldAnswer(
                field=field,
                category=Category.SUGGESTED,
                value=value,
                source=source,
                note=f"「{value}」不在選項中，請選最接近的",
            )
        return FieldAnswer(field=field, category=Category.AUTO, value=choice, source=source)
    return FieldAnswer(
        field=field,
        category=Category.AUTO,
        value=value,
        source=source,
        alternatives=alternatives,
        exact=exact,
    )


_EMPTY_NOTE = "applicant.yaml 沒有這項資料"
CURRENT_JOB = "<current job>"
DEGREE = "<degree>"


def _part(label: str, entry: Employment | Education) -> str | tuple[int, int] | None:
    """The entry's value for this label: text, (year, month), "" if unknown, CURRENT_JOB for
    the end date of a current job, None if the label is not about this entry."""
    date_kind = None
    if re.search(r"\b(start|from|began|begin)\b", label):
        date_kind = "start"
    elif re.search(r"\b(end|to|until|graduat|completion)", label):
        date_kind = "end"
    if date_kind and re.search(r"date|month|year|\bfrom\b|\bto\b|graduat", label):
        raw = getattr(entry, date_kind)
        if date_kind == "end" and isinstance(entry, Employment) and entry.current:
            return CURRENT_JOB
        parsed = _parse_month(raw)
        return parsed if parsed else ""
    if isinstance(entry, Employment):
        if re.search(r"company|employer|organi[sz]ation", label):
            return entry.company
        if re.search(r"title|position|role", label):
            return entry.title
        if re.search(r"location|city", label):
            return entry.location
        return None
    if re.search(r"school|university|college|institution", label):
        return entry.school
    if re.search(r"degree", label):
        return DEGREE
    if re.search(r"discipline|major|field of study|concentration", label):
        return entry.major
    if re.search(r"\bgpa\b|grade point", label):
        return entry.gpa
    return None


def _parse_month(raw: str) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d{4})-(\d{1,2})", raw or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _degree(raw: str) -> str:
    text = raw.strip().lower()
    for pattern, wording in DEGREES:
        if re.search(pattern, text):
            return wording
    return raw


def month_choice(options: list[str], month: int) -> str | None:
    """Pick the option meaning `month`: "March", "Mar", "03" or "3"."""
    wanted = {month_name[month].lower(), month_abbr[month].lower(), f"{month:02d}", str(month)}
    for option in options:
        if option.strip().lower().rstrip(".") in wanted:
            return option
    return None


def _date_answer(field: FormField, label: str, ym: tuple[int, int], source: str) -> FieldAnswer:
    year, month = ym
    part = "month" if "month" in label else "year" if "year" in label else ""
    if not part and field.options:  # one question split into a month and a year dropdown
        if month_choice(field.options, month) and len(field.options) <= 13:
            part = "month"
        elif all(re.fullmatch(r"\d{4}", o.strip()) for o in field.options if o.strip()):
            part = "year"
    if part == "month":
        if field.options:
            value = month_choice(field.options, month)
            if value is None:
                return FieldAnswer(
                    field=field,
                    category=Category.SUGGESTED,
                    value=month_name[month],
                    source=source,
                    note="選項裡找不到這個月份",
                )
        else:
            value = month_name[month]  # searchable dropdowns filter by the typed name
    elif part == "year":
        value = str(year)
        if field.options and value not in field.options:
            return FieldAnswer(
                field=field,
                category=Category.SUGGESTED,
                value=value,
                source=source,
                note="選項裡找不到這個年份",
            )
    elif field.kind == FieldKind.DATE:
        value = f"{year:04d}-{month:02d}-01"
    elif field.picker:  # its calendar reads only a whole date (Ramp: "05/2027" stays unread)
        value = f"{month:02d}/01/{year}"
    else:
        value = f"{month:02d}/{year}"
    return FieldAnswer(field=field, category=Category.AUTO, value=value, source=source)
