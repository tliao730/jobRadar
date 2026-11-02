"""Turn a pasted job URL into a JobRef, and fetch the JD from public ATS APIs when possible."""

from __future__ import annotations

import hashlib
import html
import logging
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from job_radar.apply.models import JobRef, Source

log = logging.getLogger(__name__)

GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.eu.greenhouse.io",
}
LEVER_HOSTS = {"jobs.lever.co": "api.lever.co", "jobs.eu.lever.co": "api.eu.lever.co"}
USER_AGENT = "job-radar/0.1 (personal job search assistant)"


class IntakeError(ValueError):
    """The URL cannot be used as a job posting."""


def greenhouse_apply_url(host: str, token: str, job_id: str) -> str:
    """The embed page shows the application form itself; the board page often redirects to
    the company's careers site (which may add a bot check and an extra "Apply" click)."""
    region = ".eu" if ".eu." in host else ""
    return f"https://job-boards{region}.greenhouse.io/embed/job_app?for={token}&token={job_id}"


def parse_job_url(url: str) -> JobRef:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IntakeError(f"不是有效的網址：{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if host in GREENHOUSE_HOSTS:
        token = job_id = None
        if parts[:2] == ["embed", "job_app"] and "for" in query and "token" in query:
            token, job_id = query["for"][0], query["token"][0]
        elif len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
            token, job_id = parts[0], parts[2]
        if token and job_id:
            return _job(
                Source.GREENHOUSE, job_id, url, greenhouse_apply_url(host, token, job_id), token
            )
    if "gh_jid" in query and query["gh_jid"][0].isdigit():
        # A company careers page embedding Greenhouse; the board token is unknown.
        return _job(Source.GREENHOUSE, query["gh_jid"][0], url, url)

    if host in LEVER_HOSTS and len(parts) >= 2:
        company, posting_id = parts[0], parts[1]
        return _job(
            Source.LEVER, posting_id, url, f"https://{host}/{company}/{posting_id}/apply", company
        )

    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        org, posting_id = parts[0], parts[1]
        return _job(
            Source.ASHBY,
            posting_id,
            url,
            f"https://jobs.ashbyhq.com/{parts[0]}/{posting_id}/application",
            org,
        )

    if host.endswith("linkedin.com"):
        job_id = (query.get("currentJobId") or [""])[0]
        if not job_id and len(parts) >= 3 and parts[:2] == ["jobs", "view"]:
            m = re.search(r"(\d{6,})$", parts[2])
            job_id = m.group(1) if m else ""
        if job_id:
            return _job(
                Source.LINKEDIN, job_id, url, f"https://www.linkedin.com/jobs/view/{job_id}/"
            )

    if "indeed." in host:
        jk = (query.get("jk") or query.get("vjk") or [""])[0]
        if jk:
            return _job(Source.INDEED, jk, url, f"https://www.indeed.com/viewjob?jk={jk}")

    if "glassdoor." in host:
        listing = (query.get("jl") or query.get("jobListingId") or [""])[0]
        if listing:
            return _job(Source.GLASSDOOR, listing, url, url)

    if host == "jobright.ai" and len(parts) >= 3 and parts[:2] == ["jobs", "info"]:
        return _job(Source.JOBRIGHT, parts[2], url, url)

    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    return _job(Source.OTHER, digest, url, url)


def _job(
    source: Source, source_job_id: str, url: str, apply_url: str, token: str | None = None
) -> JobRef:
    return JobRef(
        job_id=f"{source}:{source_job_id}",
        source=source,
        source_job_id=source_job_id,
        url=url,
        apply_url=apply_url,
        board_token=token,
        company=_pretty(token) if token else "",
    )


def _pretty(token: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", token) if w)


def fetch_job_details(job: JobRef, client: httpx.Client) -> JobRef:
    """Fill title / company / location / JD from the ATS's public API. Best effort."""
    try:
        if job.source == Source.GREENHOUSE and job.board_token:
            return _greenhouse(job, client)
        if job.source == Source.LEVER and job.board_token:
            return _lever(job, client)
        if job.source == Source.ASHBY and job.board_token:
            return _ashby(job, client)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("無法從 %s API 取得職缺內容（%s）：%s", job.source, job.job_id, exc)
    return job


def _get_json(client: httpx.Client, url: str) -> object:
    response = client.get(url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.json()


def _greenhouse(job: JobRef, client: httpx.Client) -> JobRef:
    data = _get_json(
        client,
        f"https://boards-api.greenhouse.io/v1/boards/{job.board_token}/jobs/"
        f"{job.source_job_id}?questions=true",
    )
    raw = [q for key in ("questions", "location_questions") for q in data.get(key) or []]
    raw += [q for group in data.get("compliance") or [] for q in group.get("questions") or []]
    raw += [
        _demographic_question(q)
        for q in (data.get("demographic_questions") or {}).get("questions") or []
    ]
    return job.model_copy(
        update={
            "title": data.get("title") or job.title,
            "company": data.get("company_name") or job.company,
            "location": (data.get("location") or {}).get("name", "") or job.location,
            "description_text": html_to_text(html.unescape(data.get("content") or "")),
            "ats_questions": [_greenhouse_question(q) for q in raw],
        }
    )


def _greenhouse_question(q: dict) -> dict:
    return {
        "label": q.get("label", ""),
        "required": bool(q.get("required")),
        "fields": [
            {
                "name": f.get("name", ""),
                "type": f.get("type", ""),
                "values": [v.get("label", "") for v in f.get("values") or []],
            }
            for f in q.get("fields") or []
        ],
    }


def _demographic_question(q: dict) -> dict:
    """Reshape a demographic question (answer_options, no fields) like a regular one; the
    form's input id is the question id."""
    return {
        "label": q.get("label", ""),
        "required": q.get("required"),
        "fields": [
            {
                "name": str(q.get("id", "")),
                "type": q.get("type", ""),
                "values": q.get("answer_options") or [],
            }
        ],
    }


def _lever(job: JobRef, client: httpx.Client) -> JobRef:
    api_host = LEVER_HOSTS.get(urlparse(job.apply_url).netloc.lower(), "api.lever.co")
    data = _get_json(
        client, f"https://{api_host}/v0/postings/{job.board_token}/{job.source_job_id}?mode=json"
    )
    return job.model_copy(
        update={
            "title": data.get("text") or job.title,
            "location": (data.get("categories") or {}).get("location", "") or job.location,
            "description_text": lever_description(data),
        }
    )


def lever_description(data: dict) -> str:
    """A Lever posting's full JD is split across description, lists[] and additional."""
    sections = [data.get("descriptionPlain") or html_to_text(data.get("description") or "")]
    for item in data.get("lists") or []:
        sections.append(f"{item.get('text', '')}\n{html_to_text(item.get('content') or '')}")
    sections.append(data.get("additionalPlain") or html_to_text(data.get("additional") or ""))
    return "\n\n".join(s.strip() for s in sections if s and s.strip())


def _ashby(job: JobRef, client: httpx.Client) -> JobRef:
    data = _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{job.board_token}")
    for item in data.get("jobs") or []:
        if item.get("id") == job.source_job_id:
            return job.model_copy(
                update={
                    "title": item.get("title") or job.title,
                    "location": item.get("location") or job.location,
                    "description_text": item.get("descriptionPlain")
                    or html_to_text(item.get("descriptionHtml") or ""),
                }
            )
    log.warning("Ashby board %s 裡找不到職缺 %s", job.board_token, job.source_job_id)
    return job


_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "section",
    "article",
    "header",
    "footer",
    "blockquote",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.chunks.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def html_to_text(markup: str) -> str:
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.chunks)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
