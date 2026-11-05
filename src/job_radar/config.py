"""Configuration and where things live.

- Shared defaults ship inside the package (`defaults/`, in git): everyone gets the same ones
  and an update replaces them, so nobody edits them in place.
- Each person's files live in their home folder, `~/Library/Application Support/Job Radar/`
  (or $JOB_RADAR_HOME): `profile/` (their facts and settings, which override the defaults),
  `data/` (databases, logs, the browser profile) and `.env` (secrets).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULTS_DIR = PACKAGE_DIR / "defaults"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Job Radar"
CHECKOUT = PACKAGE_DIR.parents[1]  # the repository, when running from a source checkout
LEGACY_DIRS = ("profile", "data")  # what a clone held before 2026-11-04, when it was the home

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
    home: Path  # this person's folder: profile/, data/, .env
    defaults_dir: Path = DEFAULTS_DIR  # the shared settings shipped with the package
    paths: PathsConfig = Field(default_factory=PathsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    apply: ApplyConfig = Field(default_factory=ApplyConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    env: EnvSettings = Field(default_factory=EnvSettings)

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.home / p

    @property
    def profile_dir(self) -> Path:
        return self.resolve(self.paths.profile_dir)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.paths.data_dir)

    @property
    def browser_profile_dir(self) -> Path:
        return self.resolve(self.browser.user_data_dir)


def legacy_home(checkout: Path | None = None) -> Path | None:
    """A source checkout still holding profile/ or data/ from when the clone was the home
    folder (before 2026-11-04), else None."""
    checkout = checkout or CHECKOUT
    if (checkout / "pyproject.toml").is_file() and any(
        (checkout / name).is_dir() for name in LEGACY_DIRS
    ):
        return checkout
    return None


def find_home() -> Path:
    """$JOB_RADAR_HOME, else ~/Library/Application Support/Job Radar. A checkout that still
    holds the old profile/ and data/ stays in use (with a warning) until `job-radar migrate`,
    so a `git pull` alone never strands someone's data and daily fetch."""
    if env := os.environ.get("JOB_RADAR_HOME"):
        return Path(env).expanduser().resolve()
    legacy = legacy_home()
    if legacy and not APP_SUPPORT.exists():
        log.warning("資料還在舊位置 %s：執行 `job-radar migrate` 搬到 %s", legacy, APP_SUPPORT)
        return legacy
    return APP_SUPPORT


def load_config(home: Path | None = None) -> AppConfig:
    """Shared settings.yaml, overridden by the person's own profile/settings.yaml (only the
    keys they change, merged like the radar's settings)."""
    from job_radar.radar.models import merge_settings

    home = (home or find_home()).resolve()
    data = merge_settings(
        _read_yaml(DEFAULTS_DIR / "settings.yaml"), _read_yaml(home / "profile" / "settings.yaml")
    )
    env = EnvSettings(_env_file=home / ".env")  # type: ignore[call-arg]
    _export_dotenv(home / ".env")
    return AppConfig(home=home, env=env, **data)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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

    The home folder's `.env` wins over the shell: whoever owns the key in `.env` pays for this
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


def describe_anthropic_credential(home: Path) -> str:
    """Which credential the Anthropic SDK will use, for display (never the full key)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        source = (
            ".env" if _read_dotenv(home / ".env").get("ANTHROPIC_API_KEY") == key else "環境變數"
        )
        return f"金鑰 …{key[-4:]}（{source}）"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "ANTHROPIC_AUTH_TOKEN（環境變數）"
    return "未設定金鑰"
