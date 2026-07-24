from pathlib import Path

from harness.notification_schemas import (
    DEFAULT_ONCE_GRACE_SECONDS,
    NotificationOnceScheduleSpec,
    NotificationScheduleToolInput,
)
from harness.notification_store import (
    cancel_notification_schedule,
    create_notification_schedule,
    list_notification_schedules,
    local_time_to_utc_iso,
    notification_schedules_path,
)


def test_local_time_to_utc_iso_uses_timezone() -> None:
    assert (
        local_time_to_utc_iso("2026-07-13T09:00:00", "Europe/Berlin")
        == "2026-07-13T07:00:00Z"
    )


def test_create_notification_schedule_persists_record(tmp_path: Path) -> None:
    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["all"],
    )

    record = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )

    assert record.id.startswith("notif_sched_")
    assert record.status == "active"
    assert record.message == "Call Anna"
    assert record.targets == ["all"]
    assert record.grace_seconds == DEFAULT_ONCE_GRACE_SECONDS
    assert record.next_run_at_utc == "2026-07-13T07:00:00Z"

    path = notification_schedules_path(tmp_path)
    assert path.exists()
    assert "Call Anna" in path.read_text(encoding="utf-8")

    records = list_notification_schedules(safeplane_home=tmp_path)
    assert [item.id for item in records] == [record.id]


def test_cancel_notification_schedule_marks_record_cancelled(tmp_path: Path) -> None:
    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["telegram"],
    )

    record = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )

    cancelled = cancel_notification_schedule(
        safeplane_home=tmp_path,
        notification_id=record.id,
    )

    assert cancelled is not None
    assert cancelled.status == "cancelled"

    active_records = list_notification_schedules(safeplane_home=tmp_path)
    assert active_records == []

    all_records = list_notification_schedules(
        safeplane_home=tmp_path,
        include_cancelled=True,
    )
    assert len(all_records) == 1
    assert all_records[0].status == "cancelled"


def test_cancel_missing_notification_returns_none(tmp_path: Path) -> None:
    assert (
        cancel_notification_schedule(
            safeplane_home=tmp_path,
            notification_id="notif_sched_missing",
        )
        is None
    )


def test_create_notification_outbox_once_is_idempotent(tmp_path: Path) -> None:
    from harness.notification_store import (
        create_notification_outbox_once,
        list_notification_outbox,
    )

    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["log"],
    )

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )

    first, first_created = create_notification_outbox_once(
        safeplane_home=tmp_path,
        schedule=schedule,
    )
    second, second_created = create_notification_outbox_once(
        safeplane_home=tmp_path,
        schedule=schedule,
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert len(list_notification_outbox(safeplane_home=tmp_path)) == 1


def test_mark_notification_outbox_sent_updates_record(tmp_path: Path) -> None:
    from harness.notification_store import (
        create_notification_outbox_once,
        list_notification_outbox,
        mark_notification_outbox_sent,
    )

    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["log"],
    )

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )
    outbox, _ = create_notification_outbox_once(
        safeplane_home=tmp_path,
        schedule=schedule,
    )

    mark_notification_outbox_sent(
        safeplane_home=tmp_path,
        outbox=outbox,
    )

    records = list_notification_outbox(safeplane_home=tmp_path)
    assert len(records) == 1
    assert records[0].status == "sent"
    assert records[0].sent_at is not None


def test_create_notification_delivery_record_persists_delivery(tmp_path: Path) -> None:
    from harness.notification_store import (
        create_notification_delivery_record,
        create_notification_outbox_once,
        list_notification_deliveries,
    )

    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["log"],
    )

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )
    outbox, _ = create_notification_outbox_once(
        safeplane_home=tmp_path,
        schedule=schedule,
    )

    delivery = create_notification_delivery_record(
        safeplane_home=tmp_path,
        outbox=outbox,
        connector="log",
        status="sent",
    )

    assert delivery.id.startswith("notif_delivery_")

    deliveries = list_notification_deliveries(safeplane_home=tmp_path)
    assert len(deliveries) == 1
    assert deliveries[0].connector == "log"
    assert deliveries[0].status == "sent"


def test_expire_notification_schedule_marks_record_expired(tmp_path: Path) -> None:
    from harness.notification_store import (
        expire_notification_schedule,
        list_notification_schedules,
    )

    request = NotificationScheduleToolInput(
        message="Call Anna",
        schedule=NotificationOnceScheduleSpec(
            run_at_local="2026-07-13T09:00:00",
            timezone="Europe/Berlin",
        ),
        targets=["log"],
    )

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=request,
    )

    expired = expire_notification_schedule(
        safeplane_home=tmp_path,
        notification_id=schedule.id,
    )

    assert expired is not None
    assert expired.status == "expired"

    active = list_notification_schedules(
        safeplane_home=tmp_path,
        include_cancelled=False,
    )
    assert active == []

    all_records = list_notification_schedules(
        safeplane_home=tmp_path,
        include_cancelled=True,
    )
    assert all_records[0].status == "expired"
