from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class CalendarValidationError(ValueError):
    pass


class CalendarNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CalendarPaths:
    root: Path
    events_log: Path
    index: Path
    snapshots: Path
    backups: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def calendar_paths(safeplane_home: Path) -> CalendarPaths:
    root = safeplane_home / "data" / "calendar"
    return CalendarPaths(
        root=root,
        events_log=root / "events.jsonl",
        index=root / "index.json",
        snapshots=root / "snapshots",
        backups=root / "backups",
    )


def ensure_calendar_dirs(safeplane_home: Path) -> CalendarPaths:
    paths = calendar_paths(safeplane_home)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.snapshots.mkdir(parents=True, exist_ok=True)
    paths.backups.mkdir(parents=True, exist_ok=True)
    paths.events_log.touch(exist_ok=True)
    return paths


def create_event_id() -> str:
    return f"cal_evt_{uuid.uuid4()}"


def create_op_id() -> str:
    return f"cal_op_{uuid.uuid4()}"


def parse_aware_datetime(value: str, field_name: str) -> datetime:
    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CalendarValidationError(
            f"{field_name} must be an ISO 8601 datetime, got: {value}"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CalendarValidationError(
            f"{field_name} must include a timezone offset, got: {value}"
        )

    return parsed


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarValidationError(
            f"day must be an ISO date YYYY-MM-DD, got: {value}"
        ) from exc


def validate_event_input(
    *,
    title: str,
    start: str,
    end: str,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    if not title.strip():
        raise CalendarValidationError("title must not be empty")

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise CalendarValidationError(f"unknown timezone: {timezone_name}") from exc

    start_dt = parse_aware_datetime(start, "start")
    end_dt = parse_aware_datetime(end, "end")

    if start_dt >= end_dt:
        raise CalendarValidationError("start must be before end")

    return start_dt, end_dt


def append_log_row(safeplane_home: Path, row: dict[str, Any]) -> None:
    paths = ensure_calendar_dirs(safeplane_home)

    with paths.events_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log_rows(safeplane_home: Path) -> list[dict[str, Any]]:
    paths = ensure_calendar_dirs(safeplane_home)
    rows: list[dict[str, Any]] = []

    for line_number, line in enumerate(paths.events_log.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise CalendarValidationError(
                f"Invalid JSON in calendar event log at line {line_number}"
            ) from exc

        if not isinstance(row, dict):
            raise CalendarValidationError(
                f"Calendar event log row must be an object at line {line_number}"
            )

        rows.append(row)

    return rows


def replay_events(safeplane_home: Path) -> dict[str, dict[str, Any]]:
    current: dict[str, dict[str, Any]] = {}

    for row in read_log_rows(safeplane_home):
        op = row.get("op")

        if op == "calendar_event_created":
            event = row.get("event")
            if not isinstance(event, dict):
                raise CalendarValidationError("calendar_event_created row missing event object")
            current[event["id"]] = dict(event)

        elif op == "calendar_event_cancelled":
            event_id = row.get("event_id")
            if event_id in current:
                current[event_id]["status"] = "cancelled"
                current[event_id]["updated_at"] = row.get("ts") or utc_now()

        else:
            raise CalendarValidationError(f"Unknown calendar operation: {op}")

    return current


def write_index(safeplane_home: Path, events: dict[str, dict[str, Any]]) -> dict[str, Any]:
    paths = ensure_calendar_dirs(safeplane_home)

    index = {
        "generated_at": utc_now(),
        "event_count": len(events),
        "events": dict(sorted(events.items())),
    }

    temp_path = paths.index.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(paths.index)

    return index


def rebuild_index(safeplane_home: Path) -> dict[str, Any]:
    events = replay_events(safeplane_home)
    return write_index(safeplane_home, events)


def load_index(safeplane_home: Path) -> dict[str, Any]:
    paths = ensure_calendar_dirs(safeplane_home)

    if not paths.index.exists():
        return rebuild_index(safeplane_home)

    try:
        return json.loads(paths.index.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return rebuild_index(safeplane_home)


def current_events(safeplane_home: Path) -> dict[str, dict[str, Any]]:
    index = load_index(safeplane_home)
    events = index.get("events", {})

    if not isinstance(events, dict):
        return rebuild_index(safeplane_home)["events"]

    return events


def create_calendar_event(
    *,
    safeplane_home: Path,
    title: str,
    start: str,
    end: str,
    timezone_name: str = "Europe/Berlin",
    description: str = "",
) -> dict[str, Any]:
    start_dt, end_dt = validate_event_input(
        title=title,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )

    now = utc_now()
    event = {
        "id": create_event_id(),
        "title": title.strip(),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "timezone": timezone_name,
        "description": description,
        "status": "confirmed",
        "created_at": now,
        "updated_at": now,
    }

    row = {
        "op_id": create_op_id(),
        "op": "calendar_event_created",
        "ts": now,
        "event_id": event["id"],
        "event": event,
    }

    append_log_row(safeplane_home, row)
    rebuild_index(safeplane_home)
    return event


def get_calendar_event(
    *,
    safeplane_home: Path,
    event_id: str,
) -> dict[str, Any]:
    events = current_events(safeplane_home)

    if event_id not in events:
        raise CalendarNotFoundError(f"Calendar event not found: {event_id}")

    return events[event_id]


def cancel_calendar_event(
    *,
    safeplane_home: Path,
    event_id: str,
) -> dict[str, Any]:
    event = get_calendar_event(safeplane_home=safeplane_home, event_id=event_id)

    if event.get("status") == "cancelled":
        return event

    now = utc_now()
    row = {
        "op_id": create_op_id(),
        "op": "calendar_event_cancelled",
        "ts": now,
        "event_id": event_id,
    }

    append_log_row(safeplane_home, row)
    rebuild_index(safeplane_home)
    return get_calendar_event(safeplane_home=safeplane_home, event_id=event_id)


def event_overlaps_range(event: dict[str, Any], start_range: datetime, end_range: datetime) -> bool:
    event_start = parse_aware_datetime(str(event["start"]), "event.start")
    event_end = parse_aware_datetime(str(event["end"]), "event.end")

    event_start = event_start.astimezone(start_range.tzinfo)
    event_end = event_end.astimezone(start_range.tzinfo)

    return event_start < end_range and event_end > start_range


def list_events_between(
    *,
    safeplane_home: Path,
    start_range: datetime,
    end_range: datetime,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    events = current_events(safeplane_home).values()
    matching = []

    for event in events:
        if not include_cancelled and event.get("status") == "cancelled":
            continue

        if event_overlaps_range(event, start_range, end_range):
            matching.append(dict(event))

    return sorted(matching, key=lambda item: (item["start"], item["end"], item["title"]))


def list_events_for_day(
    *,
    safeplane_home: Path,
    day: str,
    timezone_name: str = "Europe/Berlin",
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    requested_day = parse_day(day)
    tz = ZoneInfo(timezone_name)

    start_range = datetime.combine(requested_day, time.min, tzinfo=tz)
    end_range = start_range + timedelta(days=1)

    return list_events_between(
        safeplane_home=safeplane_home,
        start_range=start_range,
        end_range=end_range,
        include_cancelled=include_cancelled,
    )


def list_events_for_week(
    *,
    safeplane_home: Path,
    week: str,
    timezone_name: str = "Europe/Berlin",
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    requested_day = parse_day(week)
    monday = requested_day - timedelta(days=requested_day.weekday())
    tz = ZoneInfo(timezone_name)

    start_range = datetime.combine(monday, time.min, tzinfo=tz)
    end_range = start_range + timedelta(days=7)

    return list_events_between(
        safeplane_home=safeplane_home,
        start_range=start_range,
        end_range=end_range,
        include_cancelled=include_cancelled,
    )


def create_snapshot(safeplane_home: Path) -> Path:
    paths = ensure_calendar_dirs(safeplane_home)
    rebuild_index(safeplane_home)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = paths.snapshots / f"calendar_snapshot_{stamp}.json"

    snapshot = {
        "created_at": utc_now(),
        "source_events_log": str(paths.events_log),
        "index": load_index(safeplane_home),
        "events_log_lines": paths.events_log.read_text(encoding="utf-8").splitlines(),
    }

    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return snapshot_path


def backup_calendar_store(safeplane_home: Path) -> Path:
    paths = ensure_calendar_dirs(safeplane_home)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = paths.backups / f"calendar_backup_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    shutil.copy2(paths.events_log, backup_dir / "events.jsonl")

    if paths.index.exists():
        shutil.copy2(paths.index, backup_dir / "index.json")

    return backup_dir


def cleanup_calendar_store(safeplane_home: Path) -> dict[str, Any]:
    snapshot_path = create_snapshot(safeplane_home)
    index = rebuild_index(safeplane_home)

    return {
        "status": "completed",
        "snapshot_path": str(snapshot_path),
        "event_count": index["event_count"],
        "index_generated_at": index["generated_at"],
    }


def reset_calendar_store(safeplane_home: Path) -> dict[str, Any]:
    paths = ensure_calendar_dirs(safeplane_home)
    backup_dir = backup_calendar_store(safeplane_home)

    paths.events_log.write_text("", encoding="utf-8")
    index = write_index(safeplane_home, {})

    return {
        "status": "completed",
        "backup_path": str(backup_dir),
        "event_count": index["event_count"],
        "index_generated_at": index["generated_at"],
    }


def calendar_store_report(safeplane_home: Path) -> dict[str, Any]:
    paths = ensure_calendar_dirs(safeplane_home)
    index = load_index(safeplane_home)

    return {
        "root": str(paths.root),
        "events_log": str(paths.events_log),
        "index": str(paths.index),
        "snapshots": str(paths.snapshots),
        "backups": str(paths.backups),
        "event_count": index.get("event_count", 0),
    }
