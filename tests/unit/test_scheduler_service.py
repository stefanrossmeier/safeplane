from datetime import UTC

from safeplane_scheduler.main import (
    notification_id_from_job_id,
    notification_job_id,
    parse_utc_iso,
)


def test_notification_job_id_roundtrip() -> None:
    notification_id = "notif_sched_123"
    job_id = notification_job_id(notification_id)

    assert job_id == "notification:notif_sched_123"
    assert notification_id_from_job_id(job_id) == notification_id
    assert notification_id_from_job_id("safeplane:reconcile") is None


def test_parse_utc_iso_accepts_z_suffix() -> None:
    parsed = parse_utc_iso("2026-07-13T07:00:00Z")

    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.isoformat() == "2026-07-13T07:00:00+00:00"


def test_parse_utc_iso_converts_offsets_to_utc() -> None:
    parsed = parse_utc_iso("2026-07-13T09:00:00+02:00")

    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2026-07-13T07:00:00+00:00"


def test_notification_due_creates_outbox_and_delivery(monkeypatch, tmp_path) -> None:
    from harness.notification_schemas import (
        NotificationOnceScheduleSpec,
        NotificationScheduleToolInput,
    )
    from harness.notification_store import (
        create_notification_schedule,
        list_notification_deliveries,
        list_notification_outbox,
    )
    from safeplane_scheduler.main import notification_due

    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_NOTIFICATION_CONNECTORS", "log")

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=NotificationScheduleToolInput(
            message="Call Anna",
            schedule=NotificationOnceScheduleSpec(
                run_at_local="2026-07-13T09:00:00",
                timezone="Europe/Berlin",
            ),
            targets=["all"],
        ),
    )

    notification_due(schedule.id)

    outbox_records = list_notification_outbox(safeplane_home=tmp_path)
    deliveries = list_notification_deliveries(safeplane_home=tmp_path)

    assert len(outbox_records) == 1
    assert outbox_records[0].status == "sent"
    assert outbox_records[0].message == "Call Anna"

    assert len(deliveries) == 1
    assert deliveries[0].connector == "log"
    assert deliveries[0].status == "sent"


def test_notification_due_is_idempotent_after_sent(monkeypatch, tmp_path) -> None:
    from harness.notification_schemas import (
        NotificationOnceScheduleSpec,
        NotificationScheduleToolInput,
    )
    from harness.notification_store import (
        create_notification_schedule,
        list_notification_deliveries,
        list_notification_outbox,
    )
    from safeplane_scheduler.main import notification_due

    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_NOTIFICATION_CONNECTORS", "log")

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=NotificationScheduleToolInput(
            message="Call Anna",
            schedule=NotificationOnceScheduleSpec(
                run_at_local="2026-07-13T09:00:00",
                timezone="Europe/Berlin",
            ),
            targets=["all"],
        ),
    )

    notification_due(schedule.id)
    notification_due(schedule.id)

    assert len(list_notification_outbox(safeplane_home=tmp_path)) == 1
    assert len(list_notification_deliveries(safeplane_home=tmp_path)) == 1


def test_notification_due_ignores_cancelled_schedule(monkeypatch, tmp_path) -> None:
    from harness.notification_schemas import (
        NotificationOnceScheduleSpec,
        NotificationScheduleToolInput,
    )
    from harness.notification_store import (
        cancel_notification_schedule,
        create_notification_schedule,
        list_notification_deliveries,
        list_notification_outbox,
    )
    from safeplane_scheduler.main import notification_due

    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_NOTIFICATION_CONNECTORS", "log")

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=NotificationScheduleToolInput(
            message="Call Anna",
            schedule=NotificationOnceScheduleSpec(
                run_at_local="2026-07-13T09:00:00",
                timezone="Europe/Berlin",
            ),
            targets=["all"],
        ),
    )

    cancel_notification_schedule(
        safeplane_home=tmp_path,
        notification_id=schedule.id,
    )

    notification_due(schedule.id)

    assert list_notification_outbox(safeplane_home=tmp_path) == []
    assert list_notification_deliveries(safeplane_home=tmp_path) == []


def test_daily_trigger_kwargs_for_record() -> None:
    from harness.notification_schemas import NotificationDailyTimeScheduleSpec, NotificationScheduleRecord
    from safeplane_scheduler.main import trigger_kwargs_for_record

    record = NotificationScheduleRecord(
        id="notif_sched_daily",
        status="active",
        created_at="2026-07-12T09:00:00Z",
        updated_at="2026-07-12T09:00:00Z",
        message="Daily",
        schedule=NotificationDailyTimeScheduleSpec(time_local="09:30", timezone="Europe/Berlin"),
        targets=["all"],
        grace_seconds=1800,
        next_run_at_utc="2026-07-13T07:30:00Z",
    )

    trigger_type, kwargs = trigger_kwargs_for_record(record)

    assert trigger_type == "cron"
    assert kwargs["hour"] == 9
    assert kwargs["minute"] == 30
    assert kwargs["timezone"] == "Europe/Berlin"


def test_weekly_trigger_kwargs_for_record() -> None:
    from harness.notification_schemas import NotificationScheduleRecord, NotificationWeeklyTimeScheduleSpec
    from safeplane_scheduler.main import trigger_kwargs_for_record

    record = NotificationScheduleRecord(
        id="notif_sched_weekly",
        status="active",
        created_at="2026-07-12T09:00:00Z",
        updated_at="2026-07-12T09:00:00Z",
        message="Weekly",
        schedule=NotificationWeeklyTimeScheduleSpec(
            day_of_week="sunday",
            time_local="18:00",
            timezone="Europe/Berlin",
        ),
        targets=["all"],
        grace_seconds=1800,
        next_run_at_utc="2026-07-12T16:00:00Z",
    )

    trigger_type, kwargs = trigger_kwargs_for_record(record)

    assert trigger_type == "cron"
    assert kwargs["day_of_week"] == "sun"
    assert kwargs["hour"] == 18
    assert kwargs["minute"] == 0


def test_weekdays_trigger_kwargs_for_record() -> None:
    from harness.notification_schemas import NotificationScheduleRecord, NotificationWeekdaysTimeScheduleSpec
    from safeplane_scheduler.main import trigger_kwargs_for_record

    record = NotificationScheduleRecord(
        id="notif_sched_weekdays",
        status="active",
        created_at="2026-07-12T09:00:00Z",
        updated_at="2026-07-12T09:00:00Z",
        message="Weekdays",
        schedule=NotificationWeekdaysTimeScheduleSpec(
            time_local="08:00",
            timezone="Europe/Berlin",
        ),
        targets=["all"],
        grace_seconds=1800,
        next_run_at_utc="2026-07-13T06:00:00Z",
    )

    trigger_type, kwargs = trigger_kwargs_for_record(record)

    assert trigger_type == "cron"
    assert kwargs["day_of_week"] == "mon-fri"
    assert kwargs["hour"] == 8
    assert kwargs["minute"] == 0


def test_notification_due_expires_one_time_schedule(monkeypatch, tmp_path) -> None:
    from harness.notification_schemas import (
        NotificationOnceScheduleSpec,
        NotificationScheduleToolInput,
    )
    from harness.notification_store import (
        create_notification_schedule,
        get_notification_schedule,
    )
    from safeplane_scheduler.main import notification_due

    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_NOTIFICATION_CONNECTORS", "log")

    schedule = create_notification_schedule(
        safeplane_home=tmp_path,
        request=NotificationScheduleToolInput(
            message="Call Anna",
            schedule=NotificationOnceScheduleSpec(
                run_at_local="2026-07-13T09:00:00",
                timezone="Europe/Berlin",
            ),
            targets=["all"],
        ),
    )

    notification_due(schedule.id)

    stored = get_notification_schedule(
        safeplane_home=tmp_path,
        notification_id=schedule.id,
    )

    assert stored is not None
    assert stored.status == "expired"
