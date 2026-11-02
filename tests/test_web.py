import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from job_radar.apply.service import ApplyService
from job_radar.apply.store import Store
from job_radar.config import AppConfig, PathsConfig
from job_radar.prefill.browser import BrowserManager
from job_radar.web.app import create_app
from tests.conftest import FIXTURES

TOKEN = "test-token"
AUTH = {"X-JR-Token": TOKEN}


@pytest.fixture
def client(tmp_path, profile_dir, fake_llm):
    cfg = AppConfig(
        root=tmp_path,
        paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "data")),
    )
    browser = BrowserManager(tmp_path / "browser-profile", channel=None, headless=True)
    service = ApplyService(cfg, Store(cfg.data_dir), browser, fake_llm, http=httpx.Client())
    with TestClient(create_app(service, token=TOKEN), base_url="http://127.0.0.1") as c:
        yield c


def test_index_embeds_the_session_token(client):
    html = client.get("/").text
    assert f'content="{TOKEN}"' in html


def test_api_requires_the_token(client):
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers={"X-JR-Token": "wrong"}).status_code == 403
    status = client.get("/api/status", headers=AUTH).json()
    assert status["ok"] and status["resumes"] == ["ds"] and status["model"] == "fake-model"


def test_other_hosts_are_rejected(client):
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_add_list_detail_and_status(client):
    job = json.loads((FIXTURES / "api" / "greenhouse_job.json").read_text())
    with respx.mock(assert_all_called=True) as router:
        router.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/123").mock(
            return_value=httpx.Response(200, json=job)
        )
        added = client.post(
            "/api/applications",
            headers=AUTH,
            json={"urls": "see https://job-boards.greenhouse.io/exampleco/jobs/123 and not-a-url"},
        ).json()
    assert added == {"added": ["greenhouse:123"], "errors": []}

    listed = client.get("/api/applications", headers=AUTH).json()
    assert listed[0]["job"]["company"] == "Example Co"
    assert listed[0]["page_open"] is False  # the list can offer to re-open closed tabs
    assert "description_text" not in listed[0]["job"]

    detail = client.get("/api/applications/greenhouse:123", headers=AUTH).json()
    assert detail["application"]["status"] == "queued"
    assert detail["form"] is None and detail["resumes"] == ["ds"]
    assert detail["page_open"] is False  # the steps start at "open the application page"

    updated = client.post(
        "/api/applications/greenhouse:123/status", headers=AUTH, json={"status": "applied"}
    ).json()
    assert updated["status"] == "applied" and updated["applied_at"]


def test_errors_come_back_as_messages(client):
    response = client.post(
        "/api/applications/greenhouse:999/status", headers=AUTH, json={"status": "applied"}
    )
    assert response.status_code == 400
    assert "找不到" in response.json()["detail"]
    assert client.post("/api/applications", headers=AUTH, json={"urls": "nothing here"}).json() == {
        "added": [],
        "errors": ["沒有找到網址"],
    }


def test_panel_page_only_frames_inside_the_extension(client):
    panel = client.get("/panel")
    assert f'content="{TOKEN}"' in panel.text
    assert panel.headers["content-security-policy"] == "frame-ancestors chrome-extension:"
    assert client.get("/").headers["content-security-policy"] == "frame-ancestors 'none'"


def test_health_needs_no_token_but_tab_lookup_does(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/tab", params={"url": "https://x.example/"}).status_code == 403
    found = client.get("/api/tab", params={"url": "https://x.example/"}, headers=AUTH).json()
    assert found == {"job_id": None}
    assert client.post("/api/show", headers=AUTH).status_code == 404


def test_status_reports_whether_drafts_are_on(client):
    assert client.get("/api/status", headers=AUTH).json()["drafts"] is True


def test_radar_lists_recommendations_and_skips_applied_jobs(client, tmp_path):
    from datetime import datetime

    from job_radar.radar.models import Company, Platform, Posting
    from job_radar.radar.store import BoardResult, RadarStore
    from tests.test_radar import ROOT_CONFIG

    assert client.get("/api/radar").status_code == 403
    assert client.get("/api/radar", headers=AUTH).json()["total"] == 0  # no config, no jobs

    config = tmp_path / "config"
    config.mkdir()
    for name in ("filters.yaml", "skills.yaml"):
        (config / name).write_text((ROOT_CONFIG / name).read_text())
    co = Company(name="Example Co", platform=Platform.GREENHOUSE, token="exampleco")
    postings = [
        Posting(
            id=f"greenhouse:{n}",
            platform=co.platform,
            company=co.name,
            token=co.token,
            title=title,
            location="New York, NY",
            url=f"https://x/{n}",
            apply_url=f"https://x/{n}/apply",
            description="Python, SQL",
        )
        for n, title in ((1, "Data Scientist, New Grad"), (2, "Data Analyst I"), (3, "Sales Lead"))
    ]
    RadarStore(tmp_path / "data").record_run("fetch", [BoardResult(co, postings)], datetime.now())

    data = client.get("/api/radar", headers=AUTH).json()
    assert data["total"] == 3 and data["recommended"] == 2
    assert [m["id"] for m in data["items"]] == ["greenhouse:1", "greenhouse:2"]
    assert client.post("/api/radar/dismiss", headers=AUTH, json={"id": "greenhouse:1"}).json()
    data = client.get("/api/radar", headers=AUTH).json()
    assert [m["id"] for m in data["items"]] == ["greenhouse:2"]


def test_prefill_refreshes_questions_from_the_ats(tmp_path, profile_dir, fake_llm):
    from job_radar.apply.intake import parse_job_url

    cfg = AppConfig(
        root=tmp_path,
        paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "data")),
    )
    service = ApplyService(
        cfg,
        Store(cfg.data_dir),
        BrowserManager(tmp_path / "bp", channel=None),
        fake_llm,
        http=httpx.Client(),
    )
    old = parse_job_url("https://job-boards.greenhouse.io/exampleco/jobs/123")
    app, _ = service.store.add(old)  # added before the parser knew demographic questions
    assert app.job.ats_questions == []
    job = json.loads((FIXTURES / "api" / "greenhouse_job.json").read_text())
    with respx.mock() as router:
        router.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/123").mock(
            return_value=httpx.Response(200, json=job)
        )
        refreshed = service._refresh_job(app)
    labels = [q["label"] for q in refreshed.job.ats_questions]
    assert any("veteran" in label for label in labels)
    assert service.get(old.job_id).job.title == "Data Scientist, Ranking"
    service.store.close()


def test_pages_and_scripts_are_never_served_stale(client):
    # The controlled Chrome keeps its cache between runs; without this it kept running an old
    # app.js (the confirm() version of "我已送出") after an update.
    import re

    html = client.get("/").text
    scripts = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert scripts and all(re.search(r"\?v=[0-9a-f]{10}$", s) for s in scripts)
    assert "__JR_VERSION__" not in html and "__JR_VERSION__" not in client.get("/panel").text
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get(scripts[0]).headers["cache-control"] == "no-cache"
