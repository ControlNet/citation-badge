"""Filesystem-backed runtime storage helpers for the self-hosted service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import tempfile
from typing import Any

from .config import Settings
from .state import empty_status, normalize_status

CURRENT_RELEASE_POINTER = "current"
RELEASES_DIRNAME = "releases"
STATUS_FILENAME = "status.json"


@dataclass(frozen=True)
class StateLayout:
    """Resolved filesystem paths for the writable runtime state."""

    state_dir: str
    releases_dir: str
    status_file: str
    current_pointer: str


def get_state_layout(state_dir: str) -> StateLayout:
    resolved_state_dir = os.path.abspath(os.fspath(state_dir))
    return StateLayout(
        state_dir=resolved_state_dir,
        releases_dir=os.path.join(resolved_state_dir, RELEASES_DIRNAME),
        status_file=os.path.join(resolved_state_dir, STATUS_FILENAME),
        current_pointer=os.path.join(resolved_state_dir, CURRENT_RELEASE_POINTER),
    )


def ensure_state_layout(
    state_dir: str,
    settings: Settings | None = None,
) -> StateLayout:
    layout = get_state_layout(state_dir)
    os.makedirs(layout.state_dir, exist_ok=True)
    os.makedirs(layout.releases_dir, exist_ok=True)

    if not os.path.exists(layout.status_file):
        save_status(
            layout.status_file, empty_status(settings, state_dir=layout.state_dir)
        )

    return layout


def atomic_write_json(path: str, payload: Any) -> None:
    destination = os.path.abspath(os.fspath(path))
    parent_dir = os.path.dirname(destination)
    os.makedirs(parent_dir, exist_ok=True)

    file_descriptor, temp_path = tempfile.mkstemp(
        dir=parent_dir,
        prefix=f".{os.path.basename(destination)}.",
        suffix=".tmp",
    )

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_load_status(
    status_path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_status_path = os.path.abspath(os.fspath(status_path))
    state_dir = os.path.dirname(resolved_status_path)

    try:
        payload = load_json_file(resolved_status_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return empty_status(settings, state_dir=state_dir)

    return normalize_status(payload, settings, state_dir=state_dir)


def save_status(
    status_path: str,
    payload: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    normalized_payload = normalize_status(
        payload,
        settings,
        state_dir=os.path.dirname(os.path.abspath(os.fspath(status_path))),
    )
    atomic_write_json(status_path, normalized_payload)
    return normalized_payload
