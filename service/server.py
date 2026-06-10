"""HTTP server skeleton for the self-hosted citation service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
from types import FrameType, ModuleType
from typing import Any, cast
from urllib.parse import urlsplit

from service.config import Settings
from service.promote import (
    current_release_path,
    promote_release,
    validate_staged_release,
)
from service.scheduler import create_service_scheduler
from service.worker import (
    WorkerShutdownError,
    build_worker_argv,
    google_scholar_failure_result,
    run_worker_subprocess,
    web_of_science_failure_result,
)


JSON_COMPATIBILITY_PATH = "/citation.json"
SVG_CONTENT_TYPE = "image/svg+xml"
_PUBLICATION_SVG_PATH = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9_.-]*\.svg$")
_WORKER_SCRIPT_PATH = "/app/main.py"
_LOGGER = logging.getLogger("citation_badge.service")


def _configure_runtime_logging() -> None:
    if _LOGGER.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


def _storage_module() -> ModuleType:
    return import_module("service.storage")


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_success_at(previous: Mapping[str, Any] | None) -> str | None:
    if not isinstance(previous, Mapping):
        return None

    value = previous.get("last_success_at")
    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def _disabled_source_state(previous: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "enabled": False,
        "status": "disabled",
        "last_attempt_at": None,
        "last_success_at": _last_success_at(previous),
        "last_error": None,
    }


def _running_source_state(
    previous: Mapping[str, Any] | None,
    attempted_at: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "running",
        "last_attempt_at": attempted_at,
        "last_success_at": _last_success_at(previous),
        "last_error": None,
    }


def _successful_source_state(
    attempted_at: str,
    finished_at: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "success",
        "last_attempt_at": attempted_at,
        "last_success_at": finished_at,
        "last_error": None,
    }


def _source_payload(
    citation_payload: Mapping[str, Any] | None,
    source_name: str,
) -> Mapping[str, Any] | None:
    if not isinstance(citation_payload, Mapping):
        return None

    source_payload = citation_payload.get(source_name)
    if not isinstance(source_payload, Mapping):
        return None
    return source_payload


def _source_succeeded(
    citation_payload: Mapping[str, Any] | None,
    source_name: str,
) -> bool:
    source_payload = _source_payload(citation_payload, source_name)
    if source_payload is None:
        return False
    return str(source_payload.get("status", "")).strip().lower() == "success"


def _source_error(
    citation_payload: Mapping[str, Any] | None,
    source_name: str,
    fallback_error: str,
) -> str:
    source_payload = _source_payload(citation_payload, source_name)
    if source_payload is None:
        return fallback_error

    value = source_payload.get("error")
    if isinstance(value, str) and value.strip():
        return value.strip()

    status = str(source_payload.get("status", "")).strip().lower()
    if status and status not in {"success", "skipped"}:
        return f"{source_name} refresh ended with status '{status}'"
    return fallback_error


def _worker_failure_message(
    error: BaseException,
    completed: subprocess.CompletedProcess[str] | None = None,
) -> str:
    if isinstance(error, WorkerShutdownError):
        return str(error)
    if isinstance(error, subprocess.TimeoutExpired):
        return f"Worker timed out after {int(error.timeout)} seconds"
    if isinstance(error, subprocess.CalledProcessError):
        return str(error)

    if completed is not None and completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        if stderr:
            return stderr.splitlines()[-1]
        if stdout:
            return stdout.splitlines()[-1]
        return f"Worker exited with code {completed.returncode}"

    message = str(error).strip()
    return message or error.__class__.__name__


def _default_worker_script_path() -> str:
    if os.path.isfile(_WORKER_SCRIPT_PATH):
        return _WORKER_SCRIPT_PATH
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")


class ServiceRuntime:
    """Own refresh execution, staged promotion, and worker shutdown wiring."""

    def __init__(
        self,
        *,
        settings: Settings,
        state_layout: Any,
        worker_python_executable: str = "python",
        worker_script_path: str | None = None,
    ) -> None:
        self.settings = settings
        self.state_layout = state_layout
        self.worker_python_executable = worker_python_executable
        self.worker_script_path = worker_script_path or _default_worker_script_path()
        self._shutdown_requested = threading.Event()
        self._active_worker_lock = threading.Lock()
        self._active_worker_process: subprocess.Popen[str] | None = None
        self._active_worker_stop_event: threading.Event | None = None

    def synchronize_status(self) -> dict[str, Any]:
        payload = self._load_status()
        payload["storage"]["current_release"] = current_release_path(
            self.settings.state_dir
        )
        payload["storage"]["has_data"] = (
            payload["storage"]["current_release"] is not None
        )

        google_scholar = payload["sources"]["google_scholar"]
        google_scholar["enabled"] = True
        if google_scholar.get("status") == "disabled":
            google_scholar["status"] = "never_succeeded"

        if self.settings.wos_enabled:
            web_of_science = payload["sources"]["web_of_science"]
            web_of_science["enabled"] = True
            if web_of_science.get("status") == "disabled":
                web_of_science["status"] = (
                    "stale" if _last_success_at(web_of_science) else "never_succeeded"
                )
        else:
            payload["sources"]["web_of_science"] = _disabled_source_state(
                payload["sources"]["web_of_science"]
            )

        if payload["service"].get("status") in {"running", "stopping"}:
            payload["service"]["status"] = (
                "ready" if payload["storage"]["has_data"] else "idle"
            )
        elif (
            payload["storage"]["has_data"]
            and payload["service"].get("status") == "idle"
        ):
            payload["service"]["status"] = "ready"
        elif not payload["storage"]["has_data"] and payload["service"].get(
            "status"
        ) in {"ready", "stale"}:
            payload["service"]["status"] = "idle"

        payload = self._save_status(payload)
        _LOGGER.info(
            "service status synchronized: service_status=%s has_data=%s current_release=%s",
            payload["service"].get("status"),
            payload["storage"].get("has_data"),
            payload["storage"].get("current_release"),
        )
        return payload

    def refresh(self, trigger_reason: str) -> None:
        if self._shutdown_requested.is_set():
            _LOGGER.info(
                "refresh skipped: trigger=%s reason=shutdown_requested",
                trigger_reason,
            )
            return

        previous_status = self._load_status()
        attempted_at = _timestamp_now()
        self._write_running_status(previous_status, attempted_at)
        _LOGGER.info(
            "refresh started: trigger=%s attempted_at=%s state_dir=%s",
            trigger_reason,
            attempted_at,
            self.settings.state_dir,
        )

        if not (self.settings.author or self.settings.scholar):
            finished_at = _timestamp_now()
            service_status = self._failure_service_status()
            _LOGGER.warning(
                "refresh aborted: trigger=%s reason=missing_AUTHOR_or_SCHOLAR",
                trigger_reason,
            )
            self._write_terminal_status(
                service_status=service_status,
                previous_status=previous_status,
                attempted_at=attempted_at,
                finished_at=finished_at,
                citation_payload=None,
                fallback_error="AUTHOR or SCHOLAR must be configured",
            )
            return

        staged_run_dir = tempfile.mkdtemp(
            dir=self.state_layout.state_dir,
            prefix=".staged-refresh-",
        )
        completed: subprocess.CompletedProcess[str] | None = None

        try:
            worker_stop_event = threading.Event()
            argv = build_worker_argv(
                author=self.settings.author,
                scholar=self.settings.scholar,
                python_executable=self.worker_python_executable,
                script_path=self.worker_script_path,
            )
            _LOGGER.info(
                "worker starting: trigger=%s staged_run_dir=%s author_configured=%s scholar_configured=%s wos_enabled=%s",
                trigger_reason,
                staged_run_dir,
                bool(self.settings.author),
                bool(self.settings.scholar),
                self.settings.wos_enabled,
            )
            completed = run_worker_subprocess(
                argv,
                working_directory=staged_run_dir,
                timeout_seconds=self.settings.worker_timeout_seconds,
                started_callback=lambda process: self._set_active_worker(
                    process,
                    worker_stop_event,
                ),
                stop_event=worker_stop_event,
            )
            _LOGGER.info(
                "worker finished: trigger=%s returncode=%s stdout_bytes=%s stderr_bytes=%s",
                trigger_reason,
                completed.returncode,
                len(completed.stdout.encode("utf-8")),
                len(completed.stderr.encode("utf-8")),
            )

            if self._shutdown_requested.is_set():
                raise WorkerShutdownError(
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=completed.returncode,
                )
            if completed.returncode != 0:
                raise RuntimeError(_worker_failure_message(RuntimeError(), completed))
            if not validate_staged_release(staged_run_dir):
                raise ValueError(
                    "Staged release is incomplete; expected dist/citation.json and dist/all.svg"
                )

            citation_payload = self._load_staged_citation_payload(staged_run_dir)
            promote_release(self.settings.state_dir, staged_run_dir)
            _LOGGER.info(
                "promotion completed: trigger=%s staged_run_dir=%s current_release=%s",
                trigger_reason,
                staged_run_dir,
                current_release_path(self.settings.state_dir),
            )
            self._write_terminal_status(
                service_status="ready",
                previous_status=previous_status,
                attempted_at=attempted_at,
                finished_at=_timestamp_now(),
                citation_payload=citation_payload,
                fallback_error="Refresh succeeded without source metadata",
            )
            _LOGGER.info(
                "refresh succeeded: trigger=%s service_status=ready",
                trigger_reason,
            )
        except Exception as error:
            citation_payload = self._load_staged_citation_payload(staged_run_dir)
            service_status = (
                "stopping"
                if isinstance(error, WorkerShutdownError)
                else self._failure_service_status()
            )
            self._write_terminal_status(
                service_status=service_status,
                previous_status=previous_status,
                attempted_at=attempted_at,
                finished_at=_timestamp_now(),
                citation_payload=citation_payload,
                fallback_error=_worker_failure_message(error, completed),
            )
            _LOGGER.warning(
                "refresh failed: trigger=%s service_status=%s error=%s",
                trigger_reason,
                service_status,
                _worker_failure_message(error, completed),
            )
        finally:
            self._clear_active_worker()
            shutil.rmtree(staged_run_dir, ignore_errors=True)
            _LOGGER.info(
                "refresh finished: trigger=%s cleaned_staged_run_dir=%s",
                trigger_reason,
                staged_run_dir,
            )

    def shutdown_worker(self) -> None:
        self._shutdown_requested.set()
        payload = self._load_status()
        payload["service"]["status"] = "stopping"
        self._save_status(payload)

        with self._active_worker_lock:
            stop_event = self._active_worker_stop_event
            process = self._active_worker_process

        _LOGGER.info(
            "worker shutdown requested: active_worker=%s",
            process is not None and process.poll() is None,
        )

        if stop_event is not None:
            stop_event.set()
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _failure_service_status(self) -> str:
        return "stale" if current_release_path(self.settings.state_dir) else "failed"

    def _load_status(self) -> dict[str, Any]:
        return _storage_module().safe_load_status(
            self.state_layout.status_file,
            settings=self.settings,
        )

    def _save_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["storage"]["current_release"] = current_release_path(
            self.settings.state_dir
        )
        payload["storage"]["has_data"] = (
            payload["storage"]["current_release"] is not None
        )
        return _storage_module().save_status(
            self.state_layout.status_file,
            payload,
            settings=self.settings,
        )

    def _write_running_status(
        self,
        previous_status: Mapping[str, Any],
        attempted_at: str,
    ) -> dict[str, Any]:
        payload = self._load_status()
        payload["service"]["status"] = "running"
        payload["sources"]["google_scholar"] = _running_source_state(
            previous_status.get("sources", {}).get("google_scholar"),
            attempted_at,
        )
        if self.settings.wos_enabled:
            payload["sources"]["web_of_science"] = _running_source_state(
                previous_status.get("sources", {}).get("web_of_science"),
                attempted_at,
            )
        else:
            payload["sources"]["web_of_science"] = _disabled_source_state(
                previous_status.get("sources", {}).get("web_of_science")
            )
        return self._save_status(payload)

    def _write_terminal_status(
        self,
        *,
        service_status: str,
        previous_status: Mapping[str, Any],
        attempted_at: str,
        finished_at: str,
        citation_payload: Mapping[str, Any] | None,
        fallback_error: str,
    ) -> dict[str, Any]:
        payload = self._load_status()
        payload["service"]["status"] = service_status
        payload["sources"]["google_scholar"] = self._google_scholar_status(
            previous_status=previous_status.get("sources", {}).get("google_scholar"),
            attempted_at=attempted_at,
            finished_at=finished_at,
            citation_payload=citation_payload,
            fallback_error=fallback_error,
        )
        payload["sources"]["web_of_science"] = self._web_of_science_status(
            previous_status=previous_status.get("sources", {}).get("web_of_science"),
            attempted_at=attempted_at,
            finished_at=finished_at,
            citation_payload=citation_payload,
            fallback_error=fallback_error,
        )
        return self._save_status(payload)

    def _google_scholar_status(
        self,
        *,
        previous_status: Mapping[str, Any] | None,
        attempted_at: str,
        finished_at: str,
        citation_payload: Mapping[str, Any] | None,
        fallback_error: str,
    ) -> dict[str, Any]:
        if _source_succeeded(citation_payload, "google_scholar"):
            return _successful_source_state(attempted_at, finished_at)

        return google_scholar_failure_result(
            _source_error(citation_payload, "google_scholar", fallback_error),
            attempted_at=attempted_at,
            previous=previous_status,
        )

    def _web_of_science_status(
        self,
        *,
        previous_status: Mapping[str, Any] | None,
        attempted_at: str,
        finished_at: str,
        citation_payload: Mapping[str, Any] | None,
        fallback_error: str,
    ) -> dict[str, Any]:
        if not self.settings.wos_enabled:
            return _disabled_source_state(previous_status)

        if _source_succeeded(citation_payload, "web_of_science"):
            return _successful_source_state(attempted_at, finished_at)

        return web_of_science_failure_result(
            _source_error(citation_payload, "web_of_science", fallback_error),
            attempted_at=attempted_at,
            previous=previous_status,
            enable_wos=True,
        )

    def _set_active_worker(
        self,
        process: subprocess.Popen[str],
        stop_event: threading.Event,
    ) -> None:
        with self._active_worker_lock:
            self._active_worker_process = process
            self._active_worker_stop_event = stop_event
            if self._shutdown_requested.is_set():
                stop_event.set()
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass

    def _clear_active_worker(self) -> None:
        with self._active_worker_lock:
            self._active_worker_process = None
            self._active_worker_stop_event = None

    def _load_staged_citation_payload(
        self,
        staged_run_dir: str,
    ) -> Mapping[str, Any] | None:
        citation_json_path = os.path.join(staged_run_dir, "dist", "citation.json")
        try:
            payload = _storage_module().load_json_file(citation_json_path)
        except (
            FileNotFoundError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

        if not isinstance(payload, Mapping):
            return None
        return payload


class CitationServiceHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server that owns runtime settings and state paths."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        settings: Settings,
        *,
        worker_python_executable: str = "python",
        worker_script_path: str | None = None,
    ) -> None:
        self.settings = settings
        self._background_services_stopped = False
        self.state_layout = _storage_module().ensure_state_layout(
            settings.state_dir,
            settings=settings,
        )
        self.runtime = ServiceRuntime(
            settings=settings,
            state_layout=self.state_layout,
            worker_python_executable=worker_python_executable,
            worker_script_path=worker_script_path,
        )
        self.scheduler = create_service_scheduler(
            settings=settings,
            status_path=self.state_layout.status_file,
            refresh=self.runtime.refresh,
            shutdown_callback=self.runtime.shutdown_worker,
        )
        super().__init__(
            (settings.app_host, settings.app_port),
            CitationServiceRequestHandler,
        )

    def start_background_services(self) -> None:
        _LOGGER.info(
            "service starting background services: host=%s port=%s state_dir=%s cron=%s timezone=%s refresh_on_startup=%s wos_enabled=%s",
            self.settings.app_host,
            self.settings.app_port,
            self.settings.state_dir,
            self.settings.cron_schedule,
            self.settings.timezone,
            self.settings.refresh_on_startup,
            self.settings.wos_enabled,
        )
        self.runtime.synchronize_status()
        self.scheduler.start()
        _LOGGER.info("service background services started")

    def stop_background_services(self) -> None:
        if self._background_services_stopped:
            return
        self._background_services_stopped = True
        _LOGGER.info("service stopping background services")
        self.scheduler.shutdown()
        _LOGGER.info("service background services stopped")

    def server_close(self) -> None:
        self.stop_background_services()
        super().server_close()
        _LOGGER.info("service server closed")


class CitationServiceRequestHandler(BaseHTTPRequestHandler):
    """Serve the minimal self-hosted HTTP contract for task 3."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        self._dispatch_request(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler naming
        self._dispatch_request(include_body=False)

    def _dispatch_request(self, *, include_body: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/status":
            self._handle_status(include_body=include_body)
            return
        if path == JSON_COMPATIBILITY_PATH:
            self._handle_citation_json(include_body=include_body)
            return
        if self._is_supported_svg_path(path):
            self._handle_svg(path, include_body=include_body)
            return
        self._respond_text(
            HTTPStatus.NOT_FOUND, "Not Found\n", include_body=include_body
        )

    def _service_server(self) -> CitationServiceHTTPServer:
        return cast(CitationServiceHTTPServer, self.server)

    def _handle_status(self, *, include_body: bool) -> None:
        server = self._service_server()
        payload = _storage_module().safe_load_status(
            server.state_layout.status_file,
            settings=server.settings,
        )
        self._respond_json(HTTPStatus.OK, payload, include_body=include_body)

    def _handle_citation_json(self, *, include_body: bool) -> None:
        artifact_path = self._current_release_artifact_path("citation.json")
        if artifact_path is None:
            self._respond_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "no_data", "message": "No successful refresh yet"},
                include_body=include_body,
            )
            return

        self._respond_file(
            HTTPStatus.OK,
            artifact_path,
            content_type="application/json; charset=utf-8",
            include_body=include_body,
        )

    def _handle_svg(self, path: str, *, include_body: bool) -> None:
        artifact_path = self._current_release_artifact_path(path.lstrip("/"))
        if artifact_path is None:
            self._respond_text(
                HTTPStatus.NOT_FOUND, "Not Found\n", include_body=include_body
            )
            return

        self._respond_file(
            HTTPStatus.OK,
            artifact_path,
            content_type=SVG_CONTENT_TYPE,
            include_body=include_body,
        )

    def _current_release_artifact_path(self, filename: str) -> str | None:
        release_dir = current_release_path(self._service_server().settings.state_dir)
        if release_dir is None:
            return None

        artifact_path = os.path.join(release_dir, "dist", filename)
        if not os.path.isfile(artifact_path):
            return None
        return artifact_path

    def _is_supported_svg_path(self, path: str) -> bool:
        if path in {"/all.svg", "/review.svg"}:
            return True
        return _PUBLICATION_SVG_PATH.fullmatch(path) is not None

    def _respond_json(
        self,
        status: HTTPStatus,
        payload: Any,
        *,
        include_body: bool,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _respond_text(
        self,
        status: HTTPStatus,
        message: str,
        *,
        include_body: bool,
    ) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _respond_file(
        self,
        status: HTTPStatus,
        file_path: str,
        *,
        content_type: str,
        include_body: bool,
    ) -> None:
        with open(file_path, "rb") as handle:
            body = handle.read()

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(
    settings: Settings | None = None,
    *,
    worker_python_executable: str = "python",
    worker_script_path: str | None = None,
) -> CitationServiceHTTPServer:
    """Build the service server with resolved runtime settings."""

    return CitationServiceHTTPServer(
        settings or Settings(),
        worker_python_executable=worker_python_executable,
        worker_script_path=worker_script_path,
    )


def _request_shutdown(server: CitationServiceHTTPServer) -> None:
    _LOGGER.info("service shutdown requested")
    server.stop_background_services()
    server.shutdown()


def _install_signal_handlers(
    server: CitationServiceHTTPServer,
) -> dict[signal.Signals, Any]:
    handled_signals = (signal.SIGINT, signal.SIGTERM)
    previous_handlers = {signum: signal.getsignal(signum) for signum in handled_signals}
    shutdown_requested = threading.Event()

    def _handle_signal(signum: int, _: FrameType | None) -> None:
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        _LOGGER.info("signal received: signum=%s", signum)
        threading.Thread(
            target=_request_shutdown,
            args=(server,),
            name=f"citation-service-shutdown-{signum}",
            daemon=True,
        ).start()

    for signum in handled_signals:
        signal.signal(signum, _handle_signal)

    return previous_handlers


def _restore_signal_handlers(previous_handlers: dict[signal.Signals, Any]) -> None:
    for signum, handler in previous_handlers.items():
        signal.signal(signum, handler)


def main() -> None:
    """Start the self-hosted HTTP service."""

    _configure_runtime_logging()
    server = create_server()
    _LOGGER.info("service process initialized")
    previous_handlers = _install_signal_handlers(server)
    server.start_background_services()
    try:
        _LOGGER.info(
            "service listening: http://%s:%s",
            server.settings.app_host,
            server.settings.app_port,
        )
        server.serve_forever()
    except KeyboardInterrupt:
        _LOGGER.info("keyboard interrupt received")
        pass
    finally:
        _restore_signal_handlers(previous_handlers)
        server.server_close()
        _LOGGER.info("service stopped")


if __name__ == "__main__":
    main()
