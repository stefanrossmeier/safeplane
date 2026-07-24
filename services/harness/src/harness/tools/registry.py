from __future__ import annotations

from typing import Callable

from harness.tools.calendar import format_calendar_result, parse_calendar_command
from harness.tools.developer import format_developer_result, parse_developer_command
from harness.tools.runtime import ToolExecutionResult, ToolInvocation


Parser = Callable[[str], ToolInvocation | None]
Formatter = Callable[[ToolExecutionResult], str]


PARSERS: dict[str, Parser] = {
    "calendar": parse_calendar_command,
    "developer": parse_developer_command,
}


FORMATTERS: dict[str, Formatter] = {
    "calendar": format_calendar_result,
    "developer": format_developer_result,
}


def enabled_deterministic_adapters(contract: dict) -> list[str]:
    configured = contract.get("deterministic_tools", {}).get("enabled", [])
    return [str(item) for item in configured]


def parse_deterministic_tool_invocation(
    *,
    message: str,
    enabled_adapters: list[str],
) -> ToolInvocation | None:
    for adapter_id in enabled_adapters:
        parser = PARSERS.get(adapter_id)

        if parser is None:
            continue

        invocation = parser(message)

        if invocation is not None:
            return invocation

    return None


def format_tool_result(result: ToolExecutionResult) -> str:
    formatter = FORMATTERS.get(result.invocation.adapter_id)

    if formatter is None:
        return str(result.structured_content)

    return formatter(result)
