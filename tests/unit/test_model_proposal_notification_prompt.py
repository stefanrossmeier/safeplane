from pathlib import Path

import yaml

from harness.tools.model_proposals import allowed_model_tools, tool_instruction_block


REPO_ROOT = Path(__file__).resolve().parents[2]


def assistant_contract() -> dict:
    return {
        "mcp": {
            "allowed_servers": {
                "calendar": {
                    "tools": [
                        "calendar_list",
                        "calendar_create",
                        "calendar_cancel",
                    ],
                },
                "notification": {
                    "tools": [
                        "notification_schedule",
                        "notification_list",
                        "notification_cancel",
                    ],
                },
            },
        },
    }


def test_tool_instruction_block_includes_allowed_notification_tools() -> None:
    message = tool_instruction_block(assistant_contract())

    assert "server_id=notification, tool_name=notification_schedule" in message
    assert "server_id=notification, tool_name=notification_list" in message
    assert "server_id=notification, tool_name=notification_cancel" in message


def test_tool_instruction_block_includes_notification_schemas_and_examples() -> None:
    message = tool_instruction_block(assistant_contract())

    assert "Notification tool argument schemas:" in message
    assert "notification_schedule:" in message
    assert '"payload_type": "static"' in message
    assert '"schedule_type": "once"' in message
    assert '"targets": ["telegram"]' in message
    assert "Remind me on 2026-07-12 at 14:00: call" in message
    assert "Remind me today at 14:00: call" not in message
    assert '"tool_name": "notification_schedule"' in message


def test_tool_instruction_block_keeps_calendar_tools() -> None:
    message = tool_instruction_block(assistant_contract())

    assert "server_id=calendar, tool_name=calendar_list" in message
    assert "server_id=calendar, tool_name=calendar_create" in message
    assert "server_id=calendar, tool_name=calendar_cancel" in message
    assert "Calendar tool argument schemas:" in message
    assert "calendar_list:" in message
    assert "calendar_create:" in message
    assert "calendar_cancel:" in message


def test_actual_assistant_contract_documents_every_allowed_tool() -> None:
    contract_path = REPO_ROOT / "workflows/assistant/workflow.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    allowed = allowed_model_tools(contract)
    message = tool_instruction_block(contract)

    assert allowed, "assistant workflow must declare at least one allowed MCP tool"

    missing_available_lines: list[str] = []
    missing_schema_guidance: list[str] = []

    for server_id, tools in sorted(allowed.items()):
        for tool_name in sorted(tools):
            available_line = f"server_id={server_id}, tool_name={tool_name}"
            schema_marker = f"\n{tool_name}:\n"

            if available_line not in message:
                missing_available_lines.append(available_line)

            if schema_marker not in message:
                missing_schema_guidance.append(tool_name)

    assert not missing_available_lines, (
        "assistant runtime prompt omitted allowed tool lines: "
        + ", ".join(missing_available_lines)
    )
    assert not missing_schema_guidance, (
        "assistant runtime prompt omitted schema guidance for allowed tools: "
        + ", ".join(missing_schema_guidance)
    )
