from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.tools.calendar import parse_calendar_command  # noqa: E402
from harness.tools.registry import parse_deterministic_tool_invocation  # noqa: E402


def test_calendar_adapter_outputs_generic_tool_invocation() -> None:
    invocation = parse_calendar_command(
        "calendar create Planning block 2026-07-12T09:00:00+02:00 2026-07-12T10:00:00+02:00"
    )

    assert invocation is not None
    assert invocation.source == "deterministic_command"
    assert invocation.adapter_id == "calendar"
    assert invocation.server_id == "calendar"
    assert invocation.tool_name == "calendar_create"
    assert invocation.arguments == {
        "title": "Planning block",
        "start": "2026-07-12T09:00:00+02:00",
        "end": "2026-07-12T10:00:00+02:00",
        "timezone": "Europe/Berlin",
        "description": "",
    }


def test_registry_only_uses_enabled_adapters() -> None:
    message = "calendar list day 2026-07-12"

    assert parse_deterministic_tool_invocation(
        message=message,
        enabled_adapters=[],
    ) is None

    invocation = parse_deterministic_tool_invocation(
        message=message,
        enabled_adapters=["calendar"],
    )

    assert invocation is not None
    assert invocation.tool_name == "calendar_list"
    assert invocation.arguments["date"] == "2026-07-12"


def test_developer_adapter_outputs_generic_read_only_invocation() -> None:
    invocation = parse_deterministic_tool_invocation(
        message='developer grep "Safeplane" src "*.py"',
        enabled_adapters=["developer"],
    )

    assert invocation is not None
    assert invocation.source == "deterministic_command"
    assert invocation.adapter_id == "developer"
    assert invocation.server_id == "dev-workspace"
    assert invocation.tool_name == "dev_workspace_grep"
    assert invocation.arguments == {
        "query": "Safeplane",
        "path": "src",
        "file_glob": "*.py",
        "case_sensitive": False,
        "max_results": 100,
    }
