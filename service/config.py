"""Configuration helpers for the self-hosted service."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_APP_HOST = "0.0.0.0"
DEFAULT_APP_PORT = 8000
DEFAULT_STATE_DIR = "/data"
DEFAULT_CRON_SCHEDULE = "0 * * * *"
DEFAULT_TIMEZONE = "UTC"
DEFAULT_REFRESH_ON_STARTUP = True
DEFAULT_WORKER_TIMEOUT_SECONDS = 180


def _get_env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    value = value.strip()
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if not normalized:
        return default

    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _get_env_optional_str(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        return ""
    return value.strip()


class Settings:
    """Env-backed runtime settings with frozen task-one defaults."""

    def __init__(self) -> None:
        self.app_host = _get_env_str("APP_HOST", DEFAULT_APP_HOST)
        self.app_port = _get_env_int("APP_PORT", DEFAULT_APP_PORT)
        self.state_dir = _get_env_str("STATE_DIR", DEFAULT_STATE_DIR)
        self.author = _get_env_optional_str("AUTHOR")
        self.scholar = _get_env_optional_str("SCHOLAR")
        self.wos_overwrite = _get_env_optional_str("WOS_OVERWRITE")
        self.cron_schedule = _get_env_str("CRON_SCHEDULE", DEFAULT_CRON_SCHEDULE)
        self.timezone = _get_env_str("TIMEZONE", DEFAULT_TIMEZONE)
        self.refresh_on_startup = _get_env_bool(
            "REFRESH_ON_STARTUP",
            DEFAULT_REFRESH_ON_STARTUP,
        )
        self.worker_timeout_seconds = _get_env_int(
            "WORKER_TIMEOUT_SECONDS",
            DEFAULT_WORKER_TIMEOUT_SECONDS,
        )

    @property
    def wos_enabled(self) -> bool:
        return bool(self.wos_overwrite)

    def model_dump(self) -> dict[str, Any]:
        return {
            "app_host": self.app_host,
            "app_port": self.app_port,
            "state_dir": self.state_dir,
            "cron_schedule": self.cron_schedule,
            "timezone": self.timezone,
            "refresh_on_startup": self.refresh_on_startup,
            "worker_timeout_seconds": self.worker_timeout_seconds,
            "wos_overwrite_configured": bool(self.wos_overwrite),
        }
