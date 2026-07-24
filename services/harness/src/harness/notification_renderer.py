from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from harness.notification_schemas import NotificationScheduleRecord


def safeplane_home(explicit_home: str | Path | None = None) -> Path:
    if explicit_home is not None:
        return Path(explicit_home).expanduser()

    return Path(os.environ.get("SAFEPLANE_HOME", "~/.safeplane")).expanduser()


def parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, dict):
        value = (
            value.get("dateTime")
            or value.get("datetime")
            or value.get("date")
            or value.get("value")
        )

    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
            parsed = datetime.combine(parsed_date, time.min)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)

    return parsed.astimezone(timezone)


def first_value(record: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]

    return None


def iter_calendar_records(explicit_home: str | Path | None = None) -> list[dict[str, Any]]:
    calendar_dir = safeplane_home(explicit_home) / "data" / "calendar"
    if not calendar_dir.exists():
        return []

    records: list[dict[str, Any]] = []

    for path in sorted(calendar_dir.glob("*.jsonl")):
        if not path.is_file():
            continue

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue

            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(value, dict):
                records.append(value)

    return records


def normalize_calendar_event(record: dict[str, Any], timezone: ZoneInfo) -> dict[str, Any] | None:
    status = str(record.get("status", "")).lower()
    if status in {"cancelled", "canceled", "deleted"}:
        return None

    title = first_value(
        record,
        ["title", "summary", "name", "message", "description"],
    ) or "Untitled event"

    start_value = first_value(
        record,
        ["start_at", "starts_at", "start_time", "start", "from", "begin_at", "begin"],
    )
    end_value = first_value(
        record,
        ["end_at", "ends_at", "end_time", "end", "to", "finish_at", "finish"],
    )

    start = parse_datetime(start_value, timezone)
    end = parse_datetime(end_value, timezone)

    if start is None:
        return None

    if end is None:
        end = start + timedelta(minutes=30)

    return {
        "id": record.get("id"),
        "title": str(title),
        "start": start,
        "end": end,
        "raw": record,
    }


def digest_window(
    digest_range: str,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    timezone = ZoneInfo(timezone_name)
    now_local = (now_utc or datetime.now(UTC)).astimezone(timezone)

    if digest_range == "today":
        start_date = now_local.date()
        end_date = start_date + timedelta(days=1)
        label = f"today ({start_date.isoformat()})"
    elif digest_range == "next_week":
        days_until_next_monday = (7 - now_local.weekday()) % 7
        if days_until_next_monday == 0:
            days_until_next_monday = 7

        start_date = now_local.date() + timedelta(days=days_until_next_monday)
        end_date = start_date + timedelta(days=7)
        label = f"next week ({start_date.isoformat()} to {(end_date - timedelta(days=1)).isoformat()})"
    else:
        raise ValueError(f"Unsupported calendar digest range: {digest_range}")

    return (
        datetime.combine(start_date, time.min, tzinfo=timezone),
        datetime.combine(end_date, time.min, tzinfo=timezone),
        label,
    )


def render_time_range(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')}"

    return f"{start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%Y-%m-%d %H:%M')}"


def render_calendar_digest(
    digest_range: str,
    timezone_name: str,
    explicit_home: str | Path | None = None,
    now_utc: datetime | None = None,
    title: str | None = None,
) -> str:
    timezone = ZoneInfo(timezone_name)
    window_start, window_end, label = digest_window(
        digest_range,
        timezone_name,
        now_utc=now_utc,
    )

    events = []
    for record in iter_calendar_records(explicit_home):
        event = normalize_calendar_event(record, timezone)
        if event is None:
            continue

        if event["start"] < window_end and event["end"] > window_start:
            events.append(event)

    events.sort(key=lambda item: (item["start"], item["end"], item["title"]))

    heading = title or f"Calendar digest for {label}"

    if not events:
        return f"{heading}\n\nNo calendar entries."

    lines = [heading, ""]

    for event in events:
        lines.append(f"- {render_time_range(event['start'], event['end'])}: {event['title']}")

    return "\n".join(lines)


def render_notification_message(
    schedule: NotificationScheduleRecord,
    explicit_home: str | Path | None = None,
    now_utc: datetime | None = None,
) -> str:
    payload = schedule.payload

    if payload is None:
        return schedule.message

    if payload.payload_type == "static":
        return payload.message

    if payload.payload_type == "calendar_digest":
        return render_calendar_digest(
            digest_range=payload.range,
            timezone_name=payload.timezone,
            explicit_home=explicit_home,
            now_utc=now_utc,
            title=payload.title,
        )

    return schedule.message
