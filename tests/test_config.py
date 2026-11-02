import pytest

from job_radar.config import describe_anthropic_credential, load_config


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


def test_settings_defaults_without_a_config_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.env.tailor_model == "claude-sonnet-5-5"
    assert cfg.profile_dir == tmp_path / "profile"
