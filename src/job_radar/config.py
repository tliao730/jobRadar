"""Configuration: tunable values from config/settings.yaml, secrets from the environment."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class EnvSettings(BaseSettings):
    """Values read from environment variables or `.env`."""

    model_config = SettingsConfigDict(extra="ignore")

    tailor_model: str = "claude-sonnet-5-5"


class ModelPrice(BaseModel):
    input: float  # USD per 1M input tokens
    output: float  # USD per 1M output tokens


class LLMConfig(BaseModel):
    effort: Effort = "medium"
    max_tokens: int = 16000
    max_jd_chars: int = 12000
    # Server-side refusal fallback ("default" lets the API pick); null disables it.
    fallbacks: Literal["default"] | None = "default"
    prices: dict[str, ModelPrice] = Field(default_factory=dict)


class ResumeRule(BaseModel):
    variant: str
    title_pattern: str  # regex, case-insensitive


class ApplyConfig(BaseModel):
    default_resume: str | None = None
    resume_rules: list[ResumeRule] = Field(default_factory=list)


class BrowserConfig(BaseModel):
    # "chrome" uses the installed Google Chrome; None uses Playwright's bundled Chromium.
    channel: str | None = "chrome"
    user_data_dir: str = "data/browser-profile"


class PathsConfig(BaseModel):
    profile_dir: str = "profile"
    data_dir: str = "data"


class UIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class AppConfig(BaseModel):
    root: Path
    paths: PathsConfig = Field(default_factory=PathsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    apply: ApplyConfig = Field(default_factory=ApplyConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    env: EnvSettings = Field(default_factory=EnvSettings)

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.root / p

    @property
    def profile_dir(self) -> Path:
        return self.resolve(self.paths.profile_dir)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.paths.data_dir)

    @property
    def browser_profile_dir(self) -> Path:
        return self.resolve(self.browser.user_data_dir)


def find_root() -> Path:
    """Project root: $JOB_RADAR_ROOT, else the current directory."""
    return Path(os.environ.get("JOB_RADAR_ROOT", Path.cwd())).resolve()


def load_config(root: Path | None = None) -> AppConfig:
    root = (root or find_root()).resolve()
    settings_path = root / "config" / "settings.yaml"
    data = {}
    if settings_path.exists():
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    else:
        log.warning("找不到 %s，使用預設設定", settings_path)
    env = EnvSettings(_env_file=root / ".env")  # type: ignore[call-arg]
    _export_dotenv(root / ".env")
    return AppConfig(root=root, env=env, **data)


def _read_dotenv(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            value = value.strip().strip('"').strip("'")
            if sep and key and not key.startswith("#") and value:
                values[key] = value
    return values


def _export_dotenv(path: Path) -> None:
    """Expose ANTHROPIC_* values from `.env` to the Anthropic SDK, which reads os.environ.

    The project's `.env` wins over the shell: whoever owns the key in `.env` pays for this
    project's API calls, even if another key (for example a lab's) is exported globally.
    """
    for key, value in _read_dotenv(path).items():
        if not key.startswith("ANTHROPIC_"):
            continue
        if os.environ.get(key) not in (None, value):
            log.warning("以 .env 的 %s 取代環境變數中的值", key)
        os.environ[key] = value


def has_anthropic_credential() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def describe_anthropic_credential(root: Path) -> str:
    """Which credential the Anthropic SDK will use, for display (never the full key)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        source = (
            ".env" if _read_dotenv(root / ".env").get("ANTHROPIC_API_KEY") == key else "環境變數"
        )
        return f"金鑰 …{key[-4:]}（{source}）"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "ANTHROPIC_AUTH_TOKEN（環境變數）"
    return "未設定金鑰"
