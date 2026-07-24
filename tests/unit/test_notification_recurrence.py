from datetime import UTC, datetime

from harness.notification_schemas import (
    NotificationDailyTimeScheduleSpec,
    NotificationWeeklyTimeScheduleSpec,
    NotificationWeekdaysTimeScheduleSpec,
)
from harness.notification_store import (
    next_daily_run_at_utc,
    next_run_at_utc_for_schedule,
    next_weekdays_run_at_utc,
    next_weekly_run_at_utc,
    parse_time_local,
)


def test_parse_time_local() -> None:
    parsed = parse_time_local("09:30")

    assert parsed.hour == 9
    assert parsed.minute == 30


def test_next_daily_run_today_when_time_is_future() -> None:
    now = datetime(2026, 7, 12, 7, 0, tzinfo=UTC)

    assert next_daily_run_at_utc("10:00", "Europe/Berlin", now_utc=now) == "2026-07-12T08:00:00Z"


def test_next_daily_run_tomorrow_when_time_has_passed() -> None:
    now = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)

    assert next_daily_run_at_utc("10:00", "Europe/Berlin", now_utc=now) == "2026-07-13T08:00:00Z"


def test_next_weekly_run_same_day_future_time() -> None:
    # 2026-07-12 is Sunday.
    now = datetime(2026, 7, 12, 7, 0, tzinfo=UTC)

    assert (
        next_weekly_run_at_utc("sunday", "10:00", "Europe/Berlin", now_utc=now)
        == "2026-07-12T08:00:00Z"
    )


def test_next_weekly_run_next_week_when_time_has_passed() -> None:
    # 2026-07-12 is Sunday.
    now = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)

    assert (
        next_weekly_run_at_utc("sunday", "10:00", "Europe/Berlin", now_utc=now)
        == "2026-07-19T08:00:00Z"
    )


def test_next_weekdays_skips_weekend() -> None:
    # Saturday, 2026-07-11 10:00 UTC.
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)

    assert next_weekdays_run_at_utc("09:00", "Europe/Berlin", now_utc=now) == "2026-07-13T07:00:00Z"


def test_next_run_dispatch_daily() -> None:
    now = datetime(2026, 7, 12, 7, 0, tzinfo=UTC)
    schedule = NotificationDailyTimeScheduleSpec(time_local="10:00", timezone="Europe/Berlin")

    assert next_run_at_utc_for_schedule(schedule, now_utc=now) == "2026-07-12T08:00:00Z"


def test_next_run_dispatch_weekly() -> None:
    now = datetime(2026, 7, 12, 7, 0, tzinfo=UTC)
    schedule = NotificationWeeklyTimeScheduleSpec(
        day_of_week="sunday",
        time_local="10:00",
        timezone="Europe/Berlin",
    )

    assert next_run_at_utc_for_schedule(schedule, now_utc=now) == "2026-07-12T08:00:00Z"


def test_next_run_dispatch_weekdays() -> None:
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    schedule = NotificationWeekdaysTimeScheduleSpec(time_local="09:00", timezone="Europe/Berlin")

    assert next_run_at_utc_for_schedule(schedule, now_utc=now) == "2026-07-13T07:00:00Z"
