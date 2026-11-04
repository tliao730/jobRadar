"""Job sites (LinkedIn, Jobright, Simplify), matching their postings to ATS jobs, storing them."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from job_radar.radar.models import Platform, Posting, SimplifyConfig, SiteConfig, Sources
from job_radar.radar.resolve import Resolver, company_key, slug_guesses, title_similarity
from job_radar.radar.sites import SITES
from job_radar.radar.sites.base import SearchResult
from job_radar.radar.sites.jobright import SEARCH_URL as JOBRIGHT_URL
from job_radar.radar.sites.linkedin import SEARCH_URL as LINKEDIN_URL
from job_radar.radar.sites.simplify import LISTINGS_URL
from job_radar.radar.store import RadarStore
from tests.conftest import FIXTURES

FIXED_NOW = datetime(2026, 10, 24, tzinfo=UTC)


def sources(**site) -> Sources:
    on = SiteConfig(enabled=True, pages_per_query=2, delay_seconds=(0, 0))
    return Sources(queries=["data scientist", "data analyst"], linkedin=on, jobright=on, **site)


def page(name: str) -> str:
    return (FIXTURES / "radar" / name).read_text()


@pytest.fixture
def no_sleep():
    for site in SITES.values():
        site.sleep = lambda _: None


@respx.mock
def test_linkedin_cards_become_postings_and_empty_pages_end_a_query(no_sleep):
    route = respx.get(LINKEDIN_URL).mock(
        side_effect=[
            httpx.Response(200, text=page("linkedin_search.html")),
            httpx.Response(200, text=""),  # page 2 of "data scientist": nothing more
            httpx.Response(200, text=page("linkedin_search.html")),
            httpx.Response(200, text=""),
        ]
    )
    with httpx.Client() as client:
        result = SITES[Platform.LINKEDIN].search(sources(), client)
    assert route.call_count == 4 and not result.error
    assert len(result.postings) == 10  # the same cards twice are kept once
    first = result.postings[0]
    assert first.id == "linkedin:4481261404" and first.company == "Booz Allen Hamilton"
    assert first.title == "Data Scientist, Senior" and first.location == "San Diego, CA"
    assert first.url == first.apply_url == "https://www.linkedin.com/jobs/view/4481261404"
    assert first.posted_at.date().isoformat() == "2026-10-19"
    params = dict(route.calls[0].request.url.params)
    assert params["keywords"] == "data scientist" and params["f_TPR"] == "r604800"


@respx.mock
def test_a_rate_limit_stops_the_site_but_keeps_what_was_found(no_sleep):
    respx.get(LINKEDIN_URL).mock(
        side_effect=[httpx.Response(200, text=page("linkedin_search.html")), httpx.Response(429)]
    )
    with httpx.Client() as client:
        result = SITES[Platform.LINKEDIN].search(sources(), client)
    assert "429" in result.error and len(result.postings) == 10 and result.requests == 2


@respx.mock
def test_jobright_results_and_throttle_page(no_sleep, monkeypatch):
    monkeypatch.setattr("job_radar.radar.sites.jobright.datetime", _FrozenDatetime)
    respx.get(JOBRIGHT_URL).mock(
        side_effect=[
            httpx.Response(200, text=page("jobright_search.html")),
            httpx.Response(200, text="<html><title>303 See Other</title></html>"),
        ]
    )
    with httpx.Client() as client:
        result = SITES[Platform.JOBRIGHT].search(sources(), client)
    assert [p.title for p in result.postings] == [
        "Data Scientist, New Grad",
        "Staff Data Scientist",
    ]
    grad = result.postings[0]
    assert grad.company == "Example Co" and grad.seniority == "New Grad"
    assert "forecasting models" in grad.description and "Run A/B tests" in grad.description
    assert grad.url == "https://jobright.ai/jobs/info/aaaaaaaaaaaaaaaaaaaaaaa1"
    assert result.postings[1].remote is True
    assert "限流" in result.error  # the second query got the throttle page


@respx.mock
def test_jobright_bot_check_stops_the_site(no_sleep):
    respx.get(JOBRIGHT_URL).mock(
        return_value=httpx.Response(
            303, headers={"location": "/_jr/security/challenge?return=%2Fjobs%2Fsearch"}
        )
    )
    with httpx.Client() as client:
        result = SITES[Platform.JOBRIGHT].search(sources(), client)
    assert "真人驗證" in result.error and not result.postings and result.requests == 1


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


def test_company_and_title_normalization():
    assert company_key("Pinterest, Inc.") == company_key("Pinterest") == "pinterest"
    assert slug_guesses("Red Ventures LLC") == ["redventures", "red-ventures"]
    assert slug_guesses("SpaceX") == ["spacex"]
    assert title_similarity("Data Scientist, New Grad", "Data Scientist - New Grad (2027)") >= 0.6
    assert title_similarity("Data Scientist", "Software Engineer") == 0


def site_posting(n, company, title, platform=Platform.LINKEDIN) -> dict:
    return {"id": f"{platform.value}:{n}", "company": company, "title": title}


@respx.mock
def test_resolver_matches_known_jobs_and_finds_new_boards(tmp_path):
    store = RadarStore(tmp_path)
    ats = [{"id": "greenhouse:1", "company": "Pinterest", "title": "Data Scientist, New Grad"}]
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/v1/boards/redventures/jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 77,
                        "title": "Data Science Analyst, Early Career",
                        "absolute_url": "https://x/77",
                        "location": {"name": "Charlotte, NC"},
                        "content": "",
                    }
                ]
            },
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))
    postings = [
        site_posting(1, "Pinterest, Inc.", "Data Scientist - New Grad"),
        site_posting(2, "Red Ventures", "Data Science Analyst (Early Career)"),
        site_posting(3, "Nowhere Corp", "Data Analyst"),
    ]
    with httpx.Client() as client:
        links, boards = Resolver(store, client).resolve(postings, ats, known=[])
    assert links == {"linkedin:1": "greenhouse:1", "linkedin:2": "greenhouse:77"}
    assert [(b.company.platform, b.company.token) for b in boards] == [
        ("greenhouse", "redventures")
    ]
    assert store.board_lookup("nowhere")["platform"] is None  # cached: not tried again soon
    store.record_run("fetch", [], datetime(2026, 10, 24))
    store.record_run("discover", boards, datetime(2026, 10, 24))
    assert store.last_run()["ok"] == 0  # the daily run, not the boards fetched while matching
    assert [b["token"] for b in store.found_boards()] == ["redventures"]


def test_search_results_are_kept_until_they_go_stale(tmp_path, monkeypatch):
    store = RadarStore(tmp_path)
    t0 = datetime(2026, 10, 20)
    posting = Posting(
        id="linkedin:1",
        platform=Platform.LINKEDIN,
        company="Example Co",
        token="",
        title="Data Scientist",
        url="https://x/1",
        apply_url="https://x/1",
        seniority="Entry Level",
    )
    first = store.record_run("fetch", [], t0, [SearchResult(Platform.LINKEDIN, [posting])])
    assert first.ok == 1 and store.active()[0]["seniority"] == "Entry Level"
    # Missing from the next search (and the search was cut short): still active.
    store.record_run("fetch", [], t0, [SearchResult(Platform.LINKEDIN, [], error="HTTP 429")])
    assert len(store.active()) == 1
    store.link_ats({"linkedin:1": "greenhouse:9"})
    assert store.active()[0]["ats_id"] == "greenhouse:9"
    later = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=15)
    monkeypatch.setattr("job_radar.radar.store.utcnow", lambda: later)
    store.record_run("fetch", [], t0, [SearchResult(Platform.LINKEDIN, [])])
    assert store.active() == []


def linkedin_card(job_id: str, title: str, company: str, location: str) -> str:
    return (
        f'<li><div class="base-card" data-entity-urn="urn:li:jobPosting:{job_id}">'
        f'<h3 class="base-search-card__title">{title}</h3>'
        f'<h4 class="base-search-card__subtitle"><a href="#">{company}</a></h4>'
        f'<span class="job-search-card__location">{location}</span>'
        '<time class="job-search-card__listdate" datetime="2026-10-22">2 days ago</time>'
        "</div></li>"
    )


@respx.mock
def test_fetch_links_site_postings_and_lists_the_rest_as_manual(
    tmp_path, profile_dir, no_sleep, monkeypatch
):
    import json

    import yaml

    from job_radar.config import AppConfig, PathsConfig
    from job_radar.radar.service import RadarService
    from tests.test_radar import ROOT_CONFIG

    monkeypatch.setattr("job_radar.radar.service.REQUEST_GAP_S", 0)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("filters.yaml", "skills.yaml"):
        (config / name).write_text((ROOT_CONFIG / name).read_text())
    (config / "companies.yaml").write_text(
        yaml.safe_dump(
            {"companies": [{"name": "Example Co", "platform": "greenhouse", "token": "exampleco"}]}
        )
    )
    (config / "sources.yaml").write_text(
        yaml.safe_dump(
            {
                "queries": ["data scientist"],
                "days": 7,
                "linkedin": {"enabled": True, "pages_per_query": 1, "delay_seconds": [0, 0]},
                "jobright": {"enabled": False},
            }
        )
    )
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs?content=true").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "radar" / "greenhouse_board.json").read_text())
        )
    )
    respx.get(LINKEDIN_URL).mock(
        return_value=httpx.Response(
            200,
            text=(
                linkedin_card(
                    "11", "Data Scientist - New Grad (2027)", "Example Co", "San Francisco, CA"
                )
                + linkedin_card("12", "Data Analyst, Entry Level", "Workday Only Inc", "Austin, TX")
            ),
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))  # no board found
    cfg = AppConfig(
        root=tmp_path, paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "d"))
    )
    service = RadarService(cfg)
    with httpx.Client() as client:
        stats = service.fetch(client)
    assert stats.ok == 2  # the board and the LinkedIn search

    picked = {m.id: m for m in service.matches() if not m.excluded}
    assert "linkedin:11" not in picked  # shown as the Greenhouse job instead
    assert picked["greenhouse:1001"].also_on == ["linkedin"]
    manual = picked["linkedin:12"]
    assert manual.manual and manual.level == "new_grad"
    assert list(picked)[-1] == "linkedin:12"  # jobs you open yourself come after fillable ones


def test_found_companies_can_be_added_to_the_list(tmp_path, profile_dir):
    from job_radar.config import AppConfig, PathsConfig
    from job_radar.radar.models import load_radar_config
    from job_radar.radar.service import RadarService

    (tmp_path / "config").mkdir()
    shared = "companies:\n  - {name: A, platform: lever, token: a}\n"
    (tmp_path / "config" / "companies.yaml").write_text(shared)
    cfg = AppConfig(
        root=tmp_path, paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "d"))
    )
    service = RadarService(cfg)
    service.store.save_board("red ventures", "Red Ventures", "greenhouse", "redventures")
    service.store.save_board("a", "A", "lever", "a")
    assert [c["token"] for c in service.found_companies()] == ["redventures"]

    service.add_company("Red Ventures", "greenhouse", "redventures")
    service.add_company("Red Ventures", "greenhouse", "redventures")  # once only
    service.add_company("B", "ashby", "b")
    # Added to my own list in profile/; the shared list in git stays as it was.
    assert (tmp_path / "config" / "companies.yaml").read_text() == shared
    assert (profile_dir / "companies.yaml").read_text().startswith("# 我自己要多抓的公司")
    tokens = [c.token for c in load_radar_config(tmp_path / "config", profile_dir).companies]
    assert tokens == ["a", "redventures", "b"]
    assert service.found_companies() == []
    with pytest.raises(ValueError):
        service.add_company("X", "workday", "x")


@respx.mock
def test_a_board_counts_only_when_it_has_the_job(tmp_path):
    """Guessing "applied" for Applied Intuition finds someone's board; without a matching title
    (or with another company's name on it) it is not that company's."""
    store = RadarStore(tmp_path)
    respx.get(url__regex=r".*/boards/appliedintuition/jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 5,
                        "title": "Office Manager",
                        "absolute_url": "https://x/5",
                        "location": {"name": "Remote"},
                        "content": "",
                    }
                ]
            },
        )
    )
    respx.get(url__regex=r".*/boards/newyorklife/jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 6,
                        "title": "Data Scientist, New Grad",
                        "absolute_url": "https://x/6",
                        "company_name": "New Relic",
                        "location": {"name": "Remote"},
                        "content": "",
                    }
                ]
            },
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))
    postings = [
        site_posting(1, "Applied Intuition", "Machine Learning Engineer, New Grad"),
        site_posting(2, "New York Life", "Data Scientist, New Grad"),
    ]
    with httpx.Client() as client:
        links, boards = Resolver(store, client).resolve(postings, [], known=[])
    assert links == {} and boards == []
    assert store.found_boards() == []


NEW_GRAD = LISTINGS_URL.format(repo="SimplifyJobs/New-Grad-Positions")
INTERNSHIPS = LISTINGS_URL.format(repo="SimplifyJobs/Summer2026-Internships")


def listings() -> list[dict]:
    import json

    return json.loads(page("simplify_listings.json"))


@respx.mock
def test_simplify_lists_link_straight_to_the_application_form(no_sleep):
    respx.get(NEW_GRAD).mock(return_value=httpx.Response(200, json=listings()))
    respx.get(INTERNSHIPS).mock(return_value=httpx.Response(200, json=listings()[:1]))
    repos = ["SimplifyJobs/New-Grad-Positions", "SimplifyJobs/Summer2026-Internships"]
    lists = Sources(simplify=SimplifyConfig(enabled=True, delay_seconds=(0, 0), repos=repos))
    with httpx.Client() as client:
        result = SITES[Platform.SIMPLIFY].search(lists, client)
    assert not result.error and result.complete
    # Closed (active: false) and hidden listings are left out; the same listing twice is kept once.
    assert [p.id for p in result.postings] == ["simplify:s-1", "simplify:s-2", "simplify:s-3"]
    first, second = result.postings[:2]
    assert first.company == "Example Co" and first.seniority == "New Grad"
    assert first.apply_url.startswith("https://job-boards.greenhouse.io/exampleco/jobs/1001")
    assert first.posted_at.tzinfo is not None
    assert second.location == "New York, NY; Remote in USA"
    assert "Sponsorship: Does Not Offer Sponsorship" in second.description
    assert "Sponsorship" not in first.description  # "Other" means Simplify does not know


@respx.mock
def test_a_missing_simplify_list_is_reported(no_sleep):
    respx.get(NEW_GRAD).mock(return_value=httpx.Response(404, text="404: Not Found"))
    lists = Sources(simplify=SimplifyConfig(enabled=True, delay_seconds=(0, 0)))
    with httpx.Client() as client:
        result = SITES[Platform.SIMPLIFY].search(lists, client)
    assert result.postings == [] and "HTTP 404" in result.error


@respx.mock
def test_simplify_links_are_matched_by_url_and_never_guessed(
    tmp_path, profile_dir, no_sleep, monkeypatch
):
    import json

    import yaml

    from job_radar.config import AppConfig, PathsConfig
    from job_radar.radar.service import RadarService
    from tests.test_radar import ROOT_CONFIG

    monkeypatch.setattr("job_radar.radar.service.REQUEST_GAP_S", 0)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("filters.yaml", "skills.yaml"):
        (config / name).write_text((ROOT_CONFIG / name).read_text())
    company = {"name": "Example Co", "platform": "greenhouse", "token": "exampleco"}
    (config / "companies.yaml").write_text(yaml.safe_dump({"companies": [company]}))
    # No search keywords: a list site reads everything anyway.
    simplify = {"enabled": True, "delay_seconds": [0, 0]}
    (config / "sources.yaml").write_text(yaml.safe_dump({"queries": [], "simplify": simplify}))
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs?content=true").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "radar" / "greenhouse_board.json").read_text())
        )
    )
    lists = respx.get(NEW_GRAD).mock(return_value=httpx.Response(200, json=listings()))
    guessed = respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))
    cfg = AppConfig(
        root=tmp_path, paths=PathsConfig(profile_dir=str(profile_dir), data_dir=str(tmp_path / "d"))
    )
    service = RadarService(cfg)
    with httpx.Client() as client:
        assert service.fetch(client).ok == 2  # the board and the Simplify list
    assert not guessed.called  # Newboard AI and Bigcorp: no board names were tried

    found = {m.id: m for m in service.matches()}
    assert "simplify:s-1" not in found  # shown as the Greenhouse job it links to
    assert found["greenhouse:1001"].also_on == ["simplify"]
    assert not found["simplify:s-2"].manual  # an Ashby form: fillable as is
    assert "sponsorship" in found["simplify:s-2"].excluded
    assert found["simplify:s-3"].manual  # Workday: open it yourself

    # The list is complete: a listing gone from it is closed on the next fetch.
    lists.mock(return_value=httpx.Response(200, json=listings()[:2]))
    with httpx.Client() as client:
        service.fetch(client)
    active = {j["id"] for j in service.store.active()}
    assert "simplify:s-3" not in active and "simplify:s-2" in active
