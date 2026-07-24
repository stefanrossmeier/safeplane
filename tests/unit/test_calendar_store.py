from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.calendar_store import (  # noqa: E402
    CalendarValidationError,
    cancel_calendar_event,
    create_calendar_event,
    create_snapshot,
    list_events_for_day,
    list_events_for_week,
    rebuild_index,
)


def test_calendar_create_writes_append_only_log_and_index(tmp_path: Path) -> None:
    event = create_calendar_event(
        safeplane_home=tmp_path,
        title="Planning block",
        start="2026-07-12T09:00:00+02:00",
        end="2026-07-12T10:00:00+02:00",
        timezone_name="Europe/Berlin",
    )

    assert event["id"].startswith("cal_evt_")
    assert event["status"] == "confirmed"

    log_path = tmp_path / "data" / "calendar" / "events.jsonl"
    index_path = tmp_path / "data" / "calendar" / "index.json"

    assert log_path.exists()
    assert index_path.exists()

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["op"] == "calendar_event_created"
    assert rows[0]["event_id"] == event["id"]

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert event["id"] in index["events"]


def test_calendar_lists_by_day_and_week(tmp_path: Path) -> None:
    event = create_calendar_event(
        safeplane_home=tmp_path,
        title="Planning block",
        start="2026-07-12T09:00:00+02:00",
        end="2026-07-12T10:00:00+02:00",
        timezone_name="Europe/Berlin",
    )

    day_events = list_events_for_day(
        safeplane_home=tmp_path,
        day="2026-07-12",
        timezone_name="Europe/Berlin",
    )

    week_events = list_events_for_week(
        safeplane_home=tmp_path,
        week="2026-07-07",
        timezone_name="Europe/Berlin",
    )

    assert [item["id"] for item in day_events] == [event["id"]]
    assert [item["id"] for item in week_events] == [event["id"]]


def test_calendar_rejects_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(CalendarValidationError, match="title must not be empty"):
        create_calendar_event(
            safeplane_home=tmp_path,
            title=" ",
            start="2026-07-12T09:00:00+02:00",
            end="2026-07-12T10:00:00+02:00",
        )

    with pytest.raises(CalendarValidationError, match="must include a timezone offset"):
        create_calendar_event(
            safeplane_home=tmp_path,
            title="No timezone",
            start="2026-07-12T09:00:00",
            end="2026-07-12T10:00:00+02:00",
        )

    with pytest.raises(CalendarValidationError, match="start must be before end"):
        create_calendar_event(
            safeplane_home=tmp_path,
            title="Bad range",
            start="2026-07-12T11:00:00+02:00",
            end="2026-07-12T10:00:00+02:00",
        )


def test_calendar_cancel_is_soft_delete(tmp_path: Path) -> None:
    event = create_calendar_event(
        safeplane_home=tmp_path,
        title="Planning block",
        start="2026-07-12T09:00:00+02:00",
        end="2026-07-12T10:00:00+02:00",
    )

    cancelled = cancel_calendar_event(
        safeplane_home=tmp_path,
        event_id=event["id"],
    )

    assert cancelled["status"] == "cancelled"

    visible = list_events_for_day(
        safeplane_home=tmp_path,
        day="2026-07-12",
    )

    with_cancelled = list_events_for_day(
        safeplane_home=tmp_path,
        day="2026-07-12",
        include_cancelled=True,
    )

    assert visible == []
    assert [item["id"] for item in with_cancelled] == [event["id"]]

    log_path = tmp_path / "data" / "calendar" / "events.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["op"] for row in rows] == [
        "calendar_event_created",
        "calendar_event_cancelled",
    ]


def test_calendar_index_rebuilds_from_event_log(tmp_path: Path) -> None:
    event = create_calendar_event(
        safeplane_home=tmp_path,
        title="Planning block",
        start="2026-07-12T09:00:00+02:00",
        end="2026-07-12T10:00:00+02:00",
    )

    index_path = tmp_path / "data" / "calendar" / "index.json"
    index_path.unlink()

    rebuilt = rebuild_index(tmp_path)

    assert event["id"] in rebuilt["events"]


def test_calendar_snapshot_contains_index_and_log(tmp_path: Path) -> None:
    create_calendar_event(
        safeplane_home=tmp_path,
        title="Planning block",
        start="2026-07-12T09:00:00+02:00",
        end="2026-07-12T10:00:00+02:00",
    )

    snapshot_path = create_snapshot(tmp_path)

    assert snapshot_path.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "index" in snapshot
    assert "events_log_lines" in snapshot
    assert len(snapshot["events_log_lines"]) == 1
