from harness.mcp_schemas import validate_tool_input


def model_to_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    return value


def test_daily_calendar_digest_notification_tool_shape() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_schedule",
        {
            "payload": {
                "payload_type": "calendar_digest",
                "range": "today",
                "timezone": "Europe/Berlin",
                "title": "Today's calendar",
            },
            "schedule": {
                "schedule_type": "daily_time",
                "time_local": "07:30",
                "timezone": "Europe/Berlin",
            },
            "targets": ["all"],
        },
    ))

    assert payload["payload"]["payload_type"] == "calendar_digest"
    assert payload["payload"]["range"] == "today"
    assert payload["schedule"]["schedule_type"] == "daily_time"
    assert payload["schedule"]["time_local"] == "07:30"
    assert payload["message"] == "Today's calendar"


def test_weekday_agenda_notification_tool_shape() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_schedule",
        {
            "payload": {
                "payload_type": "calendar_digest",
                "range": "today",
                "timezone": "Europe/Berlin",
                "title": "Today's agenda",
            },
            "schedule": {
                "schedule_type": "weekdays_time",
                "time_local": "08:00",
                "timezone": "Europe/Berlin",
            },
            "targets": ["all"],
        },
    ))

    assert payload["payload"]["payload_type"] == "calendar_digest"
    assert payload["payload"]["range"] == "today"
    assert payload["schedule"]["schedule_type"] == "weekdays_time"
    assert payload["message"] == "Today's agenda"


def test_weekly_next_week_calendar_digest_notification_tool_shape() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_schedule",
        {
            "payload": {
                "payload_type": "calendar_digest",
                "range": "next_week",
                "timezone": "Europe/Berlin",
                "title": "Next week's calendar",
            },
            "schedule": {
                "schedule_type": "weekly_time",
                "day_of_week": "sunday",
                "time_local": "18:00",
                "timezone": "Europe/Berlin",
            },
            "targets": ["all"],
        },
    ))

    assert payload["payload"]["payload_type"] == "calendar_digest"
    assert payload["payload"]["range"] == "next_week"
    assert payload["schedule"]["schedule_type"] == "weekly_time"
    assert payload["schedule"]["day_of_week"] == "sunday"
    assert payload["message"] == "Next week's calendar"
