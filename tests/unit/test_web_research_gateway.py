from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/web-research-gateway/src"))

from web_research_gateway import main  # noqa: E402


def _upstream_result(request_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
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


def test_gateway_forwards_only_schema_validated_request(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_forward(payload: dict[str, Any]) -> dict[str, Any]:
        captured.update(payload)
        return _upstream_result("call-1")

    monkeypatch.setattr(main, "_forward", fake_forward)
    response = asyncio.run(
        main.mcp(
            {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {
                    "name": "web_research_clarify",
                    "arguments": {
                        "question": "What is the public FastAPI lifespan API?",
                        "allowed_domains": ["fastapi.tiangolo.com"],
                    },
                },
            }
        )
    )

    assert response["result"]["isError"] is False
    assert set(captured["params"]) == {"name", "arguments"}
    assert "context" not in captured["params"]


def test_gateway_rejects_context_and_private_material_before_forward(monkeypatch) -> None:
    called = False

    def fake_forward(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called = True
        return _upstream_result("call-2")

    monkeypatch.setattr(main, "_forward", fake_forward)
    response = asyncio.run(
        main.mcp(
            {
                "jsonrpc": "2.0",
                "id": "call-2",
                "method": "tools/call",
                "params": {
                    "name": "web_research_clarify",
                    "arguments": {
                        "question": "Read /workspace/private.py and compare it with the docs"
                    },
                    "context": {"run_id": "private-run"},
                },
            }
        )
    )

    assert response["error"]["code"] == -32602
    assert called is False
    assert "private-run" not in repr(response)
