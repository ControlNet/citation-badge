"""APScheduler-backed cron helpers for the self-hosted citation service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import threading
from typing import Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import SchedulerNotRunningError
from apscheduler.triggers.cron import CronTrigger


from .config import Settings
from .storage import safe_load_status, save_status

JOB_ID = "citation-refresh"
_UNSET = object()

RefreshCallback = Callable[[str], Any]
ShutdownCallback = Callable[[], Any]


class OverlapGuard:
    """A non-blocking lock used to skip overlapping refresh runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        if self._lock.locked():
            self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


def overlap_guard() -> OverlapGuard:
    """Build a fresh overlap guard using skip-on-contention semantics."""

    return OverlapGuard()


def _noop_refresh(_: str) -> None:
    return None


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def build_scheduler(
    cron_schedule: str,
    timezone_name: str,
    job: Callable[[], Any] | None = None,
) -> BackgroundScheduler:
    """Create a scheduler with one cron job configured from the runtime settings."""

    scheduler = BackgroundScheduler(timezone=timezone_name, daemon=True)
    scheduler.add_job(
        job or (lambda: None),
        trigger=CronTrigger.from_crontab(cron_schedule, timezone=timezone_name),
        id=JOB_ID,
        replace_existing=True,
        coalesce=False,
        max_instances=1,
    )
    return scheduler


class ServiceScheduler:
    """Own the APScheduler lifecycle and persisted schedule metadata."""

    def __init__(
        self,
        *,
        settings: Settings,
        status_path: str,
        refresh: RefreshCallback | None = None,
        shutdown_callback: ShutdownCallback | None = None,
        guard: OverlapGuard | None = None,
    ) -> None:
        self.settings = settings
        self.status_path = status_path
        self.shutdown_event = threading.Event()
        self._refresh = refresh or _noop_refresh
        self._shutdown_callback = shutdown_callback
        self._guard = guard or overlap_guard()
        self._lifecycle_lock = threading.Lock()
        self._started = False
        self._stopped = False
        self._scheduler = build_scheduler(
            settings.cron_schedule,
            settings.timezone,
            job=self._run_scheduled_refresh,
        )

    @property
    def scheduler(self) -> BackgroundScheduler:
        return self._scheduler

    def start(self) -> None:
        """Start cron scheduling and optionally run the startup refresh hook."""

        with self._lifecycle_lock:
            if self._started:
                return
            self._started = True

        self._write_schedule_status(running=False)
        self._scheduler.start()
        self._sync_next_run_time()

        if self.settings.refresh_on_startup and not self.shutdown_event.is_set():
            threading.Thread(
                target=self._run_startup_refresh,
                name="citation-startup-refresh",
                daemon=True,
            ).start()

    def shutdown(self) -> None:
        """Stop future scheduling and invoke the optional worker shutdown callback."""

        with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopped = True

        self.shutdown_event.set()

        try:
            self._scheduler.shutdown(wait=False)
        except SchedulerNotRunningError:
            pass

        if self._shutdown_callback is not None:
            self._shutdown_callback()

        self._write_schedule_status(next_run_at=None)

    def _run_startup_refresh(self) -> None:
        try:
            self._execute_refresh("startup")
        except Exception:
            return

    def _run_scheduled_refresh(self) -> None:
        self._execute_refresh("schedule")

    def _execute_refresh(self, trigger_reason: str) -> bool:
        if self.shutdown_event.is_set():
            return False
        if not self._guard.acquire():
            self._sync_next_run_time()
            return False

        self._write_schedule_status(
            running=True,
            last_started_at=_timestamp_now(),
        )

        try:
            self._refresh(trigger_reason)
        finally:
            self._guard.release()
            self._write_schedule_status(
                running=False,
                last_finished_at=_timestamp_now(),
            )
            self._sync_next_run_time()

        return True

    def _sync_next_run_time(self) -> None:
        job = self._scheduler.get_job(JOB_ID)
        next_run_time = _serialize_datetime(
            getattr(job, "next_run_time", None) if job is not None else None
        )
        self._write_schedule_status(next_run_at=next_run_time)

    def _write_schedule_status(
        self,
        *,
        running: bool | object = _UNSET,
        next_run_at: str | None | object = _UNSET,
        last_started_at: str | None | object = _UNSET,
        last_finished_at: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        payload = safe_load_status(self.status_path, settings=self.settings)
        schedule = payload["schedule"]
        schedule["cron"] = self.settings.cron_schedule
        schedule["timezone"] = self.settings.timezone
        schedule["refresh_on_startup"] = self.settings.refresh_on_startup
        schedule["overlap_policy"] = "skip"

        if running is not _UNSET:
            schedule["running"] = running
        if next_run_at is not _UNSET:
            schedule["next_run_at"] = next_run_at
        if last_started_at is not _UNSET:
            schedule["last_started_at"] = last_started_at
        if last_finished_at is not _UNSET:
            schedule["last_finished_at"] = last_finished_at

        return save_status(self.status_path, payload, settings=self.settings)


def create_service_scheduler(
    *,
    settings: Settings,
    status_path: str,
    refresh: RefreshCallback | None = None,
    shutdown_callback: ShutdownCallback | None = None,
    guard: OverlapGuard | None = None,
) -> ServiceScheduler:
    """Create the service scheduler runtime wrapper."""

    return ServiceScheduler(
        settings=settings,
        status_path=status_path,
        refresh=refresh,
        shutdown_callback=shutdown_callback,
        guard=guard,
    )


__all__ = [
    "JOB_ID",
    "OverlapGuard",
    "ServiceScheduler",
    "build_scheduler",
    "create_service_scheduler",
    "overlap_guard",
]
