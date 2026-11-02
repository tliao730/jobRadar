from job_radar.apply.models import (
    AppStatus,
    Category,
    FieldAnswer,
    FieldKind,
    FormField,
    FormState,
    JobRef,
    Source,
)
from job_radar.apply.store import Store


def job(job_id="greenhouse:1", description=""):
    return JobRef(
        job_id=job_id,
        source=Source.GREENHOUSE,
        source_job_id=job_id.split(":")[1],
        url="https://example.com/job",
        apply_url="https://example.com/job",
        company="Example Co",
        title="Data Scientist",
        description_text=description,
    )


def test_add_is_idempotent_and_records_an_event(tmp_path):
    store = Store(tmp_path)
    app, created = store.add(job())
    assert created and app.status == AppStatus.QUEUED
    again, created = store.add(job())
    assert not created and again.job.job_id == app.job.job_id
    assert [e["to"] for e in store.events("greenhouse:1")] == ["queued"]
    store.close()


def test_add_backfills_a_missing_description(tmp_path):
    store = Store(tmp_path)
    store.add(job())
    app, _ = store.add(job(description="Build ranking models"))
    assert app.job.description_text == "Build ranking models"
    assert (store.folder("greenhouse:1") / "jd.md").read_text().endswith("Build ranking models")
    store.close()


def test_status_changes_and_applied_at(tmp_path):
    store = Store(tmp_path)
    store.add(job())
    store.set_status("greenhouse:1", AppStatus.PREFILLED)
    applied = store.set_status("greenhouse:1", AppStatus.APPLIED, "submitted on site")
    assert applied.applied_at is not None
    later = store.set_status("greenhouse:1", AppStatus.INTERVIEWING)
    assert later.applied_at == applied.applied_at
    events = store.events("greenhouse:1")
    assert [e["to"] for e in events] == ["queued", "prefilled", "applied", "interviewing"]
    assert events[2]["note"] == "submitted on site"
    store.close()


def test_costs_accumulate(tmp_path):
    store = Store(tmp_path)
    store.add(job())
    store.add_cost("greenhouse:1", 0.01)
    store.add_cost("greenhouse:1", 0.02)
    assert abs(store.get("greenhouse:1").llm_cost_usd - 0.03) < 1e-9
    store.close()


def test_form_state_round_trip(tmp_path):
    store = Store(tmp_path)
    store.add(job())
    field = FormField(field_id="f0-1", kind=FieldKind.TEXTAREA, label="Why us?")
    state = FormState(
        job_id="greenhouse:1",
        answers=[
            FieldAnswer(field=field, category=Category.THOUGHT, value="Because", source="llm")
        ],
    )
    store.save_form(state)
    loaded = store.load_form("greenhouse:1")
    assert loaded.answers[0].value == "Because"
    assert store.load_form("greenhouse:2") is None
    store.close()


def test_reopening_does_not_rerun_migrations(tmp_path):
    Store(tmp_path).close()
    store = Store(tmp_path)
    store.add(job())
    assert len(store.list()) == 1
    store.close()
