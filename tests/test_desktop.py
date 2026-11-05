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


def test_launcher_runs_the_installed_command_with_the_home_folder(tmp_path):
    home = tmp_path / "Application Support" / "Job Radar"
    script = launcher_script(home, tmp_path / "bin dir" / "job-radar")
    assert f"export JOB_RADAR_HOME='{home}'" in script
    assert f"JR='{tmp_path / 'bin dir' / 'job-radar'}'" in script
    assert 'nohup "$JR" ui' in script and "uv" not in script
    check = subprocess.run(["zsh", "-n"], input=script, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr


def test_install_app_builds_a_bundle(tmp_path):
    app = install_app(tmp_path / "Job Radar", tmp_path / "job-radar", tmp_path / "Applications")
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == LAUNCHER and info["CFBundlePackageType"] == "APPL"
    launcher = app / "Contents" / "MacOS" / LAUNCHER
    assert launcher.stat().st_mode & stat.S_IXUSR
    if "CFBundleIconFile" in info:
        assert (app / "Contents" / "Resources" / "AppIcon.icns").stat().st_size > 0
    # Installing again replaces the old bundle.
    again = install_app(tmp_path / "Job Radar", tmp_path / "job-radar", tmp_path / "Applications")
    assert again == app


def test_fetch_agent_runs_the_installed_command_for_the_home_folder(tmp_path):
    from job_radar.desktop import FETCH_AGENT, fetch_agent_plist

    home, command = tmp_path / "Job Radar", tmp_path / "bin" / "job-radar"
    agent = fetch_agent_plist(home, command, 8, 30)
    assert agent["Label"] == FETCH_AGENT
    assert agent["ProgramArguments"] == [str(command), "fetch", "--if-stale"]
    assert agent["EnvironmentVariables"] == {"JOB_RADAR_HOME": str(home)}
    assert agent["RunAtLoad"] is True  # makes up a run missed while the Mac was off
    assert agent["WorkingDirectory"] == str(home)
    assert agent["StartCalendarInterval"] == {"Hour": 8, "Minute": 30}
    plistlib.dumps(agent)  # serializable as a launchd plist


def test_the_installed_schedule_says_when_a_fetch_is_due(tmp_path):
    from job_radar.desktop import FETCH_AGENT, fetch_agent_plist, scheduled_time

    assert scheduled_time(tmp_path) is None  # nothing installed: the caller uses 08:30
    agent = fetch_agent_plist(tmp_path, tmp_path / "job-radar", 7, 15)
    (tmp_path / f"{FETCH_AGENT}.plist").write_bytes(plistlib.dumps(agent))
    assert scheduled_time(tmp_path) == (7, 15)


def old_clone(path):
    (path / "profile" / "resumes").mkdir(parents=True)
    (path / "profile" / "applicant.yaml").write_text("basic: {}\n")
    (path / "data" / "logs").mkdir(parents=True)
    (path / "data" / "jobs.duckdb").write_bytes(b"db")
    (path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-x\n")
    (path / "README.md").write_text("code stays")
    return path


def test_moving_an_old_clone_into_the_home_folder(tmp_path):
    from job_radar.desktop import move_home

    old, new = old_clone(tmp_path / "Job Radar"), tmp_path / "Application Support" / "Job Radar"
    assert move_home(old, new) == ["profile", "data", ".env"]
    assert (new / "profile" / "applicant.yaml").read_text() == "basic: {}\n"
    assert (new / "data" / "jobs.duckdb").read_bytes() == b"db"
    assert (new / ".env").exists()
    assert not (old / "profile").exists() and (old / "README.md").exists()


def test_moving_refuses_rather_than_overwrite_or_pull_files_from_a_running_assistant(tmp_path):
    import os

    import pytest

    from job_radar.desktop import MoveError, move_home

    old, new = old_clone(tmp_path / "old"), tmp_path / "new"
    (new / "profile").mkdir(parents=True)
    with pytest.raises(MoveError, match="profile"):
        move_home(old, new)
    assert (old / "data").exists() and not (new / "data").exists()  # nothing moved

    (new / "profile").rmdir()
    write_session(old / "data", Session(port=8765, token="t", pid=os.getpid()))
    with pytest.raises(MoveError, match="還開著"):
        move_home(old, new)
    with pytest.raises(MoveError, match="沒有"):
        move_home(tmp_path / "empty", new)


def test_migrate_moves_the_files_and_leaves_no_app_or_schedule_it_did_not_find(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from typer.testing import CliRunner

    from job_radar import cli

    monkeypatch.delenv("JOB_RADAR_HOME")
    fake_home = tmp_path / "user"
    monkeypatch.setattr(Path, "home", lambda: fake_home)  # no real Dock app or LaunchAgent
    monkeypatch.setattr(cli, "APP_SUPPORT", fake_home / "Library" / "Application Support" / "JR")
    old = old_clone(tmp_path / "Job Radar")
    result = CliRunner().invoke(cli.app, ["migrate", str(old)])
    assert result.exit_code == 0, result.output
    assert (fake_home / "Library" / "Application Support" / "JR" / "profile").is_dir()
    assert not (fake_home / "Applications").exists()
