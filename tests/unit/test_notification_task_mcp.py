from pathlib import Path


def call_mcp(tool_name: str, arguments: dict, request_id: str = "test") -> dict:
    from notification_task_mcp.main import JsonRpcRequest, mcp

    request = JsonRpcRequest(
        jsonrpc="2.0",
        id=request_id,
        method="tools/call",
        params={
            "name": tool_name,
            "arguments": arguments,
        },
    )

    return mcp(request)


def test_notification_task_health(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    from notification_task_mcp.main import health

    assert health() == {"status": "ok"}


def test_notification_schedule_tool_persists_notification(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_SCHEDULER_URL", "http://127.0.0.1:9")

    payload = call_mcp(
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
        request_id="test-1",
    )

    result = payload["result"]["structuredContent"]

    assert result["notification_id"].startswith("notif_sched_")
    assert result["status"] == "active"
    assert result["next_run_at_utc"] == "2026-07-13T07:00:00Z"
    assert result["reload"]["status"] == "failed"

    schedules_path = tmp_path / "data" / "notifications" / "schedules.jsonl"
    assert schedules_path.exists()
    assert "Call Anna" in schedules_path.read_text(encoding="utf-8")


def test_notification_list_and_cancel_tools(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("SAFEPLANE_SCHEDULER_URL", "http://127.0.0.1:9")

    create_payload = call_mcp(
        "notification_schedule",
        {
            "message": "Call Anna",
            "schedule": {
                "schedule_type": "once",
                "run_at_local": "2026-07-13T09:00:00",
                "timezone": "Europe/Berlin",
            },
            "targets": ["telegram"],
        },
        request_id="test-create",
    )

    notification_id = create_payload["result"]["structuredContent"]["notification_id"]

    list_payload = call_mcp(
        "notification_list",
        {
            "include_cancelled": False,
        },
        request_id="test-list",
    )

    listed = list_payload["result"]["structuredContent"]["notifications"]
    assert len(listed) == 1
    assert listed[0]["id"] == notification_id

    cancel_payload = call_mcp(
        "notification_cancel",
        {
            "notification_id": notification_id,
        },
        request_id="test-cancel",
    )

    cancel_result = cancel_payload["result"]["structuredContent"]
    assert cancel_result["notification_id"] == notification_id
    assert cancel_result["status"] == "cancelled"
    assert cancel_result["reload"]["status"] == "failed"

    list_after_cancel_payload = call_mcp(
        "notification_list",
        {
            "include_cancelled": False,
        },
        request_id="test-list-after-cancel",
    )

    listed = list_after_cancel_payload["result"]["structuredContent"]["notifications"]
    assert listed == []


def test_notification_cancel_missing_is_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    payload = call_mcp(
        "notification_cancel",
        {
            "notification_id": "notif_sched_missing",
        },
        request_id="test-missing",
    )

    result = payload["result"]["structuredContent"]
    assert result["notification_id"] == "notif_sched_missing"
    assert result["status"] == "not_found"
    assert result["reload"]["status"] == "not_requested"


def test_notification_task_rejects_unknown_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    from notification_task_mcp.main import JsonRpcRequest, mcp

    payload = mcp(
        JsonRpcRequest(
            jsonrpc="2.0",
            id="test-unknown",
            method="tools/call",
            params={
                "name": "unknown_tool",
                "arguments": {},
            },
        )
    )

    assert payload["error"]["code"] == -32602
    assert "Unsupported tool" in payload["error"]["message"]
