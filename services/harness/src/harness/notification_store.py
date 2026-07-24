from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from harness.notification_schemas import (
    DEFAULT_NOTIFICATION_TIMEZONE,
    DEFAULT_ONCE_GRACE_SECONDS,
    DEFAULT_RECURRING_GRACE_SECONDS,
    NotificationDeliveryRecord,
    NotificationListToolInput,
    NotificationListToolOutput,
    NotificationOutboxRecord,
    NotificationScheduleRecord,
    NotificationScheduleToolInput,
)


WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safeplane_home(explicit_home: str | Path | None = None) -> Path:
    if explicit_home is not None:
        return Path(explicit_home).expanduser()

    return Path(os.environ.get("SAFEPLANE_HOME", "~/.safeplane")).expanduser()


def notification_data_dir(explicit_home: str | Path | None = None) -> Path:
    return safeplane_home(explicit_home) / "data" / "notifications"


def notification_schedules_path(explicit_home: str | Path | None = None) -> Path:
    return notification_data_dir(explicit_home) / "schedules.jsonl"


def notification_outbox_path(explicit_home: str | Path | None = None) -> Path:
    return notification_data_dir(explicit_home) / "outbox.jsonl"


def notification_deliveries_path(explicit_home: str | Path | None = None) -> Path:
    return notification_data_dir(explicit_home) / "deliveries.jsonl"


def model_to_json_dict(model: BaseModel) -> dict:
    return model.model_dump(mode="json")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

    return records


def write_jsonl(path: Path, records: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(model_to_json_dict(record), sort_keys=True) + "\n" for record in records)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, record: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(model_to_json_dict(record), sort_keys=True) + "\n")


def parse_time_local(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError(f"Invalid time_local value {value!r}; expected HH:MM") from exc

    return time(hour=hour, minute=minute)


def utc_iso_from_datetime(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_time_to_utc_iso(
    run_at_local: str,
    timezone_name: str = DEFAULT_NOTIFICATION_TIMEZONE,
) -> str:
    value = datetime.fromisoformat(run_at_local)
    timezone = ZoneInfo(timezone_name)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone)
    else:
        value = value.astimezone(timezone)

    return utc_iso_from_datetime(value)


def next_daily_run_at_utc(
    time_local: str,
    timezone: str,
    now_utc: datetime | None = None,
) -> str:
    tz = ZoneInfo(timezone)
    local_time = parse_time_local(time_local)

    if now_utc is None:
        now_local = datetime.now(UTC).astimezone(tz)
    else:
        now_local = now_utc.astimezone(tz)

    candidate = datetime.combine(now_local.date(), local_time, tzinfo=tz)
    if candidate <= now_local:
        candidate = candidate + timedelta(days=1)

    return utc_iso_from_datetime(candidate)


def next_weekly_run_at_utc(
    day_of_week: str,
    time_local: str,
    timezone: str,
    now_utc: datetime | None = None,
) -> str:
    tz = ZoneInfo(timezone)
    local_time = parse_time_local(time_local)

    if now_utc is None:
        now_local = datetime.now(UTC).astimezone(tz)
    else:
        now_local = now_utc.astimezone(tz)

    target_weekday = WEEKDAY_TO_INDEX[day_of_week]
    days_ahead = (target_weekday - now_local.weekday()) % 7
    candidate_date = now_local.date() + timedelta(days=days_ahead)
    candidate = datetime.combine(candidate_date, local_time, tzinfo=tz)

    if candidate <= now_local:
        candidate = candidate + timedelta(days=7)

    return utc_iso_from_datetime(candidate)


def next_weekdays_run_at_utc(
    time_local: str,
    timezone: str,
    now_utc: datetime | None = None,
) -> str:
    tz = ZoneInfo(timezone)
    local_time = parse_time_local(time_local)

    if now_utc is None:
        now_local = datetime.now(UTC).astimezone(tz)
    else:
        now_local = now_utc.astimezone(tz)

    for days_ahead in range(0, 8):
        candidate_date = now_local.date() + timedelta(days=days_ahead)
        if candidate_date.weekday() >= 5:
            continue

        candidate = datetime.combine(candidate_date, local_time, tzinfo=tz)
        if candidate > now_local:
            return utc_iso_from_datetime(candidate)

    raise ValueError("Could not determine next weekday run")


def next_run_at_utc_for_schedule(schedule: object, now_utc: datetime | None = None) -> str:
    schedule_type = getattr(schedule, "schedule_type")

    if schedule_type == "once":
        return local_time_to_utc_iso(schedule.run_at_local, schedule.timezone)

    if schedule_type == "daily_time":
        return next_daily_run_at_utc(schedule.time_local, schedule.timezone, now_utc=now_utc)

    if schedule_type == "weekly_time":
        return next_weekly_run_at_utc(
            schedule.day_of_week,
            schedule.time_local,
            schedule.timezone,
            now_utc=now_utc,
        )

    if schedule_type == "weekdays_time":
        return next_weekdays_run_at_utc(schedule.time_local, schedule.timezone, now_utc=now_utc)

    raise ValueError(f"Unsupported notification schedule_type: {schedule_type}")


def create_notification_schedule(
    payload: NotificationScheduleToolInput,
    explicit_home: str | Path | None = None,
) -> NotificationScheduleRecord:
    now = utc_now_iso()

    grace_seconds = payload.grace_seconds
    if grace_seconds is None:
        grace_seconds = (
            DEFAULT_ONCE_GRACE_SECONDS
            if payload.schedule.schedule_type == "once"
            else DEFAULT_RECURRING_GRACE_SECONDS
        )

    record = NotificationScheduleRecord(
        id=f"notif_sched_{uuid4()}",
        status="active",
        created_at=now,
        updated_at=now,
        message=payload.message,
        schedule=payload.schedule,
        targets=payload.targets,
        grace_seconds=grace_seconds,
        next_run_at_utc=next_run_at_utc_for_schedule(payload.schedule),
    )

    append_jsonl(notification_schedules_path(explicit_home), record)

    return record


def list_notification_schedules(
    include_cancelled: bool = False,
    explicit_home: str | Path | None = None,
) -> list[NotificationScheduleRecord]:
    records = [
        NotificationScheduleRecord.model_validate(record)
        for record in read_jsonl(notification_schedules_path(explicit_home))
    ]

    if not include_cancelled:
        records = [record for record in records if record.status != "cancelled"]

    return records


def list_notification_schedules_output(
    payload: NotificationListToolInput,
    explicit_home: str | Path | None = None,
) -> NotificationListToolOutput:
    return NotificationListToolOutput(
        notifications=list_notification_schedules(
            include_cancelled=payload.include_cancelled,
            explicit_home=explicit_home,
        )
    )


def get_notification_schedule(
    notification_id: str,
    explicit_home: str | Path | None = None,
) -> NotificationScheduleRecord | None:
    for record in reversed(list_notification_schedules(include_cancelled=True, explicit_home=explicit_home)):
        if record.id == notification_id:
            return record

    return None


def cancel_notification_schedule(
    notification_id: str,
    explicit_home: str | Path | None = None,
) -> NotificationScheduleRecord | None:
    path = notification_schedules_path(explicit_home)
    records = [
        NotificationScheduleRecord.model_validate(record)
        for record in read_jsonl(path)
    ]

    updated: list[NotificationScheduleRecord] = []
    cancelled: NotificationScheduleRecord | None = None
    now = utc_now_iso()

    for record in records:
        if record.id == notification_id and record.status != "cancelled":
            record = record.model_copy(update={"status": "cancelled", "updated_at": now})
            cancelled = record
        updated.append(record)

    if cancelled is None:
        return None

    write_jsonl(path, updated)
    return cancelled


def append_notification_outbox(
    record: NotificationOutboxRecord,
    explicit_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    append_jsonl(notification_outbox_path(explicit_home), record)
    return record


def list_notification_outbox(
    explicit_home: str | Path | None = None,
) -> list[NotificationOutboxRecord]:
    return [
        NotificationOutboxRecord.model_validate(record)
        for record in read_jsonl(notification_outbox_path(explicit_home))
    ]


def find_notification_outbox(
    schedule_id: str,
    due_at_utc: str,
    explicit_home: str | Path | None = None,
) -> NotificationOutboxRecord | None:
    for record in reversed(list_notification_outbox(explicit_home=explicit_home)):
        if record.schedule_id == schedule_id and record.due_at_utc == due_at_utc:
            return record

    return None


def replace_notification_outbox_record(
    replacement: NotificationOutboxRecord,
    explicit_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    path = notification_outbox_path(explicit_home)
    records = [
        NotificationOutboxRecord.model_validate(record)
        for record in read_jsonl(path)
    ]

    updated: list[NotificationOutboxRecord] = []
    replaced = False

    for record in records:
        if record.id == replacement.id:
            updated.append(replacement)
            replaced = True
        else:
            updated.append(record)

    if not replaced:
        updated.append(replacement)

    write_jsonl(path, updated)
    return replacement


def create_notification_outbox_once(
    schedule: NotificationScheduleRecord,
    due_at_utc: str,
    explicit_home: str | Path | None = None,
) -> tuple[NotificationOutboxRecord, bool]:
    existing = find_notification_outbox(
        schedule_id=schedule.id,
        due_at_utc=due_at_utc,
        explicit_home=explicit_home,
    )

    if existing is not None:
        return existing, False

    now = utc_now_iso()
    record = NotificationOutboxRecord(
        id=f"notif_outbox_{uuid4()}",
        schedule_id=schedule.id,
        due_at_utc=due_at_utc,
        status="pending",
        message=schedule.message,
        targets=schedule.targets,
        created_at=now,
        updated_at=now,
    )

    append_notification_outbox(record, explicit_home=explicit_home)
    return record, True


def mark_notification_outbox_sent(
    outbox_id: str,
    explicit_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    now = utc_now_iso()

    for record in list_notification_outbox(explicit_home=explicit_home):
        if record.id == outbox_id:
            updated = record.model_copy(
                update={
                    "status": "sent",
                    "updated_at": now,
                    "sent_at": now,
                    "error": None,
                }
            )
            return replace_notification_outbox_record(updated, explicit_home=explicit_home)

    raise ValueError(f"Notification outbox record not found: {outbox_id}")


def mark_notification_outbox_failed(
    outbox_id: str,
    error: str,
    explicit_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    now = utc_now_iso()

    for record in list_notification_outbox(explicit_home=explicit_home):
        if record.id == outbox_id:
            updated = record.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now,
                    "error": error,
                }
            )
            return replace_notification_outbox_record(updated, explicit_home=explicit_home)

    raise ValueError(f"Notification outbox record not found: {outbox_id}")


def append_notification_delivery(
    record: NotificationDeliveryRecord,
    explicit_home: str | Path | None = None,
) -> NotificationDeliveryRecord:
    append_jsonl(notification_deliveries_path(explicit_home), record)
    return record


def list_notification_deliveries(
    explicit_home: str | Path | None = None,
) -> list[NotificationDeliveryRecord]:
    return [
        NotificationDeliveryRecord.model_validate(record)
        for record in read_jsonl(notification_deliveries_path(explicit_home))
    ]


def create_notification_delivery_record(
    outbox_id: str,
    schedule_id: str,
    connector: str,
    status: str,
    attempt: int = 1,
    error: str | None = None,
    explicit_home: str | Path | None = None,
) -> NotificationDeliveryRecord:
    now = utc_now_iso()

    record = NotificationDeliveryRecord(
        id=f"notif_delivery_{uuid4()}",
        outbox_id=outbox_id,
        schedule_id=schedule_id,
        connector=connector,
        status=status,
        attempt=attempt,
        started_at=now,
        finished_at=now if status in {"sent", "failed"} else None,
        error=error,
    )

    append_notification_delivery(record, explicit_home=explicit_home)
    return record


# Compatibility wrappers for the original notification storage store API.
# New code may pass payload=/explicit_home=. Existing tests and MCP code may pass
# request=/safeplane_home=. Keep both valid.

_create_notification_schedule_impl = create_notification_schedule
_list_notification_schedules_impl = list_notification_schedules
_list_notification_schedules_output_impl = list_notification_schedules_output
_get_notification_schedule_impl = get_notification_schedule
_cancel_notification_schedule_impl = cancel_notification_schedule
_append_notification_outbox_impl = append_notification_outbox
_list_notification_outbox_impl = list_notification_outbox
_find_notification_outbox_impl = find_notification_outbox
_replace_notification_outbox_record_impl = replace_notification_outbox_record
_create_notification_outbox_once_impl = create_notification_outbox_once
_mark_notification_outbox_sent_impl = mark_notification_outbox_sent
_mark_notification_outbox_failed_impl = mark_notification_outbox_failed
_append_notification_delivery_impl = append_notification_delivery
_list_notification_deliveries_impl = list_notification_deliveries
_create_notification_delivery_record_impl = create_notification_delivery_record


def _home_arg(
    explicit_home: str | Path | None = None,
    safeplane_home: str | Path | None = None,
) -> str | Path | None:
    return explicit_home if explicit_home is not None else safeplane_home


def create_notification_schedule(
    payload: NotificationScheduleToolInput | None = None,
    explicit_home: str | Path | None = None,
    *,
    request: NotificationScheduleToolInput | None = None,
    safeplane_home: str | Path | None = None,
) -> NotificationScheduleRecord:
    selected_payload = payload if payload is not None else request
    if selected_payload is None:
        raise TypeError("create_notification_schedule requires payload= or request=")

    return _create_notification_schedule_impl(
        selected_payload,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def list_notification_schedules(
    include_cancelled: bool = False,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> list[NotificationScheduleRecord]:
    return _list_notification_schedules_impl(
        include_cancelled=include_cancelled,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def list_notification_schedules_output(
    payload: NotificationListToolInput | None = None,
    explicit_home: str | Path | None = None,
    *,
    request: NotificationListToolInput | None = None,
    safeplane_home: str | Path | None = None,
) -> NotificationListToolOutput:
    selected_payload = payload if payload is not None else request
    if selected_payload is None:
        raise TypeError("list_notification_schedules_output requires payload= or request=")

    return _list_notification_schedules_output_impl(
        selected_payload,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def get_notification_schedule(
    notification_id: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationScheduleRecord | None:
    return _get_notification_schedule_impl(
        notification_id=notification_id,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def cancel_notification_schedule(
    notification_id: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationScheduleRecord | None:
    return _cancel_notification_schedule_impl(
        notification_id=notification_id,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def append_notification_outbox(
    record: NotificationOutboxRecord,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    return _append_notification_outbox_impl(
        record,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def list_notification_outbox(
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> list[NotificationOutboxRecord]:
    return _list_notification_outbox_impl(
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def find_notification_outbox(
    schedule_id: str,
    due_at_utc: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord | None:
    return _find_notification_outbox_impl(
        schedule_id=schedule_id,
        due_at_utc=due_at_utc,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def replace_notification_outbox_record(
    replacement: NotificationOutboxRecord,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    return _replace_notification_outbox_record_impl(
        replacement,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def create_notification_outbox_once(
    schedule: NotificationScheduleRecord,
    due_at_utc: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> tuple[NotificationOutboxRecord, bool]:
    return _create_notification_outbox_once_impl(
        schedule=schedule,
        due_at_utc=due_at_utc,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def mark_notification_outbox_sent(
    outbox_id: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    return _mark_notification_outbox_sent_impl(
        outbox_id=outbox_id,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def mark_notification_outbox_failed(
    outbox_id: str,
    error: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    return _mark_notification_outbox_failed_impl(
        outbox_id=outbox_id,
        error=error,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def append_notification_delivery(
    record: NotificationDeliveryRecord,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationDeliveryRecord:
    return _append_notification_delivery_impl(
        record,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def list_notification_deliveries(
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> list[NotificationDeliveryRecord]:
    return _list_notification_deliveries_impl(
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def create_notification_delivery_record(
    outbox_id: str,
    schedule_id: str,
    connector: str,
    status: str,
    attempt: int = 1,
    error: str | None = None,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationDeliveryRecord:
    return _create_notification_delivery_record_impl(
        outbox_id=outbox_id,
        schedule_id=schedule_id,
        connector=connector,
        status=status,
        attempt=attempt,
        error=error,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


# notification scheduling compatibility overrides.
# Keep old notification storage calls valid:
# - create_notification_outbox_once(schedule=..., safeplane_home=...)
# - list_notification_schedules_output(include_cancelled=..., safeplane_home=...)
def create_notification_outbox_once(
    schedule: NotificationScheduleRecord,
    due_at_utc: str | None = None,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> tuple[NotificationOutboxRecord, bool]:
    selected_due_at_utc = due_at_utc or schedule.next_run_at_utc

    return _create_notification_outbox_once_impl(
        schedule=schedule,
        due_at_utc=selected_due_at_utc,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def list_notification_schedules_output(
    payload: NotificationListToolInput | None = None,
    explicit_home: str | Path | None = None,
    *,
    request: NotificationListToolInput | None = None,
    safeplane_home: str | Path | None = None,
    include_cancelled: bool | None = None,
) -> NotificationListToolOutput:
    selected_payload = payload if payload is not None else request
    if selected_payload is None:
        selected_payload = NotificationListToolInput(
            include_cancelled=bool(include_cancelled),
        )

    return NotificationListToolOutput(
        notifications=list_notification_schedules(
            include_cancelled=selected_payload.include_cancelled,
            explicit_home=_home_arg(explicit_home, safeplane_home),
        )
    )


# notification scheduling final compatibility overrides.
# Keep old calls valid:
# - mark_notification_outbox_sent(outbox=...)
# - create_notification_delivery_record(outbox=...)
_mark_notification_outbox_sent_current = mark_notification_outbox_sent
_create_notification_delivery_record_current = create_notification_delivery_record


def mark_notification_outbox_sent(
    outbox_id: str | None = None,
    explicit_home: str | Path | None = None,
    *,
    outbox: NotificationOutboxRecord | None = None,
    safeplane_home: str | Path | None = None,
) -> NotificationOutboxRecord:
    selected_outbox_id = outbox_id or (outbox.id if outbox is not None else None)
    if selected_outbox_id is None:
        raise TypeError("mark_notification_outbox_sent requires outbox_id= or outbox=")

    return _mark_notification_outbox_sent_current(
        outbox_id=selected_outbox_id,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def create_notification_delivery_record(
    outbox_id: str | None = None,
    schedule_id: str | None = None,
    connector: str = "log",
    status: str = "pending",
    attempt: int = 1,
    error: str | None = None,
    explicit_home: str | Path | None = None,
    *,
    outbox: NotificationOutboxRecord | None = None,
    safeplane_home: str | Path | None = None,
) -> NotificationDeliveryRecord:
    selected_outbox_id = outbox_id or (outbox.id if outbox is not None else None)
    selected_schedule_id = schedule_id or (outbox.schedule_id if outbox is not None else None)

    if selected_outbox_id is None:
        raise TypeError("create_notification_delivery_record requires outbox_id= or outbox=")

    if selected_schedule_id is None:
        raise TypeError("create_notification_delivery_record requires schedule_id= or outbox=")

    return _create_notification_delivery_record_current(
        outbox_id=selected_outbox_id,
        schedule_id=selected_schedule_id,
        connector=connector,
        status=status,
        attempt=attempt,
        error=error,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )


def expire_notification_schedule(
    notification_id: str,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> NotificationScheduleRecord | None:
    selected_home = _home_arg(explicit_home, safeplane_home)
    path = notification_schedules_path(selected_home)

    records = [
        NotificationScheduleRecord.model_validate(record)
        for record in read_jsonl(path)
    ]

    updated: list[NotificationScheduleRecord] = []
    expired: NotificationScheduleRecord | None = None
    now = utc_now_iso()

    for record in records:
        if record.id == notification_id and record.status == "active":
            record = record.model_copy(
                update={
                    "status": "expired",
                    "updated_at": now,
                }
            )
            expired = record

        updated.append(record)

    if expired is None:
        return None

    write_jsonl(path, updated)
    return expired


# Final lifecycle override.
# Normal notification lists should only show active schedules.
# include_cancelled=True means "include all non-deleted schedule records",
# including cancelled and expired, for audit/debug use.
def list_notification_schedules(
    include_cancelled: bool = False,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> list[NotificationScheduleRecord]:
    records = _list_notification_schedules_impl(
        include_cancelled=True,
        explicit_home=_home_arg(explicit_home, safeplane_home),
    )

    if include_cancelled:
        return records

    return [record for record in records if record.status == "active"]


def list_notification_schedules_output(
    payload: NotificationListToolInput | None = None,
    explicit_home: str | Path | None = None,
    *,
    request: NotificationListToolInput | None = None,
    safeplane_home: str | Path | None = None,
    include_cancelled: bool | None = None,
) -> NotificationListToolOutput:
    selected_payload = payload if payload is not None else request
    if selected_payload is None:
        selected_payload = NotificationListToolInput(
            include_cancelled=bool(include_cancelled),
        )

    return NotificationListToolOutput(
        notifications=list_notification_schedules(
            include_cancelled=selected_payload.include_cancelled,
            explicit_home=_home_arg(explicit_home, safeplane_home),
        )
    )


# notification delivery integration dynamic payload overrides.
# These override the previous compatibility definitions while keeping the same API.
def _notification_schedule_display_message(payload: NotificationScheduleToolInput) -> str:
    if payload.message:
        return payload.message

    if payload.payload is not None:
        if payload.payload.payload_type == "static":
            return payload.payload.message

        if payload.payload.payload_type == "calendar_digest":
            label = "today" if payload.payload.range == "today" else "next week"
            return payload.payload.title or f"Calendar digest: {label}"

    raise ValueError("Notification schedule requires message or payload")


def create_notification_schedule(
    payload: NotificationScheduleToolInput | None = None,
    explicit_home: str | Path | None = None,
    *,
    request: NotificationScheduleToolInput | None = None,
    safeplane_home: str | Path | None = None,
) -> NotificationScheduleRecord:
    selected_payload = payload if payload is not None else request
    if selected_payload is None:
        raise TypeError("create_notification_schedule requires payload= or request=")

    now = utc_now_iso()

    grace_seconds = selected_payload.grace_seconds
    if grace_seconds is None:
        grace_seconds = (
            DEFAULT_ONCE_GRACE_SECONDS
            if selected_payload.schedule.schedule_type == "once"
            else DEFAULT_RECURRING_GRACE_SECONDS
        )

    record = NotificationScheduleRecord(
        id=f"notif_sched_{uuid4()}",
        status="active",
        created_at=now,
        updated_at=now,
        message=_notification_schedule_display_message(selected_payload),
        payload=selected_payload.payload,
        schedule=selected_payload.schedule,
        targets=selected_payload.targets,
        grace_seconds=grace_seconds,
        next_run_at_utc=next_run_at_utc_for_schedule(selected_payload.schedule),
    )

    append_jsonl(notification_schedules_path(_home_arg(explicit_home, safeplane_home)), record)

    return record


def create_notification_outbox_once(
    schedule: NotificationScheduleRecord,
    due_at_utc: str | None = None,
    explicit_home: str | Path | None = None,
    *,
    safeplane_home: str | Path | None = None,
) -> tuple[NotificationOutboxRecord, bool]:
    selected_home = _home_arg(explicit_home, safeplane_home)
    selected_due_at_utc = due_at_utc or schedule.next_run_at_utc

    existing = find_notification_outbox(
        schedule_id=schedule.id,
        due_at_utc=selected_due_at_utc,
        explicit_home=selected_home,
    )

    if existing is not None:
        return existing, False

    from harness.notification_renderer import render_notification_message

    render_at_utc = datetime.fromisoformat(
        selected_due_at_utc.replace("Z", "+00:00")
    )
    if render_at_utc.tzinfo is None:
        render_at_utc = render_at_utc.replace(tzinfo=UTC)
    else:
        render_at_utc = render_at_utc.astimezone(UTC)

    try:
        rendered_message = render_notification_message(
            schedule,
            explicit_home=selected_home,
            now_utc=render_at_utc,
        )
    except Exception as exc:
        rendered_message = f"{schedule.message}\n\n[Notification render failed: {exc}]"

    now = utc_now_iso()
    record = NotificationOutboxRecord(
        id=f"notif_outbox_{uuid4()}",
        schedule_id=schedule.id,
        due_at_utc=selected_due_at_utc,
        status="pending",
        message=rendered_message,
        targets=schedule.targets,
        created_at=now,
        updated_at=now,
    )

    append_notification_outbox(record, explicit_home=selected_home)
    return record, True
