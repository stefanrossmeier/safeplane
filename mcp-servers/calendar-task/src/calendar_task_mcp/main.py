from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI

from harness.calendar_store import (
    CalendarNotFoundError,
    CalendarValidationError,
    cancel_calendar_event,
    create_calendar_event,
    list_events_for_day,
    list_events_for_week,
)
from harness.mcp_schemas import (
    model_to_dict,
    validate_tool_input,
    validate_tool_output,
)


app = FastAPI(title="Safeplane Calendar Task MCP")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", str(Path.home() / ".safeplane"))).expanduser()


def server_log_path(safeplane_home: Optional[Path] = None) -> Path:
    root = safeplane_home or default_safeplane_home()
    return root / "logs" / "mcp" / "calendar-task-mcp.jsonl"


def write_server_log(row: Dict[str, Any], *, safeplane_home: Optional[Path] = None) -> None:
    path = server_log_path(safeplane_home)
    path.parent.mkdir(parents=True, exist_ok=True)

    enriched = {
        "ts": row.get("ts") or utc_now(),
        **row,
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(enriched, ensure_ascii=False) + "\n")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
def mcp_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    return handle_mcp_payload(payload)


def handle_mcp_payload(
    payload: Dict[str, Any],
    *,
    safeplane_home: Optional[Path] = None,
) -> Dict[str, Any]:
    request_id = payload.get("id")

    if payload.get("method") != "tools/call":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": "Unsupported method",
            },
        }

    params = payload.get("params") or {}

    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": "params must be an object",
            },
        }

    name = params.get("name")
    arguments = params.get("arguments") or {}

    try:
        structured_content = call_tool(
            tool_name=str(name),
            arguments=arguments,
            safeplane_home=safeplane_home,
        )

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": structured_content,
                "isError": False,
            },
        }

    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": {
                    "error": str(exc),
                },
                "isError": True,
            },
        }


def call_tool(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    safeplane_home: Optional[Path] = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    root = safeplane_home or default_safeplane_home()

    try:
        validated_input = validate_tool_input(tool_name, arguments)
        data = model_to_dict(validated_input)

        if tool_name == "calendar_list":
            if data["range_type"] == "day":
                events = list_events_for_day(
                    safeplane_home=root,
                    day=data["date"],
                    timezone_name=data["timezone"],
                    include_cancelled=data["include_cancelled"],
                )
            else:
                events = list_events_for_week(
                    safeplane_home=root,
                    week=data["date"],
                    timezone_name=data["timezone"],
                    include_cancelled=data["include_cancelled"],
                )

            structured_content = {"events": events}

        elif tool_name == "calendar_create":
            event = create_calendar_event(
                safeplane_home=root,
                title=data["title"],
                start=data["start"],
                end=data["end"],
                timezone_name=data["timezone"],
                description=data.get("description", ""),
            )

            structured_content = {"event": event}

        elif tool_name == "calendar_cancel":
            event = cancel_calendar_event(
                safeplane_home=root,
                event_id=data["event_id"],
            )

            structured_content = {"event": event}

        else:
            raise ValueError(f"Unsupported tool: {tool_name}")

        validated_output = validate_tool_output(tool_name, structured_content)

        write_server_log(
            {
                "event": "mcp_tool_executed",
                "server_id": "calendar",
                "tool_name": tool_name,
                "status": "completed",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "safeplane_enforcement": "calendar_store_boundary",
            },
            safeplane_home=root,
        )

        return model_to_dict(validated_output)

    except (CalendarValidationError, CalendarNotFoundError, ValueError) as exc:
        write_server_log(
            {
                "event": "mcp_tool_executed",
                "server_id": "calendar",
                "tool_name": tool_name,
                "status": "failed",
                "error": str(exc),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "safeplane_enforcement": "calendar_store_boundary",
            },
            safeplane_home=root,
        )
        raise
