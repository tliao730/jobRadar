import json
import plistlib
import stat
import subprocess

from job_radar.desktop import (
    LAUNCHER,
    Session,
    install_app,
    launcher_script,
    prepare_extension,
    read_session,
    remove_session,
    session_path,
    write_session,
)


def test_extension_is_copied_and_pointed_at_the_server(tmp_path):
    target = prepare_extension(tmp_path, "http://127.0.0.1:9999")
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["side_panel"]["default_path"] == "sidepanel.html"
    assert (target / "sidepanel.js").exists() and (target / "icon-128.png").exists()
    assert 'const JR_ORIGIN = "http://127.0.0.1:9999";' in (target / "config.js").read_text()
    # Re-running (every start) overwrites in place.
    prepare_extension(tmp_path, "http://127.0.0.1:8765")
    assert "8765" in (target / "config.js").read_text()


def test_session_file_is_private_and_owned(tmp_path):
    write_session(tmp_path, Session(port=8765, token="abc", pid=1))
    assert stat.S_IMODE(session_path(tmp_path).stat().st_mode) == 0o600
    assert read_session(tmp_path) == Session(port=8765, token="abc", pid=1)
    remove_session(tmp_path, "someone-else")
    assert read_session(tmp_path) is not None
    remove_session(tmp_path, "abc")
    assert read_session(tmp_path) is None


def test_broken_session_file_is_ignored(tmp_path):
    session_path(tmp_path).write_text("{not json")
    assert read_session(tmp_path) is None


def test_launcher_quotes_paths_with_spaces(tmp_path):
    root = tmp_path / "Job Radar"
    script = launcher_script(root, tmp_path / "bin dir" / "uv")
    assert f"ROOT='{root}'" in script
    assert 'nohup "$UV" run job-radar ui' in script
    check = subprocess.run(["zsh", "-n"], input=script, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr


def test_install_app_builds_a_bundle(tmp_path):
    app = install_app(tmp_path / "Job Radar", tmp_path / "uv", tmp_path / "Applications")
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == LAUNCHER and info["CFBundlePackageType"] == "APPL"
    launcher = app / "Contents" / "MacOS" / LAUNCHER
    assert launcher.stat().st_mode & stat.S_IXUSR
    if "CFBundleIconFile" in info:
        assert (app / "Contents" / "Resources" / "AppIcon.icns").stat().st_size > 0
    # Installing again replaces the old bundle.
    assert install_app(tmp_path / "Job Radar", tmp_path / "uv", tmp_path / "Applications") == app


def test_fetch_agent_runs_fetch_in_the_project(tmp_path):
    from job_radar.desktop import FETCH_AGENT, fetch_agent_plist

    agent = fetch_agent_plist(tmp_path / "Job Radar", tmp_path / "uv", 8, 30)
    assert agent["Label"] == FETCH_AGENT
    assert agent["ProgramArguments"][1:] == ["run", "job-radar", "fetch", "--if-stale"]
    assert agent["RunAtLoad"] is True  # makes up a run missed while the Mac was off
    assert agent["WorkingDirectory"] == str(tmp_path / "Job Radar")
    assert agent["StartCalendarInterval"] == {"Hour": 8, "Minute": 30}
    plistlib.dumps(agent)  # serializable as a launchd plist


def test_the_installed_schedule_says_when_a_fetch_is_due(tmp_path):
    from job_radar.desktop import FETCH_AGENT, fetch_agent_plist, scheduled_time

    assert scheduled_time(tmp_path) is None  # nothing installed: the caller uses 08:30
    agent = fetch_agent_plist(tmp_path, tmp_path / "uv", 7, 15)
    (tmp_path / f"{FETCH_AGENT}.plist").write_bytes(plistlib.dumps(agent))
    assert scheduled_time(tmp_path) == (7, 15)
