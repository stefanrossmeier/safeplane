from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.tools.model_proposals import (  # noqa: E402
    ModelProposalError,
    parse_model_proposal,
)


CONTRACT = {
    "mcp": {
        "allowed_servers": {
            "calendar": {
                "tools": [
                    "calendar_list",
                    "calendar_create",
                    "calendar_cancel",
                ]
            }
        }
    }
}


def test_parse_final_model_response() -> None:
    parsed = parse_model_proposal(
        content='{"type":"final","message":"Hello"}',
        contract=CONTRACT,
    )

    assert parsed.type == "final"
    assert parsed.message == "Hello"


def test_parse_tool_call_to_generic_invocation() -> None:
    parsed = parse_model_proposal(
        content=(
            '{"type":"tool_call",'
            '"server_id":"calendar",'
            '"tool_name":"calendar_list",'
            '"arguments":{"range_type":"day","date":"2026-07-12","timezone":"Europe/Berlin"}}'
        ),
        contract=CONTRACT,
    )

    assert parsed.type == "tool_call"
    assert parsed.invocation is not None
    assert parsed.invocation.source == "model_tool_proposal"
    assert parsed.invocation.adapter_id == "calendar"
    assert parsed.invocation.server_id == "calendar"
    assert parsed.invocation.tool_name == "calendar_list"
    assert parsed.invocation.arguments["date"] == "2026-07-12"


def test_rejects_unallowed_tool() -> None:
    with pytest.raises(ModelProposalError, match="tool_name is not allowed"):
        parse_model_proposal(
            content=(
                '{"type":"tool_call",'
                '"server_id":"calendar",'
                '"tool_name":"calendar_reset",'
                '"arguments":{}}'
            ),
            contract=CONTRACT,
        )


def test_rejects_schema_invalid_arguments() -> None:
    with pytest.raises(ModelProposalError, match="range_type"):
        parse_model_proposal(
            content=(
                '{"type":"tool_call",'
                '"server_id":"calendar",'
                '"tool_name":"calendar_list",'
                '"arguments":{"range_type":"month","date":"2026-07-12"}}'
            ),
            contract=CONTRACT,
        )


def test_rejects_non_json_response() -> None:
    with pytest.raises(ModelProposalError, match="valid JSON"):
        parse_model_proposal(
            content="I will create the event.",
            contract=CONTRACT,
        )
