---
name: radar-config
description: Change what the job radar fetches and recommends. Use when adding or removing companies, finding a company's ATS board token, or tuning filters, skills and scoring because recommendations look wrong.
---

# Radar configuration

Shared defaults ship with the package in `src/job_radar/defaults/` (`companies.yaml`, `filters.yaml`, `skills.yaml`, `sources.yaml` for LinkedIn / Jobright pacing and Simplify GitHub lists); everyone gets them on update. Each person's own changes go in the same-named files in `profile/` inside their home folder (`uv run job-radar home` prints it; not in git), holding only the keys they change: `radar/models.py` `merge_settings` overrides key by key, replaces lists, merges roles by id and companies by platform + token. The user's extra skills are in `profile/skills.yaml`. Code: `src/job_radar/radar/` (`fetchers/` ATS boards, `sites/` job sites, `resolve.py` matching site postings to ATS jobs).

## Adding a company

1. Find the board token: try `https://boards-api.greenhouse.io/v1/boards/<token>/jobs`, `https://api.lever.co/v0/postings/<token>?mode=json`, `https://api.ashbyhq.com/posting-api/job-board/<token>` with likely tokens (company name, lowercase, no spaces); the careers page's apply links also reveal it (`job-boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`).
2. Add `{name, platform, token}` to `defaults/companies.yaml` when everyone should get it, or to `profile/companies.yaml` when only this person wants it (ask if unclear), and run `uv run job-radar check-companies`. Done when the company reports `ok：N 個職缺`.
3. Companies on Workday, iCIMS or their own sites have no public board API here; tell the user and suggest pasting their URLs into the assistant instead.
4. Boards found from LinkedIn / Jobright company names appear on the radar page ("加入"), which calls `RadarService.add_company`; a found board is trusted only if it lists a job title seen on the site (`resolve._is_theirs`).

## Job sites

LinkedIn and Jobright are searched without logging in; both rate-limit fast (LinkedIn 429 within a few requests, Jobright a "303 See Other" page). Keep `delay_seconds` and the number of queries modest, and never add a logged-in session (hard rule). A site that stops early keeps what it found; check `fetch_results` for `status = 'error'`.

## Tuning recommendations

1. Look before changing: `uv run job-radar radar --limit 40` and `--excluded` show scores and every exclusion reason.
2. Edit the matching YAML rule (regexes, case-insensitive): a fix for everyone in `defaults/filters.yaml`; a personal preference (level, sponsorship, role weights) in `profile/filters.yaml` with only the changed keys. Someone after a different direction sets `only_roles` there: a group (`software`, `data`, `hardware`) or role ids; job-site searches follow the roles in use. When no built-in family fits, add one there (`id`, `name`, `titles`, `queries`); when a family misses titles everyone would want, change `defaults/filters.yaml` (order matters: the first matching family in use wins) and add a case to `test_role_families_cover_software_data_and_hardware`. Evaluations are cached per fetch and settings-file mtime, so a settings edit takes effect on the next listing.
3. For a change to `defaults/`, add a case to `tests/test_radar.py` (`test_hard_filters_explain_exclusions` or the ranking tests) for each rule you change. Done when the new case fails without the change and passes with it, and the full suite is green.

Skill matching only affects ranking; skills listed in `profile/skills.yaml` are the user's own statement and are never written into applications.
