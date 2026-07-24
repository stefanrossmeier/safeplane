from harness.mcp_schemas import model_to_dict, validate_tool_input, validate_tool_output


def test_notification_schedule_schema_registered() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_schedule",
        {
            "message": "Call Anna",
            "schedule": {
                "schedule_type": "once",
                "run_at_local": "2026-07-13T09:00:00",
                "timezone": "Europe/Berlin",
            },
            "targets": ["all"],
        },
    ))

    assert payload["message"] == "Call Anna"
    assert payload["targets"] == ["all"]


def test_notification_schedule_output_schema_registered() -> None:
    payload = model_to_dict(validate_tool_output(
        "notification_schedule",
        {
            "notification_id": "notif_sched_123",
            "status": "active",
            "next_run_at_utc": "2026-07-13T07:00:00Z",
            "reload": {
                "status": "ok",
                "warning": None,
            },
        },
    ))

    assert payload["notification_id"] == "notif_sched_123"
    assert payload["reload"]["status"] == "ok"


def test_notification_cancel_schema_registered() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_cancel",
        {
            "notification_id": "notif_sched_123",
        },
    ))

    assert payload["notification_id"] == "notif_sched_123"


def test_notification_schedule_calendar_digest_schema_registered() -> None:
    payload = model_to_dict(validate_tool_input(
        "notification_schedule",
        {
            "payload": {
                "payload_type": "calendar_digest",
                "range": "today",
                "timezone": "Europe/Berlin",
            },
            "schedule": {
                "schedule_type": "daily_time",
                "time_local": "07:30",
                "timezone": "Europe/Berlin",
            },
            "targets": ["all"],
        },
    ))

    assert payload["message"] == "Calendar digest: today"
    assert payload["payload"]["payload_type"] == "calendar_digest"
    assert payload["schedule"]["schedule_type"] == "daily_time"
