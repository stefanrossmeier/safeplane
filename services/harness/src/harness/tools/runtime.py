from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.mcp_broker import McpToolBroker


class ToolCommandError(ValueError):
    pass


@dataclass(frozen=True)
class ToolInvocation:
    source: str
    adapter_id: str
    server_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolExecutionResult:
    invocation: ToolInvocation
    server_id: str
    tool_name: str
    structured_content: dict[str, Any]
    is_error: bool


def execute_tool_invocation(
    *,
    invocation: ToolInvocation,
    workflow_id: str,
    session_id: str,
    turn: int,
    run_id: str,
    safeplane_home: Path,
    safeplane_config_path: Path,
    connector: str,
    agent_id: str | None = None,
) -> ToolExecutionResult:
    broker = McpToolBroker(
        config_path=safeplane_config_path,
        safeplane_home=safeplane_home,
    )

    response = broker.call_tool(
        {
            "workflow_id": workflow_id,
            "server_id": invocation.server_id,
            "tool_name": invocation.tool_name,
            "arguments": invocation.arguments,
            "session_id": session_id,
            "turn": turn,
            "run_id": run_id,
            "connector": connector,
            "agent_id": agent_id,
        }
    )

    return ToolExecutionResult(
        invocation=invocation,
        server_id=response.server_id,
        tool_name=response.tool_name,
        structured_content=response.structured_content,
        is_error=response.is_error,
    )
