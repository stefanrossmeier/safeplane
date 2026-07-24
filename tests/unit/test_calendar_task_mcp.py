from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "mcp-servers/calendar-task/src"))

from calendar_task_mcp.main import handle_mcp_payload  # noqa: E402


def test_calendar_task_mcp_create_and_list(tmp_path: Path) -> None:
    created_payload = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "calendar_create",
                "arguments": {
                    "title": "Planning block",
                    "start": "2026-07-12T09:00:00+02:00",
                    "end": "2026-07-12T10:00:00+02:00",
                    "timezone": "Europe/Berlin",
                },
            },
        },
        safeplane_home=tmp_path,
    )

    assert created_payload["result"]["isError"] is False

    event = created_payload["result"]["structuredContent"]["event"]
    assert event["id"].startswith("cal_evt_")

    listed_payload = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "calendar_list",
                "arguments": {
                    "range_type": "day",
                    "date": "2026-07-12",
                    "timezone": "Europe/Berlin",
                },
            },
        },
        safeplane_home=tmp_path,
    )

    assert listed_payload["result"]["isError"] is False
    assert [item["id"] for item in listed_payload["result"]["structuredContent"]["events"]] == [
        event["id"]
    ]

    assert (tmp_path / "data" / "calendar" / "events.jsonl").exists()
    assert (tmp_path / "logs" / "mcp" / "calendar-task-mcp.jsonl").exists()


def test_calendar_task_mcp_invalid_input_returns_tool_error(tmp_path: Path) -> None:
    payload = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "bad",
            "method": "tools/call",
            "params": {
                "name": "calendar_create",
                "arguments": {
                    "title": "Bad event",
                    "start": "2026-07-12T11:00:00+02:00",
                    "end": "2026-07-12T10:00:00+02:00",
                },
            },
        },
        safeplane_home=tmp_path,
    )

    assert payload["result"]["isError"] is True
    assert "start must be before end" in payload["result"]["structuredContent"]["error"]
