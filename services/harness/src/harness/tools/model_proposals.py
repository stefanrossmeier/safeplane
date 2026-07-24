from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from harness.mcp_schemas import validate_tool_input
from harness.tools.runtime import ToolInvocation


class ModelProposalError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelFinalResponse(StrictModel):
    type: Literal["final"]
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class ModelToolCallResponse(StrictModel):
    type: Literal["tool_call"]
    server_id: str
    tool_name: str
    arguments: dict[str, Any]

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("server_id must not be empty")
        return value

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tool_name must not be empty")
        return value


class ParsedModelProposal:
    def __init__(
        self,
        *,
        type: Literal["final", "tool_call"],
        message: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> None:
        self.type = type
        self.message = message
        self.invocation = invocation


def strip_json_code_fence(content: str) -> str:
    stripped = content.strip()

    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()

    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()

    return stripped


def allowed_model_tools(contract: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}

    mcp = contract.get("mcp", {})
    model_servers = mcp.get("model_allowed_servers", mcp.get("allowed_servers", {}))
    for server_id, server_config in model_servers.items():
        tools = server_config.get("tools", [])
        result[str(server_id)] = {str(tool) for tool in tools}

    return result


def ensure_tool_is_allowed(
    *,
    contract: dict[str, Any],
    server_id: str,
    tool_name: str,
) -> None:
    allowed = allowed_model_tools(contract)

    if server_id not in allowed:
        raise ModelProposalError(f"server_id is not allowed for this workflow: {server_id}")

    if tool_name not in allowed[server_id]:
        raise ModelProposalError(
            f"tool_name is not allowed for server {server_id}: {tool_name}"
        )


def parse_model_proposal(
    *,
    content: str,
    contract: dict[str, Any],
) -> ParsedModelProposal:
    candidate = strip_json_code_fence(content)

    try:
        raw = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ModelProposalError(f"model response must be valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ModelProposalError("model response JSON must be an object")

    proposal_type = raw.get("type")

    try:
        if proposal_type == "final":
            final = ModelFinalResponse.model_validate(raw)
            return ParsedModelProposal(
                type="final",
                message=final.message,
            )

        if proposal_type == "tool_call":
            tool_call = ModelToolCallResponse.model_validate(raw)

            ensure_tool_is_allowed(
                contract=contract,
                server_id=tool_call.server_id,
                tool_name=tool_call.tool_name,
            )

            validate_tool_input(tool_call.tool_name, tool_call.arguments)

            return ParsedModelProposal(
                type="tool_call",
                invocation=ToolInvocation(
                    source="model_tool_proposal",
                    adapter_id=tool_call.server_id,
                    server_id=tool_call.server_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                ),
            )

    except ValidationError as exc:
        raise ModelProposalError(str(exc)) from exc
    except ValueError as exc:
        raise ModelProposalError(str(exc)) from exc

    raise ModelProposalError(
        "model response type must be either final or tool_call"
    )


def tool_instruction_block(contract: dict[str, Any]) -> str:
    allowed = allowed_model_tools(contract)

    if not allowed:
        return ""

    tool_lines: list[str] = []
    for server_id, tools in sorted(allowed.items()):
        for tool_name in sorted(tools):
            tool_lines.append(f"- server_id={server_id}, tool_name={tool_name}")

    first_server = sorted(allowed)[0]
    first_tool = sorted(allowed[first_server])[0]
    sections = [
        """You are running inside Safeplane's harness-owned agent runtime.

Important:
- You DO have access to the tools listed below.
- These are not provider-native tool calls.
- You must request tool execution by returning JSON.
- The Safeplane harness will validate your JSON, execute the tool, and give you the result.
- Use only tools listed under Available tools.

When a tool is needed, return ONLY a JSON object with this shape:
{
  "type": "tool_call",
  "server_id": "%s",
  "tool_name": "%s",
  "arguments": {}
}

When no tool is needed, return ONLY a JSON object with this shape:
{
  "type": "final",
  "message": "your final answer to the user"
}

Do not wrap JSON in Markdown.
Do not include explanations outside JSON.
Do not claim that a tool was executed until the harness gives you a tool result.

Available tools:
%s
""" % (first_server, first_tool, "\n".join(tool_lines))
    ]

    if "calendar" in allowed:
        sections.append(r'''Calendar tool argument schemas:

calendar_list:
{
  "range_type": "day" | "week",
  "date": "YYYY-MM-DD",
  "timezone": "IANA timezone, default Europe/Berlin if the user does not specify",
  "include_cancelled": false
}

calendar_create:
{
  "title": "event title",
  "start": "ISO-8601 datetime with timezone offset",
  "end": "ISO-8601 datetime with timezone offset",
  "timezone": "IANA timezone, default Europe/Berlin if the user does not specify",
  "description": ""
}

calendar_cancel:
{
  "event_id": "cal_evt_..."
}

Calendar examples:

User: Show my calendar for 2026-07-12.
Assistant:
{
  "type": "tool_call",
  "server_id": "calendar",
  "tool_name": "calendar_list",
  "arguments": {
    "range_type": "day",
    "date": "2026-07-12",
    "timezone": "Europe/Berlin",
    "include_cancelled": false
  }
}

User: Add a calendar event called Planning block on 2026-07-12 from 09:00 to 10:00 Europe/Berlin.
Assistant:
{
  "type": "tool_call",
  "server_id": "calendar",
  "tool_name": "calendar_create",
  "arguments": {
    "title": "Planning block",
    "start": "2026-07-12T09:00:00+02:00",
    "end": "2026-07-12T10:00:00+02:00",
    "timezone": "Europe/Berlin",
    "description": ""
  }
}
''')

    if "notification" in allowed:
        sections.append(r'''Notification tool argument schemas:

notification_schedule:
{
  "payload": {
    "payload_type": "static",
    "message": "reminder text"
  },
  "schedule": {
    "schedule_type": "once",
    "run_at_local": "ISO-8601 local datetime with timezone offset",
    "timezone": "IANA timezone, default Europe/Berlin if the user does not specify"
  },
  "targets": ["telegram"],
  "grace_seconds": 300
}

notification_list:
{
  "include_cancelled": false
}

notification_cancel:
{
  "notification_id": "notif_sched_..."
}

Recurring notification schedules:

daily_time:
{
  "payload": {
    "payload_type": "static",
    "message": "message text"
  },
  "schedule": {
    "schedule_type": "daily_time",
    "time_local": "07:30",
    "timezone": "Europe/Berlin"
  },
  "targets": ["telegram"],
  "grace_seconds": 300
}

weekdays_time:
{
  "payload": {
    "payload_type": "static",
    "message": "message text"
  },
  "schedule": {
    "schedule_type": "weekdays_time",
    "time_local": "07:30",
    "timezone": "Europe/Berlin"
  },
  "targets": ["telegram"],
  "grace_seconds": 300
}

weekly_time:
{
  "payload": {
    "payload_type": "static",
    "message": "message text"
  },
  "schedule": {
    "schedule_type": "weekly_time",
    "weekday": "sunday",
    "time_local": "18:00",
    "timezone": "Europe/Berlin"
  },
  "targets": ["telegram"],
  "grace_seconds": 300
}

Calendar digest notification payload:
{
  "payload": {
    "payload_type": "calendar_digest",
    "range": "today",
    "timezone": "Europe/Berlin",
    "title": "Today's calendar"
  },
  "schedule": {
    "schedule_type": "daily_time",
    "time_local": "07:30",
    "timezone": "Europe/Berlin"
  },
  "targets": ["telegram"],
  "grace_seconds": 300
}

Notification examples:

User: Remind me on 2026-07-12 at 14:00: call
Assistant:
{
  "type": "tool_call",
  "server_id": "notification",
  "tool_name": "notification_schedule",
  "arguments": {
    "payload": {
      "payload_type": "static",
      "message": "call"
    },
    "schedule": {
      "schedule_type": "once",
      "run_at_local": "2026-07-12T14:00:00+02:00",
      "timezone": "Europe/Berlin"
    },
    "targets": ["telegram"],
    "grace_seconds": 300
  }
}

User: Every morning at 07:30, send me today's calendar.
Assistant:
{
  "type": "tool_call",
  "server_id": "notification",
  "tool_name": "notification_schedule",
  "arguments": {
    "payload": {
      "payload_type": "calendar_digest",
      "range": "today",
      "timezone": "Europe/Berlin",
      "title": "Today's calendar"
    },
    "schedule": {
      "schedule_type": "daily_time",
      "time_local": "07:30",
      "timezone": "Europe/Berlin"
    },
    "targets": ["telegram"],
    "grace_seconds": 300
  }
}
''')

    if "dev-workspace" in allowed:
        sections.append(r'''Developer workspace tool argument schemas:

The repository root is `/workspace`. All paths are interpreted relative to it.
The workspace is read-only. Do not request patch application or arbitrary shell execution.

dev_workspace_list:
{
  "path": ".",
  "max_depth": 2,
  "max_entries": 200
}

dev_workspace_find:
{
  "pattern": "*.py",
  "path": ".",
  "max_results": 100
}

dev_workspace_grep:
{
  "query": "search text",
  "path": ".",
  "file_glob": "*.py",
  "case_sensitive": false,
  "max_results": 100
}

dev_workspace_read:
{
  "path": "relative/path.py",
  "start_line": 1,
  "max_lines": 200,
  "max_bytes": 65536
}

dev_git_metadata:
{
  "include_remote": true
}

dev_git_status:
{
  "include_untracked": true
}

dev_git_diff:
{
  "paths": [],
  "staged": false,
  "context_lines": 3,
  "max_bytes": 262144
}

dev_git_log:
{
  "max_commits": 20,
  "path": null
}

dev_git_show:
{
  "ref": "HEAD",
  "path": null,
  "max_bytes": 262144
}

dev_git_tracked_files:
{
  "path": ".",
  "max_results": 1000
}

dev_workspace_propose_patch:
{
  "summary": "focused description of the proposed change",
  "patch": "unified diff beginning with diff --git"
}

Developer workflow guidance:
- Inspect before proposing changes.
- Use list/find/grep/read and the narrow Git metadata tools as needed.
- Produce a unified diff only after you understand the relevant files.
- Store the final proposal through dev_workspace_propose_patch.
- The patch is an artifact only; it is not applied.
''')

    return "\n".join(section.strip() for section in sections if section.strip()) + "\n"
