from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.mcp_broker import McpToolBroker  # noqa: E402


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
                        "timeout_seconds": 120,
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
                    }
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


def test_broker_does_not_forward_safeplane_context_to_research_service(tmp_path: Path) -> None:
    broker = McpToolBroker(config_path=_write_config(tmp_path), safeplane_home=tmp_path / "home")
    captured: dict[str, Any] = {}

    def fake_post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "isError": False,
                "structuredContent": {
                    "answer": "Public answer",
                    "claims": [],
                    "sources": [],
                    "incomplete_reasons": [],
                    "security_events": [],
                    "usage": {
                        "search_requests": 0,
                        "fetch_attempts": 0,
                        "pages_fetched": 0,
                        "bytes_fetched": 0,
                        "llm_calls": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "estimated_cost_usd": 0.0,
                    },
                },
            },
        }

    broker._post_json = fake_post_json  # type: ignore[method-assign]
    broker.call_tool(
        {
            "workflow_id": "developer",
            "server_id": "web-research",
            "tool_name": "web_research_clarify",
            "arguments": {"question": "What is the public FastAPI lifespan API?"},
            "session_id": "private-session",
            "turn": 4,
            "run_id": "run_private-123",
            "connector": "cli",
            "agent_id": "analysis",
        }
    )

    params = captured["payload"]["params"]
    assert set(params) == {"name", "arguments"}
    assert "private-session" not in repr(captured["payload"])
    assert "run_private-123" not in repr(captured["payload"])


def test_research_server_uses_bounded_longer_timeout(tmp_path: Path) -> None:
    broker = McpToolBroker(config_path=_write_config(tmp_path), safeplane_home=tmp_path / "home")
    assert broker._endpoint_timeout_seconds("http://web-research-agent:8080/mcp") == 120.0
