"""Configuration loader — reads clutch.yaml + .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ProfileConfig(BaseModel):
    name: str = "User"
    interests: list[str] = Field(default_factory=list)
    location: str = ""


class OllamaConfig(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "gemma3:4b"
    timeout: int = 120


class ScoringConfig(BaseModel):
    critical_threshold: float = 0.80
    high_threshold: float = 0.50
    auto_expire_days: int = 3
    max_calendar_events: int = 10
    max_new_per_run: int = 5


class CalendarOutputConfig(BaseModel):
    calendar_name: str = "Clutch Radar"
    colors: dict[str, str] = Field(
        default_factory=lambda: {"critical": "11", "high": "6", "info": "9"}
    )


class OutputConfig(BaseModel):
    google_calendar: CalendarOutputConfig = Field(default_factory=CalendarOutputConfig)


class ConnectorServerConfig(BaseModel):
    name: str
    channels: list[str] = Field(default_factory=list)


class DiscordConnectorConfig(BaseModel):
    enabled: bool = False
    servers: list[ConnectorServerConfig] = Field(default_factory=list)


class LumaConnectorConfig(BaseModel):
    enabled: bool = False
    cities: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class RSSConnectorConfig(BaseModel):
    enabled: bool = False
    feeds: list[str] = Field(default_factory=list)


class ConnectorsConfig(BaseModel):
    discord: DiscordConnectorConfig = Field(default_factory=DiscordConnectorConfig)
    luma: LumaConnectorConfig = Field(default_factory=LumaConnectorConfig)
    rss: RSSConnectorConfig = Field(default_factory=RSSConnectorConfig)

    model_config = {"extra": "allow"}


class ClutchCoreConfig(BaseModel):
    schedule: str = "4h"
    timezone: str = "Asia/Kolkata"
    digest_time: str = "07:00"


class ClutchConfig(BaseModel):
    clutch: ClutchCoreConfig = Field(default_factory=ClutchCoreConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    connectors: ConnectorsConfig = Field(default_factory=ConnectorsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


class EnvSettings(BaseSettings):
    """Secrets from .env file."""

    google_client_id: str = ""
    google_client_secret: str = ""
    discord_token: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    github_token: str = ""
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    sentry_dsn: str = ""
    ollama_host: str = "http://localhost:11434"

    model_config = {"env_file": ".env", "extra": "ignore"}


def find_config_file() -> Path:
    """Walk up from cwd to find clutch.yaml."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / "clutch.yaml"
        if candidate.exists():
            return candidate
    return Path("clutch.yaml")


def load_config(config_path: Optional[str] = None) -> ClutchConfig:
    """Load clutch.yaml into a validated config object."""
    path = Path(config_path) if config_path else find_config_file()
    if not path.exists():
        return ClutchConfig()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    return ClutchConfig.model_validate(raw)


def load_env(env_path: Optional[str] = None) -> EnvSettings:
    """Load secrets from .env."""
    if env_path:
        os.environ.setdefault("ENV_FILE", env_path)
    return EnvSettings()
