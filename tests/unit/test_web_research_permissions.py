from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.mcp_broker import McpPermissionError, McpToolBroker  # noqa: E402


def _write_config(tmp_path: Path) -> Path:
    (tmp_path / "workflows" / "developer").mkdir(parents=True)
    (tmp_path / "safeplane.yaml").write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "web-research": {
                        "enabled": True,
                        "transport": "internal_http_jsonrpc",
                        "endpoint": "http://web-research-agent:8080/mcp",
                        "forward_context": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "developer" / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "workflow_id": "developer",
                "agents": {
                    "analysis": {
                        "allowed_mcp_servers": {
                            "web-research": {"tools": ["web_research_clarify"]}
                        }
                    },
                    "planning": {"allowed_mcp_servers": {}},
                    "implementation": {"allowed_mcp_servers": {}},
                },
                "mcp": {
                    "allowed_servers": {
                        "web-research": {"tools": ["web_research_clarify"]}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "safeplane.yaml"


def test_only_analysis_agent_receives_web_research_capability(tmp_path: Path) -> None:
    broker = McpToolBroker(config_path=_write_config(tmp_path), safeplane_home=tmp_path / "home")

    assert (
        broker.ensure_workflow_tool_allowed(
            workflow_id="developer",
            server_id="web-research",
            tool_name="web_research_clarify",
            agent_id="analysis",
        )
        == "allowed"
    )

    for agent_id in ("planning", "implementation"):
        with pytest.raises(McpPermissionError):
            broker.ensure_workflow_tool_allowed(
                workflow_id="developer",
                server_id="web-research",
                tool_name="web_research_clarify",
                agent_id=agent_id,
            )


def test_checked_in_developer_contract_limits_web_research_to_analysis() -> None:
    contract = yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )
    agents = contract["agents"]

    assert agents["analysis"]["allowed_mcp_servers"]["web-research"]["tools"] == [
        "web_research_clarify"
    ]
    for agent_id, agent in agents.items():
        if agent_id == "analysis":
            continue
        assert "web-research" not in (agent.get("allowed_mcp_servers") or {})

    server = yaml.safe_load((REPO_ROOT / "safeplane.yaml").read_text(encoding="utf-8"))[
        "mcp_servers"
    ]["web-research"]
    assert server["endpoint"] == "http://web-research-gateway:8080/mcp"
    assert server["forward_context"] is False
    assert server["timeout_seconds"] == 120
