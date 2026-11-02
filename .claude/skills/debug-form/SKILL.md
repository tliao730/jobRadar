---
name: debug-form
description: Debug the application assistant on a real job form. Use when a site's fields are filled wrongly or not at all (dropdowns failing, wrong answer, missing field, wrong section label), or before trusting a new ATS.
---

# Debug a form fill

Work toward a **red** loop: one command that reproduces the user's exact symptom on the real page. Nothing is ever submitted; every page action goes through `SafePage`.

1. **Collect the evidence.** The user's last scan is `data/applications/<job>/form.json` (each answer's `category`, `filled`, `error`, `field.section`). Note the exact error text; that is the symptom the loop must show.
2. **Reproduce in isolation.** `uv run job-radar inspect "<url>" --fill` (temporary Chrome profile; add `--headed` to watch). Done when the table shows the same failure as form.json, or shows it passing.
3. **If isolation is green, reproduce the user's conditions.** Drive the running assistant through its API with the token from `data/ui-session.json`: `POST /api/applications/<id>/open`, then `/prefill`. A freshly launched assistant (Dock) has a cold cache and loads pages slower; repeat 3–5 runs to get a reproduction rate. Done when one scripted command goes red reliably.
4. **Instrument, then fix.** Tag temporary logs `[DEBUG-xxxx]`, capture `pageerror`/console errors, and check the known causes below first. Turn the pattern into a fixture in `tests/fixtures/forms/` plus a failing test, watch it fail, fix, watch it pass, then re-run the step 3 loop. Remove every `[DEBUG-` line.
5. Finish with `uv run ruff check . && uv run ruff format . && uv run pytest` and record the root cause in CLAUDE.md if it changes behaviour.

## Known causes

- **Hydration**: typing into a server-rendered React form before it hydrates crashes the app (React #426/#345); dropdowns then never open while text fields look filled. `scanner.wait_until_interactive` (`prefill/hydration.js`) guards this; a dropdown input without `__reactProps$` keys means the page never hydrated. On a cold cache React may not have marked its root yet, so framework markers (`__remixContext`, `__NEXT_DATA__`…) also count as "React page, wait" — a new framework needs its marker added there.
- **Late forms**: client-rendered pages (Ashby) draw the form seconds after load, 20 s+ on a cold cache with several tabs loading; `wait_until_interactive` first waits for any visible control (`FORM_WAIT_MS`). "No form fields found" on a page that visibly has a form means it gave up too early.
- **Wording**: an answer whose meaning matches but wording differs from the options goes through `choose_option`'s same-meaning fallback; Greenhouse demographic options come from the API's `demographic_questions`.
- **Closed tab**: "Target page … has been closed" means the tab disappeared mid-fill (the user closed it, or the site replaced it); the filler reports it as `PAGE_CLOSED`.
- **Options**: Greenhouse dropdowns list options only when opened; custom questions get them from the board API (`enrich_options`), standard ones (school, degree, months) are searched by typing. `SafePage.choose_combobox` retries shorter queries but only accepts an option matching the full value.
- **Sections**: `extract_fields.js` `sectionOf` gives each field its form part; `apply/history.py` uses section, id suffix (`-0`, `--0`) and label to fill employment/education from applicant.yaml.
- **Covered fields**: a popup left open (react-datepicker's calendar) sits over nearby fields, so a forced click lands on it: "Clicking the checkbox did not change its state". Screenshot after the automatic pass and look for visible popups; date pickers are committed by clicking their selected day (`prefill/datepicker.js`).
- **Multi-line options**: Ashby's school options read "Name\nCountry\ndomain"; matching uses the first line.
- **Click timeouts**: the full Playwright call log (which element intercepted the click) is in `data/logs/ui.log` ("填寫「…」失敗").
- **Labels**: an unlabeled control borrows the previous control's label when they share a small group (month + year selects).
