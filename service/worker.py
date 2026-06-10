"""Subprocess worker helpers for wrapping the existing main.py entrypoint."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import os
import subprocess
import time
import threading
from typing import Any

PYTHON_EXECUTABLE = "python"
MAIN_SCRIPT_PATH = "/app/main.py"
DIST_DIRNAME = "dist"
CI_BATCH_ONLY_FILENAMES = frozenset({"citation_updated.flag", "summary.md"})

GOOGLE_SCHOLAR_SOURCE = "google_scholar"
WEB_OF_SCIENCE_SOURCE = "web_of_science"
SUPPORTED_SOURCES = frozenset({GOOGLE_SCHOLAR_SOURCE, WEB_OF_SCIENCE_SOURCE})
PROCESS_POLL_INTERVAL_SECONDS = 0.2
PROFILE_TIMEOUT_SECONDS = 180

ProcessStartedCallback = Callable[[subprocess.Popen[str]], None]


class WorkerShutdownError(RuntimeError):
    """Raised when service shutdown terminates an in-flight worker."""

    def __init__(
        self,
        message: str = "Worker terminated during shutdown",
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _normalize_cli_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _has_cli_value(value: str | None) -> bool:
    return bool(_normalize_cli_value(value))


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_worker_argv(
    *,
    scholar: str | None,
    python_executable: str = PYTHON_EXECUTABLE,
    script_path: str = MAIN_SCRIPT_PATH,
) -> list[str]:
    """Build argv for service-mode execution of the existing batch script."""

    argv = [python_executable, script_path]

    if _has_cli_value(scholar):
        argv.extend(["--scholar", str(scholar)])

    argv.extend(["--timeout", str(PROFILE_TIMEOUT_SECONDS)])

    return argv


def get_worker_dist_dir(working_directory: str) -> str:
    """Resolve the only directory that service mode treats as public worker output."""

    resolved_working_directory = os.path.abspath(os.fspath(working_directory))
    return os.path.join(resolved_working_directory, DIST_DIRNAME)


def cleanup_ci_batch_side_files(working_directory: str) -> None:
    """Remove CI-only side files after a service-mode worker run."""

    resolved_working_directory = os.path.abspath(os.fspath(working_directory))
    for filename in CI_BATCH_ONLY_FILENAMES:
        file_path = os.path.join(resolved_working_directory, filename)
        try:
            os.unlink(file_path)
        except FileNotFoundError:
            continue


def _source_enabled(source: str, *, enable_wos: bool) -> bool:
    if source == GOOGLE_SCHOLAR_SOURCE:
        return True
    if source == WEB_OF_SCIENCE_SOURCE:
        return enable_wos
    raise ValueError(
        f"Unsupported source '{source}'. Expected one of {sorted(SUPPORTED_SOURCES)}"
    )


def _previous_success_timestamp(previous: Mapping[str, Any] | None) -> str | None:
    if not isinstance(previous, Mapping):
        return None

    last_success_at = previous.get("last_success_at")
    if not isinstance(last_success_at, str):
        return None

    last_success_at = last_success_at.strip()
    return last_success_at or None


def record_failure_result(
    source: str,
    error: str,
    *,
    attempted_at: str | None = None,
    previous: Mapping[str, Any] | None = None,
    enable_wos: bool = True,
) -> dict[str, Any]:
    """Build a source status payload for a failed worker attempt."""

    enabled = _source_enabled(source, enable_wos=enable_wos)
    last_success_at = _previous_success_timestamp(previous)
    message = str(error).strip() or "Unknown worker failure"

    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "last_attempt_at": None,
            "last_success_at": last_success_at,
            "last_error": None,
        }

    return {
        "enabled": True,
        "status": "stale" if last_success_at else "failed",
        "last_attempt_at": attempted_at or _timestamp_now(),
        "last_success_at": last_success_at,
        "last_error": message,
    }


def google_scholar_failure_result(
    error: str,
    *,
    attempted_at: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return record_failure_result(
        GOOGLE_SCHOLAR_SOURCE,
        error,
        attempted_at=attempted_at,
        previous=previous,
        enable_wos=True,
    )


def web_of_science_failure_result(
    error: str,
    *,
    attempted_at: str | None = None,
    previous: Mapping[str, Any] | None = None,
    enable_wos: bool = True,
) -> dict[str, Any]:
    return record_failure_result(
        WEB_OF_SCIENCE_SOURCE,
        error,
        attempted_at=attempted_at,
        previous=previous,
        enable_wos=enable_wos,
    )


def run_worker_subprocess(
    argv: Sequence[str],
    *,
    working_directory: str,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
    started_callback: ProcessStartedCallback | None = None,
    stop_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the worker subprocess with explicit cwd and timeout controls."""

    if not argv:
        raise ValueError("Worker argv must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("Worker timeout_seconds must be positive")

    resolved_working_directory = os.path.abspath(os.fspath(working_directory))
    if not os.path.isdir(resolved_working_directory):
        raise ValueError(
            f"Worker working_directory must be an existing directory: {resolved_working_directory}"
        )

    run_env = os.environ.copy()
    if env is not None:
        run_env.update({str(key): str(value) for key, value in env.items()})

    try:
        process = subprocess.Popen(
            list(argv),
            cwd=resolved_working_directory,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )

        if started_callback is not None:
            started_callback(process)

        deadline = time.monotonic() + timeout_seconds
        while True:
            if stop_event is not None and stop_event.is_set():
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    if process.poll() is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    stdout, stderr = process.communicate()
                raise WorkerShutdownError(
                    stdout=stdout,
                    stderr=stderr,
                    returncode=process.returncode,
                )

            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                if process.poll() is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(
                    list(argv),
                    timeout_seconds,
                    output=stdout,
                    stderr=stderr,
                )

            try:
                stdout, stderr = process.communicate(
                    timeout=min(PROCESS_POLL_INTERVAL_SECONDS, remaining_seconds)
                )
            except subprocess.TimeoutExpired:
                continue

            return subprocess.CompletedProcess(
                list(argv),
                process.returncode,
                stdout,
                stderr,
            )
    finally:
        cleanup_ci_batch_side_files(resolved_working_directory)


__all__ = [
    "GOOGLE_SCHOLAR_SOURCE",
    "MAIN_SCRIPT_PATH",
    "PYTHON_EXECUTABLE",
    "CI_BATCH_ONLY_FILENAMES",
    "DIST_DIRNAME",
    "SUPPORTED_SOURCES",
    "WEB_OF_SCIENCE_SOURCE",
    "build_worker_argv",
    "cleanup_ci_batch_side_files",
    "get_worker_dist_dir",
    "google_scholar_failure_result",
    "record_failure_result",
    "run_worker_subprocess",
    "WorkerShutdownError",
    "web_of_science_failure_result",
]
