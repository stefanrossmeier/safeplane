from __future__ import annotations

import urllib.request

import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from harness.notification_store import (
    create_notification_delivery_record,
    expire_notification_schedule,
    create_notification_outbox_once,
    get_notification_schedule,
    list_notification_schedules,
    mark_notification_outbox_failed,
    mark_notification_outbox_sent,
)


RECONCILE_INTERVAL_SECONDS = 5 * 60
INTERNAL_RECONCILE_JOB_ID = "safeplane:reconcile"
NOTIFICATION_JOB_PREFIX = "notification:"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")



def utc_iso_from_datetime(value: object) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"

def safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", "/data/safeplane")).expanduser()


def scheduler_log_path() -> Path:
    return safeplane_home() / "logs" / "scheduler" / "scheduler.jsonl"


def append_scheduler_log(event: str, payload: dict[str, Any]) -> None:
    path = scheduler_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": utc_now_iso(),
        "component": "scheduler",
        "event": event,
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_utc_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def notification_job_id(notification_id: str) -> str:
    return NOTIFICATION_JOB_PREFIX + notification_id


def notification_id_from_job_id(job_id: str) -> str | None:
    if not job_id.startswith(NOTIFICATION_JOB_PREFIX):
        return None
    return job_id[len(NOTIFICATION_JOB_PREFIX) :]


class ReloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "manual"
    schedule_id: str | None = None


class ReloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    active_jobs: int
    added: int
    updated: int
    removed: int
    error: str | None = None


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    active_jobs: int
    last_reload_at: str | None
    last_reload_error: str | None
    next_run_at_utc: str | None




WEEKDAY_TO_CRON = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}


def parse_hh_mm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text), int(minute_text)


def trigger_kwargs_for_record(record: object) -> tuple[str, dict[str, object]]:
    schedule = record.schedule
    schedule_type = schedule.schedule_type

    if schedule_type == "once":
        return (
            "date",
            {
                "run_date": parse_utc_iso(record.next_run_at_utc),
            },
        )

    if schedule_type == "daily_time":
        hour, minute = parse_hh_mm(schedule.time_local)
        return (
            "cron",
            {
                "hour": hour,
                "minute": minute,
                "timezone": schedule.timezone,
            },
        )

    if schedule_type == "weekly_time":
        hour, minute = parse_hh_mm(schedule.time_local)
        return (
            "cron",
            {
                "day_of_week": WEEKDAY_TO_CRON[schedule.day_of_week],
                "hour": hour,
                "minute": minute,
                "timezone": schedule.timezone,
            },
        )

    if schedule_type == "weekdays_time":
        hour, minute = parse_hh_mm(schedule.time_local)
        return (
            "cron",
            {
                "day_of_week": "mon-fri",
                "hour": hour,
                "minute": minute,
                "timezone": schedule.timezone,
            },
        )

    raise ValueError(f"Unsupported schedule_type: {schedule_type}")


def trigger_for_record(record: object) -> object:
    trigger_type, kwargs = trigger_kwargs_for_record(record)

    if trigger_type == "date":
        
        return DateTrigger(**kwargs)

    if trigger_type == "cron":
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(**kwargs)

    raise ValueError(f"Unsupported trigger type: {trigger_type}")
class SchedulerRuntime:
    def __init__(self) -> None:
        self._scheduler: Any | None = None
        self._lock = threading.Lock()
        self.last_reload_at: str | None = None
        self.last_reload_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._scheduler is not None:
                return

            from apscheduler.schedulers.background import BackgroundScheduler

            scheduler = BackgroundScheduler(timezone=UTC)
            scheduler.start()

            scheduler.add_job(
                self.reconcile,
                trigger="interval",
                seconds=RECONCILE_INTERVAL_SECONDS,
                id=INTERNAL_RECONCILE_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

            self._scheduler = scheduler

        self.reload(reason="startup")

    def stop(self) -> None:
        with self._lock:
            if self._scheduler is None:
                return
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def scheduler(self) -> Any:
        if self._scheduler is None:
            raise RuntimeError("scheduler is not started")
        return self._scheduler

    def notification_job_ids(self) -> set[str]:
        if self._scheduler is None:
            return set()

        return {
            job.id
            for job in self._scheduler.get_jobs()
            if job.id.startswith(NOTIFICATION_JOB_PREFIX)
        }

    def active_job_count(self) -> int:
        return len(self.notification_job_ids())

    def next_run_at_utc(self) -> str | None:
        if self._scheduler is None:
            return None

        next_runs: list[datetime] = []
        for job in self._scheduler.get_jobs():
            if not job.id.startswith(NOTIFICATION_JOB_PREFIX):
                continue
            if job.next_run_time is None:
                continue
            next_runs.append(job.next_run_time.astimezone(UTC))

        if not next_runs:
            return None

        return min(next_runs).isoformat(timespec="seconds").replace("+00:00", "Z")

    def status(self) -> StatusResponse:
        return StatusResponse(
            status="ok" if self.last_reload_error is None else "degraded",
            active_jobs=self.active_job_count(),
            last_reload_at=self.last_reload_at,
            last_reload_error=self.last_reload_error,
            next_run_at_utc=self.next_run_at_utc(),
        )

    def reconcile(self) -> None:
        try:
            response = self.reload(reason="periodic_reconciliation")
            if response.added or response.updated or response.removed:
                append_scheduler_log(
                    "periodic_reconciliation_changed_jobs",
                    response.model_dump(mode="json"),
                )
        except Exception as exc:
            self.last_reload_error = str(exc)
            append_scheduler_log(
                "periodic_reconciliation_failed",
                {
                    "error": str(exc),
                },
            )

    def reload(self, *, reason: str, schedule_id: str | None = None) -> ReloadResponse:
        with self._lock:
            scheduler = self.scheduler()
            existing_ids = self.notification_job_ids()

            records = list_notification_schedules(
                safeplane_home=safeplane_home(),
                include_cancelled=False,
            )
            desired_ids = {notification_job_id(record.id) for record in records}

            removed_ids = existing_ids - desired_ids
            added_ids = desired_ids - existing_ids
            updated_ids = desired_ids & existing_ids

            for job_id in removed_ids:
                scheduler.remove_job(job_id)

            for record in records:
                job_id = notification_job_id(record.id)
                run_date = parse_utc_iso(record.next_run_at_utc)

                scheduler.add_job(
                    notification_due,
                    trigger="date",
                    run_date=run_date,
                    id=job_id,
                    args=[record.id],
                    replace_existing=True,
                    misfire_grace_time=record.grace_seconds,
                    max_instances=1,
                    coalesce=True,
                )

            self.last_reload_at = utc_now_iso()
            self.last_reload_error = None

            response = ReloadResponse(
                status="ok",
                active_jobs=len(desired_ids),
                added=len(added_ids),
                updated=len(updated_ids),
                removed=len(removed_ids),
            )

            if response.added or response.updated or response.removed or reason != "periodic_reconciliation":
                append_scheduler_log(
                    "reload_completed",
                    {
                        **response.model_dump(mode="json"),
                        "reason": reason,
                        "schedule_id": schedule_id,
                    },
                )

            return response


def configured_connectors() -> list[str]:
    raw = os.environ.get("SAFEPLANE_NOTIFICATION_CONNECTORS", "log")
    connectors = [item.strip() for item in raw.split(",") if item.strip()]
    return connectors or ["log"]


def resolve_targets(targets: list[str]) -> list[str]:
    configured = configured_connectors()

    if "all" in targets:
        return configured

    resolved = [target for target in targets if target in configured or target == "log"]

    # Compatibility fallback: if the requested connector is not configured yet, use log delivery
    # rather than dropping the notification silently.
    return resolved or ["log"]


def deliver_to_log_connector(*, notification_id: str, outbox_id: str, message: str) -> None:
    append_scheduler_log(
        "log_connector_delivered",
        {
            "notification_id": notification_id,
            "outbox_id": outbox_id,
            "message": message,
        },
    )



def deliver_to_telegram_connector(
    notification_id: str,
    outbox_id: str,
    message: str,
) -> None:
    connector_url = os.environ.get(
        "SAFEPLANE_TELEGRAM_CONNECTOR_URL",
        "http://telegram-connector:8080",
    ).rstrip("/")

    body = json.dumps(
        {
            "notification_id": notification_id,
            "outbox_id": outbox_id,
            "message": message,
        },
        sort_keys=True,
    ).encode("utf-8")

    request = urllib.request.Request(
        connector_url + "/notifications/send",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        status_code = response.status

    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"Telegram connector returned HTTP {status_code}: {raw}")

    append_scheduler_log(
        "telegram_connector_delivered",
        {
            "notification_id": notification_id,
            "outbox_id": outbox_id,
            "connector_url": connector_url,
            "status_code": status_code,
            "response": raw[:500],
        },
    )

def notification_due(notification_id: str, scheduled_run_time: object | None = None) -> None:
    schedule = get_notification_schedule(
        safeplane_home=safeplane_home(),
        notification_id=notification_id,
    )

    if schedule is None:
        append_scheduler_log(
            "notification_due_missing_schedule",
            {
                "notification_id": notification_id,
            },
        )
        return

    if schedule.status != "active":
        append_scheduler_log(
            "notification_due_ignored_inactive_schedule",
            {
                "notification_id": notification_id,
                "status": schedule.status,
            },
        )
        return

    if scheduled_run_time is not None and hasattr(scheduled_run_time, "astimezone"):
        due_at_utc = utc_iso_from_datetime(scheduled_run_time)
    elif schedule.schedule.schedule_type == "once":
        due_at_utc = schedule.next_run_at_utc
    else:
        due_at_utc = utc_now_iso()

    outbox, created = create_notification_outbox_once(
        safeplane_home=safeplane_home(),
        schedule=schedule,
        due_at_utc=due_at_utc,
    )

    if not created and outbox.status == "sent":
        append_scheduler_log(
            "notification_due_duplicate_ignored",
            {
                "notification_id": notification_id,
                "outbox_id": outbox.id,
                "status": outbox.status,
            },
        )
        return

    connectors = resolve_targets(schedule.targets)
    failed: list[str] = []

    append_scheduler_log(
        "notification_delivery_started",
        {
            "notification_id": notification_id,
            "outbox_id": outbox.id,
            "connectors": connectors,
        },
    )

    for connector in connectors:
        try:
            if connector == "log":
                deliver_to_log_connector(
                    notification_id=notification_id,
                    outbox_id=outbox.id,
                    message=outbox.message,
                )
            elif connector == "telegram":
                deliver_to_telegram_connector(
                    notification_id=notification_id,
                    outbox_id=outbox.id,
                    message=outbox.message,
                )
            else:
                # Real connectors are wired in a later notification system slice.
                # For now, non-log connectors are recorded as fake successful delivery
                # so fanout and idempotency can be tested before Telegram wiring.
                append_scheduler_log(
                    "fake_connector_delivered",
                    {
                        "connector": connector,
                        "notification_id": notification_id,
                        "outbox_id": outbox.id,
                        "message": outbox.message,
                    },
                )

            create_notification_delivery_record(
                safeplane_home=safeplane_home(),
                outbox=outbox,
                connector=connector,
                status="sent",
            )
        except Exception as exc:
            failed.append(connector)
            create_notification_delivery_record(
                safeplane_home=safeplane_home(),
                outbox=outbox,
                connector=connector,
                status="failed",
                error=str(exc),
            )

    if failed:
        mark_notification_outbox_failed(
            safeplane_home=safeplane_home(),
            outbox=outbox,
            error="failed connectors: " + ", ".join(failed),
        )
        append_scheduler_log(
            "notification_delivery_failed",
            {
                "notification_id": notification_id,
                "outbox_id": outbox.id,
                "failed_connectors": failed,
            },
        )
    else:
        sent = mark_notification_outbox_sent(
            safeplane_home=safeplane_home(),
            outbox=outbox,
        )
        if schedule.schedule.schedule_type == "once":
            expired = expire_notification_schedule(
                safeplane_home=safeplane_home(),
                notification_id=notification_id,
            )
            append_scheduler_log(
                "notification_schedule_expired",
                {
                    "notification_id": notification_id,
                    "expired": expired is not None,
                },
            )

        append_scheduler_log(
            "notification_delivery_succeeded",
            {
                "notification_id": notification_id,
                "outbox_id": sent.id,
                "connectors": connectors,
            },
        )


runtime = SchedulerRuntime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.start()
    try:
        yield
    finally:
        runtime.stop()


app = FastAPI(
    title="Safeplane Scheduler",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reload", response_model=ReloadResponse)
def reload_scheduler(request: ReloadRequest) -> ReloadResponse:
    try:
        return runtime.reload(
            reason=request.reason,
            schedule_id=request.schedule_id,
        )
    except Exception as exc:
        runtime.last_reload_error = str(exc)
        append_scheduler_log(
            "reload_failed",
            {
                "reason": request.reason,
                "schedule_id": request.schedule_id,
                "error": str(exc),
            },
        )
        return ReloadResponse(
            status="failed",
            active_jobs=runtime.active_job_count(),
            added=0,
            updated=0,
            removed=0,
            error=str(exc),
        )


@app.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return runtime.status()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "safeplane_scheduler.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
