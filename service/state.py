"""Status payload helpers for the self-hosted service."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import __version__
from .config import Settings


def _empty_source_state(*, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "status": "never_succeeded" if enabled else "disabled",
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
    }


def empty_status(
    settings: Settings | None = None,
    *,
    state_dir: str | None = None,
) -> dict[str, Any]:
    runtime_settings = settings or Settings()

    return {
        "service": {
            "mode": "self_hosted",
            "status": "idle",
            "version": __version__,
        },
        "schedule": {
            "cron": runtime_settings.cron_schedule,
            "timezone": runtime_settings.timezone,
            "refresh_on_startup": runtime_settings.refresh_on_startup,
            "overlap_policy": "skip",
            "running": False,
            "next_run_at": None,
            "last_started_at": None,
            "last_finished_at": None,
        },
        "storage": {
            "state_dir": state_dir or runtime_settings.state_dir,
            "current_release": None,
            "has_data": False,
        },
        "sources": {
            "google_scholar": _empty_source_state(enabled=True),
            "web_of_science": _empty_source_state(enabled=runtime_settings.wos_enabled),
        },
    }


def _merge_status(default_value: Any, loaded_value: Any) -> Any:
    if isinstance(default_value, dict) and not isinstance(loaded_value, dict):
        return deepcopy(default_value)

    if not isinstance(default_value, dict) or not isinstance(loaded_value, dict):
        return deepcopy(loaded_value)

    merged = {key: deepcopy(value) for key, value in default_value.items()}
    for key, value in loaded_value.items():
        if key in merged:
            merged[key] = _merge_status(merged[key], value)
            continue
        merged[key] = deepcopy(value)

    return merged


def normalize_status(
    status: Any,
    settings: Settings | None = None,
    *,
    state_dir: str | None = None,
) -> dict[str, Any]:
    baseline = empty_status(settings, state_dir=state_dir)
    if not isinstance(status, dict):
        return baseline
    normalized = _merge_status(baseline, status)
    normalized["storage"]["state_dir"] = baseline["storage"]["state_dir"]
    return normalized
