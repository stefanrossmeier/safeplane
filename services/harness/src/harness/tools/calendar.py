from __future__ import annotations

import json
import shlex
from typing import Any

from harness.tools.runtime import ToolCommandError, ToolExecutionResult, ToolInvocation


class CalendarCommandError(ToolCommandError):
    pass


def consume_option(tokens: list[str], option: str, default: str) -> tuple[list[str], str]:
    remaining = list(tokens)

    if option not in remaining:
        return remaining, default

    index = remaining.index(option)

    if index + 1 >= len(remaining):
        raise CalendarCommandError(f"{option} requires a value")

    value = remaining[index + 1]
    del remaining[index:index + 2]
    return remaining, value


def parse_calendar_command(message: str) -> ToolInvocation | None:
    stripped = message.strip()

    if not stripped.lower().startswith("calendar "):
        return None

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        raise CalendarCommandError(f"Invalid calendar command quoting: {exc}") from exc

    if len(tokens) < 2 or tokens[0].lower() != "calendar":
        return None

    action = tokens[1].lower()
    rest = tokens[2:]

    if action == "list":
        if len(rest) < 2:
            raise CalendarCommandError(
                "Usage: calendar list day YYYY-MM-DD | calendar list week YYYY-MM-DD"
            )

        range_type = rest[0].lower()

        if range_type not in {"day", "week"}:
            raise CalendarCommandError("calendar list range must be day or week")

        date_value = rest[1]
        include_cancelled = "--include-cancelled" in rest
        rest_without_flag = [token for token in rest[2:] if token != "--include-cancelled"]
        rest_without_flag, timezone_name = consume_option(
            rest_without_flag,
            "--timezone",
            "Europe/Berlin",
        )

        if rest_without_flag:
            raise CalendarCommandError(
                f"Unexpected calendar list arguments: {' '.join(rest_without_flag)}"
            )

        return ToolInvocation(
            source="deterministic_command",
            adapter_id="calendar",
            server_id="calendar",
            tool_name="calendar_list",
            arguments={
                "range_type": range_type,
                "date": date_value,
                "timezone": timezone_name,
                "include_cancelled": include_cancelled,
            },
        )

    if action == "create":
        rest, timezone_name = consume_option(rest, "--timezone", "Europe/Berlin")
        rest, description = consume_option(rest, "--description", "")

        if len(rest) < 3:
            raise CalendarCommandError(
                "Usage: calendar create TITLE START_ISO END_ISO"
            )

        title = " ".join(rest[:-2]).strip()
        start = rest[-2]
        end = rest[-1]

        if not title:
            raise CalendarCommandError("calendar create requires a title")

        return ToolInvocation(
            source="deterministic_command",
            adapter_id="calendar",
            server_id="calendar",
            tool_name="calendar_create",
            arguments={
                "title": title,
                "start": start,
                "end": end,
                "timezone": timezone_name,
                "description": description,
            },
        )

    if action == "cancel":
        if len(rest) != 1:
            raise CalendarCommandError("Usage: calendar cancel cal_evt_...")

        return ToolInvocation(
            source="deterministic_command",
            adapter_id="calendar",
            server_id="calendar",
            tool_name="calendar_cancel",
            arguments={
                "event_id": rest[0],
            },
        )

    raise CalendarCommandError(f"Unsupported calendar command: {action}")


def format_event_line(event: dict[str, Any]) -> str:
    return (
        f"- {event['id']} {event['title']}: "
        f"{event['start']} -> {event['end']} "
        f"({event['status']})"
    )


def format_calendar_result(result: ToolExecutionResult) -> str:
    invocation = result.invocation
    structured_content = result.structured_content

    if invocation.tool_name == "calendar_create":
        event = structured_content["event"]
        return (
            f"Created calendar event {event['id']}.\n"
            f"{event['title']}\n"
            f"{event['start']} -> {event['end']}"
        )

    if invocation.tool_name == "calendar_cancel":
        event = structured_content["event"]
        return (
            f"Cancelled calendar event {event['id']}.\n"
            f"{event['title']}\n"
            f"{event['start']} -> {event['end']}"
        )

    if invocation.tool_name == "calendar_list":
        events = structured_content["events"]
        range_type = invocation.arguments["range_type"]
        date_value = invocation.arguments["date"]

        if not events:
            return f"No calendar events found for {range_type} {date_value}."

        lines = [
            f"Calendar events for {range_type} {date_value}:",
            *[format_event_line(event) for event in events],
        ]
        return "\n".join(lines)

    return json.dumps(structured_content, ensure_ascii=False, indent=2)
