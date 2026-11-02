"""Ask Claude for suggested values and drafts for the fields the deterministic pass left over."""

from __future__ import annotations

import logging
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel

from job_radar.apply.classify import choose_option
from job_radar.apply.models import Category, FieldAnswer, FieldKind, FormField, JobRef
from job_radar.llm import LLMUsage, StructuredLLM

log = logging.getLogger(__name__)

PROMPT_VERSION = "draft_answers_v1"


class FieldDraft(BaseModel):
    field_id: str
    category: Literal["suggested", "thought", "user"]
    answer: str
    answers: list[str]
    note: str
    facts_used: list[str]


class DraftResult(BaseModel):
    drafts: list[FieldDraft]


_CATEGORY = {"suggested": Category.SUGGESTED, "thought": Category.THOUGHT, "user": Category.USER}


def system_prompt() -> str:
    return resources.files("job_radar.prompts").joinpath(f"{PROMPT_VERSION}.md").read_text("utf-8")


def build_user_message(
    job: JobRef, fields: list[FormField], facts: str, max_jd_chars: int
) -> tuple[str, bool]:
    """Returns (message, jd_truncated)."""
    jd = job.description_text or "(job description not available)"
    truncated = len(jd) > max_jd_chars
    if truncated:
        jd = jd[:max_jd_chars]
    listed = [
        {
            k: v
            for k, v in {
                "field_id": f.field_id,
                "section": f.section or None,
                "question": f.label,
                "type": f.kind.value,
                "required": f.required,
                "max_length": f.max_length,
                "options": f.options or None,
                "current_value": f.value or None,
            }.items()
            if v is not None
        }
        for f in fields
    ]
    message = (
        "<job_posting>\n"
        f"Company: {job.company}\nTitle: {job.title}\nLocation: {job.location}\n\n{jd}\n"
        "</job_posting>\n\n"
        f"<applicant_facts>\n{facts}\n</applicant_facts>\n\n"
        "<form_fields>\n"
        f"{yaml.safe_dump(listed, allow_unicode=True, sort_keys=False)}"
        "</form_fields>"
    )
    return message, truncated


def draft_answers(
    llm: StructuredLLM, job: JobRef, fields: list[FormField], facts: str, max_jd_chars: int
) -> tuple[list[FieldAnswer], LLMUsage, bool]:
    """Raises LLMError on failure. Returns (answers, usage, jd_truncated)."""
    message, truncated = build_user_message(job, fields, facts, max_jd_chars)
    if truncated:
        log.info("JD 超過 %d 字元，只送出前段", max_jd_chars)
    result, usage = llm.parse(system=system_prompt(), user=message, output_model=DraftResult)
    return merge_drafts(fields, result), usage, truncated


def merge_drafts(fields: list[FormField], result: DraftResult) -> list[FieldAnswer]:
    by_id = {d.field_id: d for d in result.drafts}
    answers = []
    for field in fields:
        draft = by_id.get(field.field_id)
        if draft is None:
            answers.append(
                FieldAnswer(
                    field=field,
                    category=Category.THOUGHT,
                    source="llm",
                    note="模型沒有回覆這一題，請自行填寫",
                )
            )
            continue
        answers.append(_to_answer(field, draft))
    unknown = set(by_id) - {f.field_id for f in fields}
    if unknown:
        log.warning("模型回覆了不存在的欄位，已忽略：%s", sorted(unknown))
    return answers


def _to_answer(field: FormField, draft: FieldDraft) -> FieldAnswer:
    category = _CATEGORY[draft.category]
    note = draft.note
    value: str | list[str] = draft.answer

    if category == Category.USER:
        value = ""
    elif field.kind == FieldKind.CHECKBOXES:
        picked = [
            c
            for a in (draft.answers or [draft.answer])
            if a and (c := choose_option(field.options, a))
        ]
        if len(picked) < len([a for a in draft.answers if a]):
            category, note = Category.THOUGHT, _join(note, "部分建議不在選項中，請自行勾選")
        value = picked
    elif field.options and field.kind in (FieldKind.SELECT, FieldKind.RADIO, FieldKind.COMBOBOX):
        choice = choose_option(field.options, draft.answer)
        if choice is None and draft.answer:
            category = Category.THOUGHT
            note = _join(note, f"建議的「{draft.answer}」不在選項中，請自行選擇")
        value = choice or ""

    if isinstance(value, str) and field.max_length and len(value) > field.max_length:
        note = _join(note, f"草稿 {len(value)} 字元，超過上限 {field.max_length}，請刪減")

    return FieldAnswer(
        field=field,
        category=category,
        value=value,
        source="llm",
        note=note,
        facts_used=draft.facts_used,
    )


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)
