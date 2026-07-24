from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.mcp_retry import McpRetryExhausted, validate_tool_call_with_retries  # noqa: E402


def valid_request() -> dict:
    return {
        "workflow_id": "assistant",
        "server_id": "calendar",
        "tool_name": "calendar_list",
        "arguments": {
            "range_type": "day",
            "date": "2026-07-12",
            "timezone": "Europe/Berlin",
        },
    }


def test_retry_accepts_later_valid_attempt() -> None:
    result = validate_tool_call_with_retries(
        [
            {
                "workflow_id": "assistant",
                "server_id": "calendar",
                "tool_name": "calendar_list",
                "arguments": {
                    "range_type": "month",
                    "date": "2026-07-12",
                },
            },
            valid_request(),
        ],
        max_retries=5,
    )

    assert result.attempts_used == 2
    assert result.request.tool_name == "calendar_list"
    assert len(result.errors) == 1


def test_retry_exhausts_after_initial_attempt_plus_retries() -> None:
    invalid = {
        "workflow_id": "assistant",
        "server_id": "calendar",
        "tool_name": "calendar_list",
        "arguments": {
            "range_type": "month",
            "date": "2026-07-12",
        },
    }

    with pytest.raises(McpRetryExhausted) as raised:
        validate_tool_call_with_retries(
            [invalid, invalid, invalid],
            max_retries=1,
        )

    assert len(raised.value.errors) == 2
