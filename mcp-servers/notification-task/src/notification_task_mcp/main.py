from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from harness.notification_schemas import (
    NotificationCancelToolInput,
    NotificationCancelToolOutput,
    NotificationListToolInput,
    NotificationReloadInfo,
    NotificationScheduleToolInput,
    NotificationScheduleToolOutput,
)
from harness.notification_store import (
    cancel_notification_schedule,
    create_notification_schedule,
    list_notification_schedules_output,
)


DEFAULT_SCHEDULER_URL = "http://scheduler:8080"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", "/data/safeplane")).expanduser()


def scheduler_url() -> str:
    return os.environ.get("SAFEPLANE_SCHEDULER_URL", DEFAULT_SCHEDULER_URL).rstrip("/")


def mcp_log_path() -> Path:
    return safeplane_home() / "logs" / "mcp" / "notification-task-mcp.jsonl"


def append_log(event: str, payload: dict[str, Any]) -> None:
    path = mcp_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": utc_now_iso(),
        "component": "notification-task-mcp",
        "event": event,
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


class JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


def mcp_success(request_id: str | int | None, structured_content: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(structured_content, ensure_ascii=False, sort_keys=True),
                }
            ],
            "structuredContent": structured_content,
            "isError": False,
        },
    }


def mcp_error(
    request_id: str | int | None,
    *,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "data": data or {},
        },
    }


def call_scheduler_reload(reason: str, schedule_id: str | None = None) -> NotificationReloadInfo:
    url = scheduler_url() + "/reload"
    body = json.dumps(
        {
            "reason": reason,
            "schedule_id": schedule_id,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            response_body = response.read().decode("utf-8")
            append_log(
                "scheduler_reload_succeeded",
                {
                    "reason": reason,
                    "schedule_id": schedule_id,
                    "status_code": response.status,
                    "response": response_body,
                },
            )
            return NotificationReloadInfo(status="ok", warning=None)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        warning = (
            "Notification was saved, but scheduler reload failed. "
            "It will be picked up by periodic reconciliation or scheduler restart."
        )
        append_log(
            "scheduler_reload_failed",
            {
                "reason": reason,
                "schedule_id": schedule_id,
                "error": str(exc),
            },
        )
        return NotificationReloadInfo(status="failed", warning=warning)


def handle_notification_schedule(arguments: dict[str, Any]) -> dict[str, Any]:
    request = NotificationScheduleToolInput.model_validate(arguments)
    record = create_notification_schedule(
        safeplane_home=safeplane_home(),
        request=request,
    )

    reload_info = call_scheduler_reload(
        reason="notification_schedule",
        schedule_id=record.id,
    )

    output = NotificationScheduleToolOutput(
        notification_id=record.id,
        status=record.status,
        next_run_at_utc=record.next_run_at_utc,
        reload=reload_info,
    )

    append_log(
        "notification_scheduled",
        {
            "notification_id": record.id,
            "next_run_at_utc": record.next_run_at_utc,
            "targets": record.targets,
            "reload_status": reload_info.status,
        },
    )

    return output.model_dump(mode="json")


def handle_notification_list(arguments: dict[str, Any]) -> dict[str, Any]:
    request = NotificationListToolInput.model_validate(arguments)
    output = list_notification_schedules_output(
        safeplane_home=safeplane_home(),
        include_cancelled=request.include_cancelled,
    )

    append_log(
        "notification_listed",
        {
            "include_cancelled": request.include_cancelled,
            "count": len(output.notifications),
        },
    )

    return output.model_dump(mode="json")


def handle_notification_cancel(arguments: dict[str, Any]) -> dict[str, Any]:
    request = NotificationCancelToolInput.model_validate(arguments)

    cancelled = cancel_notification_schedule(
        safeplane_home=safeplane_home(),
        notification_id=request.notification_id,
    )

    if cancelled is None:
        reload_info = NotificationReloadInfo(status="not_requested")
        status = "not_found"
    else:
        reload_info = call_scheduler_reload(
            reason="notification_cancel",
            schedule_id=request.notification_id,
        )
        status = "cancelled"

    output = NotificationCancelToolOutput(
        notification_id=request.notification_id,
        status=status,
        reload=reload_info,
    )

    append_log(
        "notification_cancelled",
        {
            "notification_id": request.notification_id,
            "status": status,
            "reload_status": reload_info.status,
        },
    )

    return output.model_dump(mode="json")


TOOL_HANDLERS = {
    "notification_schedule": handle_notification_schedule,
    "notification_list": handle_notification_list,
    "notification_cancel": handle_notification_cancel,
}


app = FastAPI(title="Safeplane Notification Task MCP")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
def mcp(request: JsonRpcRequest) -> dict[str, Any]:
    if request.method != "tools/call":
        return mcp_error(
            request.id,
            code=-32601,
            message=f"Unsupported method: {request.method}",
        )

    params = request.params or {}
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    if not isinstance(tool_name, str):
        return mcp_error(
            request.id,
            code=-32602,
            message="Missing tool name",
        )

    if not isinstance(arguments, dict):
        return mcp_error(
            request.id,
            code=-32602,
            message="Tool arguments must be an object",
        )

    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return mcp_error(
            request.id,
            code=-32602,
            message=f"Unsupported tool: {tool_name}",
        )

    try:
        result = handler(arguments)
    except Exception as exc:
        append_log(
            "tool_call_failed",
            {
                "tool_name": tool_name,
                "error": str(exc),
            },
        )
        return mcp_error(
            request.id,
            code=-32000,
            message=str(exc),
            data={"tool_name": tool_name},
        )

    return mcp_success(request.id, result)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "notification_task_mcp.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
