import pytest

from job_radar import config
from job_radar.config import describe_anthropic_credential, find_home, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def test_project_env_file_wins_over_the_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-lab-key-1111")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-my-own-key-2222\n", encoding="utf-8")
    load_config(tmp_path)
    assert describe_anthropic_credential(tmp_path) == "金鑰 …2222（.env）"


def test_shell_key_is_reported_as_such(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-lab-key-1111")
    load_config(tmp_path)
    assert describe_anthropic_credential(tmp_path) == "金鑰 …1111（環境變數）"


def test_no_key(tmp_path):
    load_config(tmp_path)
    assert describe_anthropic_credential(tmp_path) == "未設定金鑰"


def test_shared_settings_ship_with_the_package(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.env.tailor_model == "claude-sonnet-5-5"
    assert cfg.profile_dir == tmp_path / "profile"
    assert cfg.browser_profile_dir == tmp_path / "data" / "browser-profile"
    assert cfg.ui.port == 8765 and cfg.apply.resume_rules  # from defaults/settings.yaml
    assert (cfg.defaults_dir / "filters.yaml").is_file()


def test_my_settings_override_only_what_they_name(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "settings.yaml").write_text("ui: {port: 8766}\nllm: {effort: low}\n")
    cfg = load_config(tmp_path)
    assert cfg.ui.port == 8766 and cfg.ui.host == "127.0.0.1"
    assert cfg.llm.effort == "low" and cfg.llm.prices  # the rest stays shared


def test_the_home_folder_is_app_support_unless_named(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_RADAR_HOME")
    support, checkout = tmp_path / "Application Support" / "Job Radar", tmp_path / "clone"
    monkeypatch.setattr(config, "APP_SUPPORT", support)
    monkeypatch.setattr(config, "CHECKOUT", checkout)
    assert find_home() == support
    monkeypatch.setenv("JOB_RADAR_HOME", str(tmp_path / "mine"))
    assert find_home() == tmp_path / "mine"


def test_an_old_clone_keeps_working_until_migrated(tmp_path, monkeypatch):
    # Before 2026-11-04 the clone held profile/ and data/: a `git pull` alone must not leave
    # the Dock app and the daily fetch looking at an empty home folder.
    monkeypatch.delenv("JOB_RADAR_HOME")
    support, checkout = tmp_path / "Application Support" / "Job Radar", tmp_path / "clone"
    (checkout / "data").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("")
    monkeypatch.setattr(config, "APP_SUPPORT", support)
    monkeypatch.setattr(config, "CHECKOUT", checkout)
    assert find_home() == checkout
    support.mkdir(parents=True)  # moved (or set up) by now
    assert find_home() == support
