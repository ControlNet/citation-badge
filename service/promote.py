"""Release promotion helpers for staged worker output."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid

from .storage import CURRENT_RELEASE_POINTER, get_state_layout

DIST_DIRNAME = "dist"
REQUIRED_DIST_FILENAMES = ("citation.json", "all.svg")


def staged_dist_path(staged_run_dir: str) -> str:
    """Return the canonical dist directory for a staged worker run."""

    return os.path.join(os.path.abspath(os.fspath(staged_run_dir)), DIST_DIRNAME)


def validate_staged_release(staged_run_dir: str) -> bool:
    """Return True only when the staged run contains promotable public artifacts."""

    dist_dir = staged_dist_path(staged_run_dir)
    if not os.path.isdir(dist_dir):
        return False

    for filename in REQUIRED_DIST_FILENAMES:
        if not os.path.isfile(os.path.join(dist_dir, filename)):
            return False

    citation_json_path = os.path.join(dist_dir, "citation.json")
    try:
        with open(citation_json_path, "r", encoding="utf-8") as handle:
            json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False

    return True


def _resolve_run_id(staged_run_dir: str) -> str:
    run_id = os.path.basename(
        os.path.normpath(os.path.abspath(os.fspath(staged_run_dir)))
    )
    if not run_id:
        raise ValueError("Unable to derive a release run id from staged_run_dir")
    return run_id


def _copy_release(staged_run_dir: str, release_dir: str) -> str:
    staged_dist_dir = staged_dist_path(staged_run_dir)
    releases_dir = os.path.dirname(release_dir)
    temp_release_dir = tempfile.mkdtemp(
        dir=releases_dir,
        prefix=f".{os.path.basename(release_dir)}.",
        suffix=".tmp",
    )

    try:
        shutil.copytree(staged_dist_dir, os.path.join(temp_release_dir, DIST_DIRNAME))
        os.replace(temp_release_dir, release_dir)
    except Exception:
        shutil.rmtree(temp_release_dir, ignore_errors=True)
        raise

    return release_dir


def _atomic_switch_current(current_pointer: str, release_dir: str) -> None:
    state_dir = os.path.dirname(current_pointer)
    temp_pointer = os.path.join(
        state_dir,
        f".{CURRENT_RELEASE_POINTER}.{uuid.uuid4().hex}.tmp",
    )

    if os.path.isdir(current_pointer) and not os.path.islink(current_pointer):
        raise RuntimeError(
            f"Current release pointer must not be a directory: {current_pointer}"
        )

    try:
        os.symlink(release_dir, temp_pointer)
        os.replace(temp_pointer, current_pointer)
    except Exception:
        if os.path.lexists(temp_pointer):
            os.unlink(temp_pointer)
        raise


def promote_release(state_dir: str, staged_run_dir: str) -> str:
    """Promote a validated staged run into the public current release pointer."""

    layout = get_state_layout(state_dir)
    os.makedirs(layout.state_dir, exist_ok=True)
    os.makedirs(layout.releases_dir, exist_ok=True)

    if not validate_staged_release(staged_run_dir):
        raise ValueError(
            "Staged release is incomplete; expected dist/citation.json and dist/all.svg"
        )

    run_id = _resolve_run_id(staged_run_dir)
    release_dir = os.path.join(layout.releases_dir, run_id)
    if os.path.exists(release_dir):
        raise FileExistsError(f"Release already exists for run id '{run_id}'")

    _copy_release(staged_run_dir, release_dir)
    _atomic_switch_current(layout.current_pointer, release_dir)
    return release_dir


def current_release_path(state_dir: str) -> str | None:
    """Resolve the currently published release directory, if any."""

    current_pointer = get_state_layout(state_dir).current_pointer
    if not os.path.lexists(current_pointer):
        return None

    if os.path.islink(current_pointer):
        resolved_release = os.path.realpath(current_pointer)
    elif os.path.isdir(current_pointer):
        resolved_release = os.path.abspath(current_pointer)
    else:
        return None

    if not os.path.isdir(resolved_release):
        return None

    return resolved_release


__all__ = [
    "current_release_path",
    "promote_release",
    "staged_dist_path",
    "validate_staged_release",
]
