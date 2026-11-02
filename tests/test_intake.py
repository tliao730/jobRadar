import json

import httpx
import pytest
import respx

from job_radar.apply.intake import IntakeError, fetch_job_details, html_to_text, parse_job_url
from job_radar.apply.models import Source
from tests.conftest import FIXTURES


@pytest.mark.parametrize(
    ("url", "source", "job_id", "apply_url", "token"),
    [
        (
            "https://job-boards.greenhouse.io/exampleco/jobs/123",
            Source.GREENHOUSE,
            "greenhouse:123",
            "https://job-boards.greenhouse.io/embed/job_app?for=exampleco&token=123",
            "exampleco",
        ),
        (
            "https://boards.greenhouse.io/embed/job_app?for=exampleco&token=456",
            Source.GREENHOUSE,
            "greenhouse:456",
            "https://job-boards.greenhouse.io/embed/job_app?for=exampleco&token=456",
            "exampleco",
        ),
        (
            "https://www.example.com/careers/open-roles?gh_jid=789",
            Source.GREENHOUSE,
            "greenhouse:789",
            "https://www.example.com/careers/open-roles?gh_jid=789",
            None,
        ),
        (
            "https://jobs.lever.co/exampleco/4c1e7a2b-0000-4000-8000-000000000001",
            Source.LEVER,
            "lever:4c1e7a2b-0000-4000-8000-000000000001",
            "https://jobs.lever.co/exampleco/4c1e7a2b-0000-4000-8000-000000000001/apply",
            "exampleco",
        ),
        (
            "https://jobs.ashbyhq.com/exampleco/11111111-1111-4111-8111-111111111111/application",
            Source.ASHBY,
            "ashby:11111111-1111-4111-8111-111111111111",
            "https://jobs.ashbyhq.com/exampleco/11111111-1111-4111-8111-111111111111/application",
            "exampleco",
        ),
        (
            "https://www.linkedin.com/jobs/view/data-scientist-at-example-co-4012345678/",
            Source.LINKEDIN,
            "linkedin:4012345678",
            "https://www.linkedin.com/jobs/view/4012345678/",
            None,
        ),
        (
            "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4099999999",
            Source.LINKEDIN,
            "linkedin:4099999999",
            "https://www.linkedin.com/jobs/view/4099999999/",
            None,
        ),
        (
            "https://www.indeed.com/viewjob?jk=abc123def",
            Source.INDEED,
            "indeed:abc123def",
            "https://www.indeed.com/viewjob?jk=abc123def",
            None,
        ),
        (
            "https://jobright.ai/jobs/info/66f0c0ffee",
            Source.JOBRIGHT,
            "jobright:66f0c0ffee",
            "https://jobright.ai/jobs/info/66f0c0ffee",
            None,
        ),
    ],
)
def test_parse_job_url(url, source, job_id, apply_url, token):
    job = parse_job_url(url)
    assert job.source == source
    assert job.job_id == job_id
    assert job.apply_url == apply_url
    assert job.board_token == token


def test_unknown_site_gets_a_stable_id():
    first = parse_job_url("https://careers.example.org/jobs/ml-engineer")
    again = parse_job_url("https://careers.example.org/jobs/ml-engineer")
    assert first.source == Source.OTHER
    assert first.job_id == again.job_id


@pytest.mark.parametrize("bad", ["not a url", "ftp://example.com/job", "https://"])
def test_rejects_non_http_urls(bad):
    with pytest.raises(IntakeError):
        parse_job_url(bad)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / "api" / name).read_text())


@respx.mock
def test_greenhouse_details_unescape_content_and_keep_questions():
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/123").mock(
        return_value=httpx.Response(200, json=_fixture("greenhouse_job.json"))
    )
    with httpx.Client() as client:
        job = fetch_job_details(
            parse_job_url("https://job-boards.greenhouse.io/exampleco/jobs/123"), client
        )
    assert job.title == "Data Scientist, Ranking"
    assert job.company == "Example Co"
    assert job.location == "San Francisco, CA"
    assert "&lt;" not in job.description_text and "<li>" not in job.description_text
    assert "- Build ranking models" in job.description_text
    assert "What you'll do" in job.description_text
    names = [f["name"] for q in job.ats_questions for f in q["fields"]]
    assert {"question_1003", "gender"} <= set(names)
    sponsorship = next(q for q in job.ats_questions if "sponsorship" in q["label"])
    assert sponsorship["fields"][0]["values"] == ["Yes", "No"]
    # Demographic questions live in their own block; the form's input id is the question id.
    veteran = next(q for q in job.ats_questions if "veteran" in q["label"])
    assert veteran["fields"][0]["name"] == "75904"
    assert veteran["fields"][0]["values"][1] == "No, I am not a veteran or active member"


@respx.mock
def test_lever_details_join_description_lists_and_additional():
    posting_id = "4c1e7a2b-0000-4000-8000-000000000001"
    respx.get(f"https://api.lever.co/v0/postings/exampleco/{posting_id}").mock(
        return_value=httpx.Response(200, json=_fixture("lever_posting.json"))
    )
    with httpx.Client() as client:
        job = fetch_job_details(
            parse_job_url(f"https://jobs.lever.co/exampleco/{posting_id}"), client
        )
    assert job.title == "Machine Learning Engineer"
    assert job.location == "New York, NY"
    text = job.description_text
    assert "Requirements" in text and "Experience with PyTorch" in text
    assert text.rstrip().endswith("We sponsor visas.")


@respx.mock
def test_ashby_details_pick_the_matching_job():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/exampleco").mock(
        return_value=httpx.Response(200, json=_fixture("ashby_board.json"))
    )
    url = "https://jobs.ashbyhq.com/exampleco/22222222-2222-4222-8222-222222222222"
    with httpx.Client() as client:
        job = fetch_job_details(parse_job_url(url), client)
    assert job.title == "AI Engineer"
    assert job.description_text == "Build LLM agents."


@respx.mock
def test_network_failure_keeps_the_job_usable():
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/123").mock(
        side_effect=httpx.ConnectError("offline")
    )
    original = parse_job_url("https://job-boards.greenhouse.io/exampleco/jobs/123")
    with httpx.Client() as client:
        job = fetch_job_details(original, client)
    assert job == original


def test_html_to_text_keeps_structure():
    text = html_to_text(
        "<h2>Role</h2><p>Hello&nbsp;world</p><ul><li>A</li><li>B</li></ul><script>ignore()</script>"
    )
    assert text.splitlines()[0] == "Role"
    assert "Hello world" in text
    assert "- A" in text and "- B" in text
    assert "ignore" not in text
