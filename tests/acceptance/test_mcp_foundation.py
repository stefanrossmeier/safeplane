from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "mcp-servers/calendar-task/src"))

from calendar_task_mcp.main import handle_mcp_payload  # noqa: E402
from harness.mcp_broker import McpPermissionError, McpToolBroker  # noqa: E402


class CalendarMcpHttpHandler(BaseHTTPRequestHandler):
    safeplane_home: Path

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))

        response = handle_mcp_payload(
            payload,
            safeplane_home=type(self).safeplane_home,
        )

        body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def calendar_mcp_endpoint(tmp_path: Path) -> str:
    CalendarMcpHttpHandler.safeplane_home = tmp_path / "home"

    server = HTTPServer(("127.0.0.1", 0), CalendarMcpHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def write_mcp_foundation_config(tmp_path: Path, endpoint: str) -> Path:
    (tmp_path / "workflows" / "assistant").mkdir(parents=True)
    (tmp_path / "workflows" / "chat").mkdir(parents=True)

    (tmp_path / "safeplane.yaml").write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "calendar": {
                        "enabled": True,
                        "transport": "internal_http_jsonrpc",
                        "endpoint": endpoint,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / "workflows" / "assistant" / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "workflow_id": "assistant",
                "mcp": {
                    "max_tool_call_retries": 5,
                    "allowed_servers": {
                        "calendar": {
                            "tools": [
                                "calendar_list",
                                "calendar_create",
                                "calendar_cancel",
                            ]
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / "workflows" / "chat" / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "workflow_id": "chat",
                "mcp": {
                    "max_tool_call_retries": 5,
                    "allowed_servers": {},
                },
            }
        ),
        encoding="utf-8",
    )

    return tmp_path / "safeplane.yaml"


def test_harness_brokers_calendar_tools_and_logs_access(
    tmp_path: Path,
    calendar_mcp_endpoint: str,
) -> None:
    config_path = write_mcp_foundation_config(tmp_path, calendar_mcp_endpoint)
    safeplane_home = tmp_path / "home"

    broker = McpToolBroker(
        config_path=config_path,
        safeplane_home=safeplane_home,
    )

    created = broker.call_tool(
        {
            "workflow_id": "assistant",
            "server_id": "calendar",
            "tool_name": "calendar_create",
            "arguments": {
                "title": "Planning block",
                "start": "2026-07-12T09:00:00+02:00",
                "end": "2026-07-12T10:00:00+02:00",
                "timezone": "Europe/Berlin",
            },
            "connector": "cli",
            "session_id": "sess_test",
            "run_id": "run_test",
        }
    )

    event = created.structured_content["event"]
    event_id = event["id"]

    listed = broker.call_tool(
        {
            "workflow_id": "assistant",
            "server_id": "calendar",
            "tool_name": "calendar_list",
            "arguments": {
                "range_type": "day",
                "date": "2026-07-12",
                "timezone": "Europe/Berlin",
            },
        }
    )

    assert [item["id"] for item in listed.structured_content["events"]] == [event_id]

    cancelled = broker.call_tool(
        {
            "workflow_id": "assistant",
            "server_id": "calendar",
            "tool_name": "calendar_cancel",
            "arguments": {
                "event_id": event_id,
            },
        }
    )

    assert cancelled.structured_content["event"]["status"] == "cancelled"

    with pytest.raises(McpPermissionError):
        broker.call_tool(
            {
                "workflow_id": "chat",
                "server_id": "calendar",
                "tool_name": "calendar_list",
                "arguments": {
                    "range_type": "day",
                    "date": "2026-07-12",
                },
            }
        )

    access_log = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
    server_log = safeplane_home / "logs" / "mcp" / "calendar-task-mcp.jsonl"
    calendar_log = safeplane_home / "data" / "calendar" / "events.jsonl"

    assert access_log.exists()
    assert server_log.exists()
    assert calendar_log.exists()

    access_rows = [
        json.loads(line)
        for line in access_log.read_text(encoding="utf-8").splitlines()
    ]

    assert [row["decision"] for row in access_rows] == [
        "allowed",
        "allowed",
        "allowed",
        "denied",
    ]

    server_rows = [
        json.loads(line)
        for line in server_log.read_text(encoding="utf-8").splitlines()
    ]

    assert [row["tool_name"] for row in server_rows] == [
        "calendar_create",
        "calendar_list",
        "calendar_cancel",
    ]
