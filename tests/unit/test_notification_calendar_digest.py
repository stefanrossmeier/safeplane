import json
from datetime import UTC, datetime
from pathlib import Path

from harness.notification_renderer import render_calendar_digest
from harness.notification_schemas import (
    NotificationOnceScheduleSpec,
    NotificationScheduleToolInput,
)
from harness.notification_store import (
    create_notification_outbox_once,
    create_notification_schedule,
)


def write_calendar_event(tmp_path: Path, event: dict) -> None:
    path = tmp_path / "data" / "calendar" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def test_render_calendar_digest_today_includes_matching_event(tmp_path: Path) -> None:
    write_calendar_event(
        tmp_path,
        {
            "id": "cal_1",
            "title": "Project sync",
            "start_at": "2026-07-12T11:00:00+02:00",
            "end_at": "2026-07-12T11:30:00+02:00",
            "status": "active",
        },
    )

    digest = render_calendar_digest(
        digest_range="today",
        timezone_name="Europe/Berlin",
        explicit_home=tmp_path,
        now_utc=datetime(2026, 7, 12, 7, 0, tzinfo=UTC),
    )

    assert "Project sync" in digest


def test_calendar_digest_outbox_renders_for_scheduled_occurrence(tmp_path: Path) -> None:
    write_calendar_event(
        tmp_path,
        {
            "id": "cal_1",
            "title": "Project sync",
            "start_at": "2026-07-12T11:00:00+02:00",
            "end_at": "2026-07-12T11:30:00+02:00",
            "status": "active",
        },
    )

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=NotificationScheduleToolInput(
            payload={
                "payload_type": "calendar_digest",
                "range": "today",
                "timezone": "Europe/Berlin",
                "title": "Today from calendar",
            },
            schedule=NotificationOnceScheduleSpec(
                run_at_local="2026-07-12T09:00:00",
                timezone="Europe/Berlin",
            ),
            targets=["log"],
        ),
    )

    outbox, created = create_notification_outbox_once(
        safeplane_home=tmp_path,
        schedule=schedule,
        due_at_utc="2026-07-12T07:00:00Z",
    )

    assert created is True
    assert "Today from calendar" in outbox.message
    assert "Project sync" in outbox.message


def test_notification_schedule_accepts_calendar_digest_payload_only() -> None:
    schedule = NotificationScheduleToolInput(
        payload={
            "payload_type": "calendar_digest",
            "range": "next_week",
            "timezone": "Europe/Berlin",
        },
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-12T09:00:00",
            timezone="Europe/Berlin",
        ),
    )

    assert schedule.message == "Calendar digest: next week"
    assert schedule.payload is not None
    assert schedule.payload.payload_type == "calendar_digest"
