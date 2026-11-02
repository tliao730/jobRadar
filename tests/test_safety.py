"""Static guarantees: nothing outside SafePage can click, press keys, or submit a form."""

import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "job_radar"

FORBIDDEN_PY = re.compile(
    r"\.click\(|\.dblclick\(|\.tap\(|\.press\(|press_sequentially|keyboard\.|mouse\."
    r"|\.submit\(|requestSubmit|dispatch_event"
)
FORBIDDEN_JS = re.compile(r"\.click\(|\.submit\(\)|requestSubmit\(|dispatchEvent\(")


def test_python_code_never_clicks_or_submits_outside_safe_page():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "safe_page.py":
            continue
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if FORBIDDEN_PY.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_safe_page_clicks_in_exactly_one_checked_place():
    source = (SRC / "prefill" / "safe_page.py").read_text("utf-8")
    assert len(re.findall(r"\.click\(", source)) == 1
    click_line = next(line for line in source.splitlines() if ".click(" in line)
    assert "loc.click(" in click_line
    body = source.split("async def _safe_click", 1)[1].split("\n    async def ", 1)[0]
    assert "UnsafeActionError" in body and ".click(" in body
    assert not re.search(r"\.press\(|keyboard\.|\.submit\(|requestSubmit\(", source)


def test_page_scripts_never_click_or_submit():
    # Comment lines are stripped before a script runs (job_radar.prefill.js), so skip them here.
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in (SRC / "prefill").glob("*.js")
        for line in path.read_text("utf-8").splitlines()
        if not line.lstrip().startswith("//") and FORBIDDEN_JS.search(line)
    ]
    assert not offenders, "\n".join(offenders)


def test_side_panel_extension_cannot_touch_pages():
    extension = SRC / "web" / "extension"
    manifest = json.loads((extension / "manifest.json").read_text("utf-8"))
    assert set(manifest["permissions"]) == {"sidePanel", "tabs"}
    assert "content_scripts" not in manifest and "host_permissions" not in manifest
    for path in extension.glob("*.js"):
        source = path.read_text("utf-8")
        assert "chrome.scripting" not in source and "executeScript" not in source, path.name


def test_pages_never_use_browser_dialogs():
    # Playwright dismisses confirm()/alert()/prompt() in the controlled Chrome, so a button
    # guarded by one silently does nothing (the "我已送出" button did, 2026-10-25).
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in (SRC / "web").rglob("*.js")
        for line in path.read_text("utf-8").splitlines()
        if not line.lstrip().startswith("//") and re.search(r"\b(confirm|alert|prompt)\(", line)
    ]
    assert not offenders, "\n".join(offenders)
