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

from harness.mcp_broker import (  # noqa: E402
    McpPermissionError,
    McpToolBroker,
    McpToolExecutionError,
    McpValidationError,
)


class FakeMcpHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []
    structured_content: dict[str, Any] = {"events": []}
    is_error: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))

        type(self).calls.append(payload)

        response = {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "structuredContent": type(self).structured_content,
                "isError": type(self).is_error,
            },
        }

        body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_mcp_server() -> str:
    FakeMcpHandler.calls = []
    FakeMcpHandler.structured_content = {"events": []}
    FakeMcpHandler.is_error = False

    server = HTTPServer(("127.0.0.1", 0), FakeMcpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def write_config(tmp_path: Path, endpoint: str) -> Path:
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


def test_broker_allows_declared_assistant_tool_and_writes_log(
    tmp_path: Path,
    fake_mcp_server: str,
) -> None:
    config_path = write_config(tmp_path, fake_mcp_server)
    safeplane_home = tmp_path / "home"

    broker = McpToolBroker(
        config_path=config_path,
        safeplane_home=safeplane_home,
    )

    response = broker.call_tool(
        {
            "workflow_id": "assistant",
            "server_id": "calendar",
            "tool_name": "calendar_list",
            "arguments": {
                "range_type": "day",
                "date": "2026-07-12",
                "timezone": "Europe/Berlin",
            },
            "connector": "cli",
        }
    )

    assert response.structured_content == {"events": []}
    assert len(FakeMcpHandler.calls) == 1

    log_path = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert rows[-1]["decision"] == "allowed"
    assert rows[-1]["workflow_id"] == "assistant"
    assert rows[-1]["tool_name"] == "calendar_list"
    assert rows[-1]["input_schema_valid"] is True
    assert rows[-1]["output_schema_valid"] is True


def test_broker_denies_undeclared_chat_tool_without_calling_server(
    tmp_path: Path,
    fake_mcp_server: str,
) -> None:
    config_path = write_config(tmp_path, fake_mcp_server)
    safeplane_home = tmp_path / "home"

    broker = McpToolBroker(
        config_path=config_path,
        safeplane_home=safeplane_home,
    )

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

    assert FakeMcpHandler.calls == []

    log_path = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert rows[-1]["decision"] == "denied"
    assert rows[-1]["reason"] == "permission_denied"


def test_broker_rejects_invalid_input_before_calling_server(
    tmp_path: Path,
    fake_mcp_server: str,
) -> None:
    config_path = write_config(tmp_path, fake_mcp_server)
    safeplane_home = tmp_path / "home"

    broker = McpToolBroker(
        config_path=config_path,
        safeplane_home=safeplane_home,
    )

    with pytest.raises(McpValidationError):
        broker.call_tool(
            {
                "workflow_id": "assistant",
                "server_id": "calendar",
                "tool_name": "calendar_list",
                "arguments": {
                    "range_type": "month",
                    "date": "2026-07-12",
                },
            }
        )

    assert FakeMcpHandler.calls == []

    log_path = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert rows[-1]["decision"] == "rejected"
    assert rows[-1]["reason"] == "schema_validation_failed"


def test_broker_detects_invalid_output_schema(
    tmp_path: Path,
    fake_mcp_server: str,
) -> None:
    config_path = write_config(tmp_path, fake_mcp_server)
    safeplane_home = tmp_path / "home"

    FakeMcpHandler.structured_content = {"events": "not-a-list"}

    broker = McpToolBroker(
        config_path=config_path,
        safeplane_home=safeplane_home,
    )

    with pytest.raises(McpValidationError):
        broker.call_tool(
            {
                "workflow_id": "assistant",
                "server_id": "calendar",
                "tool_name": "calendar_list",
                "arguments": {
                    "range_type": "day",
                    "date": "2026-07-12",
                },
            }
        )

    log_path = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert rows[-1]["decision"] == "rejected"
