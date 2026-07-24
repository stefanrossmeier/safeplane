from __future__ import annotations

from pathlib import Path

import yaml

from harness.tools.model_proposals import allowed_model_tools, tool_instruction_block
from harness.workflow_registry import build_registry


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_developer_workflow_is_registered_and_documents_all_tools() -> None:
    config_path = REPO_ROOT / "safeplane.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    registry = build_registry(config, config_path)

    entry = registry["developer"]
    assert entry.workflow_id == "developer"
    assert entry.mcp["allowed_servers"]["dev-workspace"]["tools"]

    contract = yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )
    prompt = tool_instruction_block(contract)
    allowed = allowed_model_tools(contract)

    for server_id, tools in allowed.items():
        for tool_name in tools:
            assert f"server_id={server_id}, tool_name={tool_name}" in prompt
            assert f"\n{tool_name}:\n" in prompt

    assert "Calendar tool argument schemas:" not in prompt
    assert "Notification tool argument schemas:" not in prompt
    assert "The repository root is `/workspace`" in prompt


def test_developer_model_proposal_validates_read_tool_schema() -> None:
    from harness.tools.model_proposals import parse_model_proposal

    contract = yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )
    parsed = parse_model_proposal(
        content=(
            '{"type":"tool_call",'
            '"server_id":"dev-workspace",'
            '"tool_name":"dev_workspace_read",'
            '"arguments":{"path":"README.md","start_line":1,"max_lines":50,"max_bytes":4096}}'
        ),
        contract=contract,
    )

    assert parsed.type == "tool_call"
    assert parsed.invocation is not None
    assert parsed.invocation.server_id == "dev-workspace"
    assert parsed.invocation.tool_name == "dev_workspace_read"


def test_patch_apply_tool_is_approval_only_and_not_model_visible() -> None:
    contract = yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )
    allowed = allowed_model_tools(contract)
    prompt = tool_instruction_block(contract)

    assert "dev-workspace-apply" not in allowed
    assert "dev_workspace_apply_patch" not in prompt
    assert "dev-workspace-apply" not in contract["agents"]["documentation"]["allowed_mcp_servers"]
    assert contract["mcp"]["approval_required_servers"]["dev-workspace-apply"]["tools"] == [
        "dev_workspace_apply_patch"
    ]
