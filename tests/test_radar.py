import json
import threading
from datetime import UTC, datetime

import httpx
import pytest
import respx
import yaml

from job_radar.config import AppConfig, PathsConfig
from job_radar.radar.fetchers import FETCHERS, FetchError, TokenNotFound
from job_radar.radar.fetchers import base as fetch_base
from job_radar.radar.match import Matcher, min_years
from job_radar.radar.models import Company, Platform, Posting, load_radar_config
from job_radar.radar.service import RadarService
from job_radar.radar.store import BoardResult, RadarStore
from tests.conftest import FIXTURES

ROOT_CONFIG = FIXTURES.parents[1] / "config"
GH = Company(name="Example Co", platform=Platform.GREENHOUSE, token="exampleco")
LV = Company(name="Lever Co", platform=Platform.LEVER, token="leverco")
AB = Company(name="Ashby Co", platform=Platform.ASHBY, token="ashbyco")


def board(name):
    return json.loads((FIXTURES / "radar" / name).read_text())


def mock_boards(router):
    router.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs?content=true").mock(
        return_value=httpx.Response(200, json=board("greenhouse_board.json"))
    )
    router.get("https://api.lever.co/v0/postings/leverco?mode=json").mock(
        return_value=httpx.Response(200, json=board("lever_board.json"))
    )
    router.get(
        "https://api.ashbyhq.com/posting-api/job-board/ashbyco?includeCompensation=true"
    ).mock(return_value=httpx.Response(200, json=board("ashby_board.json")))


@respx.mock
def test_each_platform_is_normalized():
    mock_boards(respx)
    with httpx.Client() as client:
        gh = FETCHERS[Platform.GREENHOUSE].fetch(GH, client)
        lv = FETCHERS[Platform.LEVER].fetch(LV, client)
        ab = FETCHERS[Platform.ASHBY].fetch(AB, client)
    assert gh[0].id == "greenhouse:1001"
    assert (
        gh[0].apply_url == "https://job-boards.greenhouse.io/embed/job_app?for=exampleco&token=1001"
    )
    assert gh[0].description == "Use Python, SQL and statistics to run A/B tests."
    assert gh[0].posted_at.isoformat() == "2026-10-01T12:00:00-04:00"
    assert gh[1].posted_at is None  # updated_at is not a publish date
    assert lv[0].apply_url.endswith("/apply") and lv[0].remote is True
    assert (
        "Time series forecasting" in lv[0].description and "unable to sponsor" in lv[0].description
    )
    assert [p.id for p in ab] == ["ashby:bbbb-2222"]  # unlisted jobs are skipped


@respx.mock
def test_missing_board_and_retries(monkeypatch):
    monkeypatch.setattr(fetch_base.time, "sleep", lambda _: None)
    respx.get("https://api.lever.co/v0/postings/gone?mode=json").mock(
        return_value=httpx.Response(404)
    )
    flaky = respx.get("https://api.lever.co/v0/postings/flaky?mode=json").mock(
        side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json=[])]
    )
    down = respx.get("https://api.lever.co/v0/postings/down?mode=json").mock(
        return_value=httpx.Response(500)
    )
    fetcher = FETCHERS[Platform.LEVER]
    with httpx.Client() as client:
        with pytest.raises(TokenNotFound):
            fetcher.fetch(LV.model_copy(update={"token": "gone"}), client)
        assert fetcher.fetch(LV.model_copy(update={"token": "flaky"}), client) == []
        assert flaky.call_count == 3
        with pytest.raises(FetchError, match="HTTP 500"):
            fetcher.fetch(LV.model_copy(update={"token": "down"}), client)
        assert down.call_count == fetch_base.RETRIES + 1


def posting(n: int, title="Data Scientist", company=GH) -> Posting:
    return Posting(
        id=f"greenhouse:{n}",
        platform=company.platform,
        company=company.name,
        token=company.token,
        title=title,
        url=f"https://x/{n}",
        apply_url=f"https://x/{n}/apply",
        description=f"JD {n}",
    )


def test_store_tracks_new_changed_closed_and_suspect_boards(tmp_path):
    store = RadarStore(tmp_path)
    t0 = datetime(2026, 10, 20)
    first = store.record_run("fetch", [BoardResult(GH, [posting(i) for i in range(6)])], t0)
    assert first.new == 0 and first.ok == 1  # the first fetch of a board is baseline
    assert all(j["is_baseline"] for j in store.active())

    changed = posting(1).model_copy(update={"description": "JD 1, revised"})
    second = store.record_run("fetch", [BoardResult(GH, [posting(0), changed, posting(7)])], t0)
    assert (second.new, second.updated, second.closed) == (1, 1, 4)
    active = {j["id"]: j for j in store.active()}
    assert set(active) == {"greenhouse:0", "greenhouse:1", "greenhouse:7"}
    assert not active["greenhouse:7"]["is_baseline"]

    # A failed board closes nothing; an empty board after ≥ 5 jobs is suspect, not a purge.
    third = store.record_run("fetch", [BoardResult(GH, [posting(i) for i in range(6)])], t0)
    assert (third.reopened, third.closed) == (4, 1)
    failed = store.record_run("fetch", [BoardResult(GH, error="HTTP 500")], t0)
    suspect = store.record_run("fetch", [BoardResult(GH, [])], t0)
    assert failed.failed and suspect.suspect == ["Example Co"]
    assert len(store.active()) == 6
    assert store.last_run()["suspect"] == ["Example Co"]

    store.dismiss("greenhouse:0")
    store.dismiss("greenhouse:0")
    assert store.dismissed() == {"greenhouse:0"}


def test_personal_settings_change_only_what_they_name(tmp_path):
    # A friend's profile/ holds their own level, sponsorship, roles and queries; the shared
    # config/ in git stays untouched, so `git pull` never conflicts.
    config, mine = tmp_path / "config", tmp_path / "profile"
    config.mkdir()
    mine.mkdir()
    for name in ("filters.yaml", "skills.yaml", "sources.yaml"):
        (config / name).write_text((ROOT_CONFIG / name).read_text())
    (config / "companies.yaml").write_text(
        "companies:\n  - {name: A, platform: lever, token: a}\n"
        "  - {name: B, platform: ashby, token: b}\n"
    )
    (mine / "companies.yaml").write_text(
        "companies:\n  - {platform: ashby, token: b, enabled: false}\n"
        "  - {name: C, platform: greenhouse, token: c}\n"
    )
    (mine / "filters.yaml").write_text(
        "sponsorship: {exclude_no_sponsorship: false}\n"
        "levels: {want: [intern, new_grad]}\n"
        "roles:\n  - {id: da, enabled: false}\n  - {id: quant, titles: ['\\bquant\\b']}\n"
    )
    (mine / "sources.yaml").write_text("queries: [software engineer]\n")

    shared = load_radar_config(config)
    radar = load_radar_config(config, mine)
    assert [(c.token, c.enabled) for c in radar.companies] == [
        ("a", True),
        ("b", False),
        ("c", True),
    ]
    assert not radar.filters.sponsorship.exclude_no_sponsorship
    assert radar.filters.sponsorship.no_sponsorship == shared.filters.sponsorship.no_sponsorship
    assert radar.filters.levels.want == ["intern", "new_grad"]
    assert radar.filters.levels.max_years == shared.filters.levels.max_years
    roles = {r.id: r for r in radar.filters.roles}
    assert not roles["da"].enabled
    assert roles["da"].titles == next(r for r in shared.filters.roles if r.id == "da").titles
    assert list(roles) == [r.id for r in shared.filters.roles] + ["quant"]
    assert radar.sources.queries == ["software engineer"]
    assert radar.sources.linkedin == shared.sources.linkedin
    assert radar.skills == shared.skills


def test_init_profile_templates_change_nothing_until_edited(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from job_radar.cli import app

    monkeypatch.setenv("JOB_RADAR_ROOT", str(tmp_path))
    result = CliRunner().invoke(app, ["init-profile"])
    assert result.exit_code == 0, result.output
    profile = tmp_path / "profile"
    assert {"filters.yaml", "sources.yaml", "companies.yaml"} <= {p.name for p in profile.iterdir()}
    assert load_radar_config(ROOT_CONFIG, profile) == load_radar_config(ROOT_CONFIG)


@pytest.fixture
def matcher():
    radar = load_radar_config(ROOT_CONFIG)
    return Matcher(radar.filters, radar.skills, {"Python", "SQL", "Statistics", "A/B testing"})


def job(title, location="San Francisco, CA", description="Python and SQL.", **extra):
    return {
        "id": "greenhouse:1",
        "company": "Example Co",
        "title": title,
        "location": location,
        "url": "u",
        "apply_url": "a",
        "platform": "greenhouse",
        "description": description,
        **extra,
    }


def directed(**update) -> Matcher:
    radar = load_radar_config(ROOT_CONFIG)
    return Matcher(radar.filters.model_copy(update=update), radar.skills, set())


@pytest.mark.parametrize(
    ("title", "role"),
    [
        ("Machine Learning Engineer, New Grad", "mle"),
        ("Data Scientist, New Grad", "ds"),
        ("Data Engineer", "de"),
        ("Business Intelligence Analyst", "da"),
        ("Business Analyst, New Grad", "ba"),
        ("Software Engineer, New Grad", "swe"),
        ("Frontend Engineer", "swe"),
        ("Software Development Engineer I", "swe"),
        ("Software Engineer, Infrastructure", "swe"),  # swe is listed before infra
        ("Software Engineer, Hardware Platform", "swe"),  # and before electrical
        ("Site Reliability Engineer", "infra"),
        ("Embedded Software Engineer, New Grad", "embedded"),  # embedded is before swe
        ("Firmware Engineer", "embedded"),
        ("ASIC Design Engineer, New Grad", "digital"),
        ("Design Verification Engineer", "digital"),
        ("Post-Silicon Validation Engineer", "digital"),
        ("Analog Mixed-Signal Engineer", "analog"),
        ("RF Engineer", "analog"),
        ("Electrical Engineer New Grad", "electrical"),
        ("Hardware Test Engineer", "electrical"),
        ("Software Test Engineer", ""),
        ("Software Verification Engineer", ""),
        ("Digital Product Designer", ""),
        ("Applied AI New Grad - Non Silicon", ""),
    ],
)
def test_role_families_cover_software_data_and_hardware(matcher, title, role):
    # The shared defaults look at every family; the first one that matches wins.
    assert matcher.evaluate(job(title)).role == role


def test_only_roles_names_families_or_whole_groups():
    asic = job("ASIC Design Engineer, New Grad", description="RTL in SystemVerilog, FPGA, UVM.")
    firmware = job("Embedded Software Engineer, New Grad", description="Embedded C, RTOS.")
    software = job("Software Engineer, New Grad")

    hardware = directed(only_roles=["hardware"])
    assert hardware.evaluate(asic).role == "digital" and not hardware.evaluate(asic).excluded
    assert hardware.evaluate(firmware).role == "embedded"
    assert hardware.evaluate(software).excluded == "不是目標職務類別"
    # Without embedded among the families in use, embedded software is SWE.
    mine = directed(only_roles=["ds", "swe"])
    assert mine.evaluate(firmware).role == "swe"
    assert mine.evaluate(asic).excluded == "不是目標職務類別"


def test_a_family_switched_off_stays_off_inside_its_group():
    radar = load_radar_config(ROOT_CONFIG)
    roles = [r.model_copy(update={"enabled": r.id != "analog"}) for r in radar.filters.roles]
    no_analog = Matcher(
        radar.filters.model_copy(update={"roles": roles, "only_roles": ["hardware"]}),
        radar.skills,
        set(),
    )
    assert no_analog.evaluate(job("Analog Design Engineer")).excluded == "不是目標職務類別"
    assert no_analog.evaluate(job("FPGA Engineer")).role == "digital"


def test_job_sites_are_searched_for_the_families_in_use():
    from job_radar.radar.service import search_queries

    radar = load_radar_config(ROOT_CONFIG)
    data = radar.model_copy(
        update={"filters": radar.filters.model_copy(update={"only_roles": ["data"]})}
    )
    # Every family's first query before any second one: a rate limit midway still covers all.
    assert search_queries(data) == [
        "data scientist new grad",
        "data analyst new grad",
        "business analyst new grad",
        "data scientist",
        "data analyst",
        "business analyst",
    ]
    mine = data.model_copy(update={"sources": data.sources.model_copy(update={"queries": ["x"]})})
    assert search_queries(mine) == ["x"]  # queries in sources.yaml win


@pytest.mark.parametrize(
    ("title", "location", "description", "reason"),
    [
        ("Senior Data Scientist", "New York, NY", "", "層級"),
        ("Senior Data Scientist I", "New York, NY", "", "層級"),
        ("Account Executive", "New York, NY", "", "職稱"),
        ("Product Designer", "New York, NY", "", "職務類別"),
        ("PhD Data Scientist, New Grad", "New York, NY", "", "職稱"),
        ("Data Scientist, New Grad", "London, UK", "", "地點"),
        ("Data Scientist, New Grad", "Remote - Canada", "", "地點"),
        ("Data Scientist, New Grad", "Paris, France", "", "地點"),
        ("ML Engineer, New Grad", "Remote - US", "We are unable to sponsor visas.", "sponsorship"),
        (
            "Electrical Engineer New Grad",
            "Hawthorne, CA",
            "To conform to U.S. Government export regulations, applicant must be a (i) U.S. "
            "citizen or national, (ii) U.S. lawful, permanent resident",
            "sponsorship",
        ),
        ("FPGA Engineer", "Costa Mesa, CA", "Must be a U.S. person under ITAR.", "sponsorship"),
        ("Data Scientist, New Grad", "Stuttgart, DE", "", "地點"),
    ],
)
def test_hard_filters_explain_exclusions(matcher, title, location, description, reason):
    assert reason in matcher.evaluate(job(title, location, description)).excluded


def test_every_us_state_counts_and_export_boilerplate_does_not_exclude(matcher):
    boilerplate = (
        "This position may require access to information protected under U.S. export control laws."
    )
    us = ["Huntsville, AL", "Boise, ID", "Indianapolis, IN", "Wilmington, DE", "New London, CT"]
    for place in [*us, "Albuquerque, New Mexico", "Dublin, CA"]:
        assert not matcher.evaluate(job("Electrical Engineer New Grad", place)).excluded, place
    assert not matcher.evaluate(job("Data Scientist, New Grad", description=boilerplate)).excluded


def test_wanted_levels_rank_above_unstated_ones(matcher):
    grad = matcher.evaluate(job("Data Scientist, New Grad", "San Francisco, CA; London"))
    ms_phd = matcher.evaluate(job("MS/PhD Data Scientist, University Grad"))
    plain = matcher.evaluate(job("Data Scientist"))
    assert not grad.excluded and not ms_phd.excluded and not plain.excluded
    assert grad.level == "new_grad" and grad.role == "ds"
    assert grad.score > plain.score
    assert grad.matched_skills == ["Python", "SQL"]


def test_internships_only_when_co_op(matcher):
    # Graduating in May 2027: a summer internship no longer fits, a co-op still can.
    summer = matcher.evaluate(job("Data Science Intern (Summer 2027)"))
    co_op = matcher.evaluate(job("Data Science Co-op, Spring 2027"))
    fall = matcher.evaluate(job("Machine Learning Intern - Fall 2026"))
    jd_co_op = matcher.evaluate(job("ML Intern", description="This is a 6-month co-op."))
    # A season in the JD is often about school ("returning to school in fall 2027").
    school = matcher.evaluate(
        job("ML Research Intern (Summer 2027)", description="Return to school in Fall 2027.")
    )
    assert "co-op" in summer.excluded and "co-op" in school.excluded
    assert not co_op.excluded and not fall.excluded and not jd_co_op.excluded
    assert co_op.level == "intern"


def test_site_seniority_labels_set_or_exclude_the_level(matcher):
    entry = matcher.evaluate(job("Data Scientist", seniority="Entry Level"))
    senior = matcher.evaluate(job("Data Scientist", seniority="Senior Level"))
    assert entry.level == "new_grad" and not entry.excluded
    assert senior.excluded == "層級：Senior Level"


@pytest.mark.parametrize(
    ("text", "years"),
    [
        ("3+ years of experience in machine learning", 3),
        ("1-3 years of relevant experience, or 5+ years of industry experience", 1),
        ("Minimum 2 yrs of hands-on experience", 2),
        ("We have 30 years of history.", None),
        ("", None),
    ],
)
def test_min_years(text, years):
    assert min_years(text) == years


def test_jobs_asking_for_years_of_experience_are_excluded(matcher):
    m = matcher.evaluate(job("Data Scientist", description="5+ years of experience with SQL."))
    assert m.excluded == "要求 5 年以上經驗"


def test_new_means_first_seen_in_the_last_few_days(matcher):
    now = datetime(2026, 11, 1, 12)
    fresh = job("Data Scientist, New Grad", first_seen_at=datetime(2026, 10, 30, 9))
    old = job("Data Scientist, New Grad", first_seen_at=datetime(2026, 10, 20, 9))
    baseline = job("Data Scientist, New Grad", first_seen_at=now, is_baseline=True)
    assert matcher.evaluate(fresh, now).is_new
    assert not matcher.evaluate(old, now).is_new  # a re-fetch must not keep calling it new
    assert not matcher.evaluate(baseline, now).is_new  # a board's first fetch never counts


def test_old_postings_are_not_recommended(matcher):
    old = matcher.evaluate(
        job("Data Scientist, New Grad", posted_at=datetime(2026, 1, 1)), now=datetime(2026, 10, 23)
    )
    assert "發布超過" in old.excluded


@respx.mock
def test_service_fetches_ranks_and_merges_locations(tmp_path, profile_dir, monkeypatch):
    monkeypatch.setattr("job_radar.radar.service.REQUEST_GAP_S", 0)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("filters.yaml", "skills.yaml"):
        (config / name).write_text((ROOT_CONFIG / name).read_text())
    companies = [c.model_dump(mode="json") for c in (GH, LV, AB)]
    companies.append({"name": "Gone", "platform": "lever", "token": "gone"})
    (config / "companies.yaml").write_text(yaml.safe_dump({"companies": companies}))
    mock_boards(respx)
    respx.get("https://api.lever.co/v0/postings/gone?mode=json").mock(
        return_value=httpx.Response(404)
    )
    cfg = AppConfig(
        root=tmp_path, paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "d"))
    )
    service = RadarService(cfg)
    assert service.stale()  # never fetched: opening the assistant should fetch
    with httpx.Client() as client:
        stats = service.fetch(client)
    assert not service.stale()
    assert stats.ok == 3 and len(stats.failed) == 1 and "404" in stats.failed[0]

    matches = service.matches()
    picked = [m for m in matches if not m.excluded]
    assert [m.id for m in picked] == ["greenhouse:1001", "ashby:bbbb-2222"]
    assert "sponsorship" in next(m for m in matches if m.id == "lever:aaaa-1111").excluded
    assert service.matches(skip_ids={"greenhouse:1001"})[0].id == "ashby:bbbb-2222"
    service.store.dismiss("ashby:bbbb-2222")
    assert "ashby:bbbb-2222" not in {m.id for m in service.matches()}

    # Remembering an answer touches profile/answers_learned.yaml; the ranking stays cached.
    evaluated = []
    monkeypatch.setattr(service, "_evaluate_all", lambda: evaluated.append(1) or [])
    (profile_dir / "answers_learned.yaml").write_text("answers: []\n")
    service.matches()
    assert not evaluated
    highlights = profile_dir / "highlights.yaml"
    highlights.write_text(highlights.read_text() + "\n")
    service.matches()
    assert evaluated  # what my skills come from did change
    evaluated.clear()
    (profile_dir / "filters.yaml").write_text("levels: {want: [intern]}\n")
    service.matches()
    assert evaluated  # so did my own filters


def test_threads_of_one_process_take_turns_with_the_database(tmp_path):
    # DuckDB failed once with "already attached" when a fetch thread opened jobs.duckdb while
    # another thread's connection was closing (data/logs/ui.log, 10/25); connections in one
    # process now take turns.
    store = RadarStore(tmp_path)
    order = []

    def other():
        with store._connect():
            order.append("other")

    with store._connect():
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(0.3)
        order.append("first")
    thread.join()
    assert order == ["first", "other"]


def test_the_daily_fetch_is_due_once_its_time_has_passed(tmp_path, monkeypatch):
    service = RadarService(AppConfig(root=tmp_path, paths=PathsConfig(data_dir=str(tmp_path))))

    def fetched_at(local: datetime) -> None:
        finished = local.astimezone(UTC).replace(tzinfo=None)  # runs are stored in UTC
        monkeypatch.setattr(service.store, "last_run", lambda: {"finished_at": finished})

    morning, early = datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 7, 0)
    # 11/02: a manual fetch the afternoon before used to make 08:30 skip ("not 20 hours yet").
    fetched_at(datetime(2026, 11, 1, 13, 57))
    assert service.stale((8, 30), morning)
    assert not service.stale((8, 30), early)  # before 08:30, yesterday's slot is the latest
    fetched_at(datetime(2026, 11, 2, 8, 31))
    assert not service.stale((8, 30), morning)
    fetched_at(datetime(2026, 11, 1, 8, 0))
    assert service.stale((8, 30), early)  # yesterday's 08:30 was missed too
