from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/web-research-agent/src"))

from web_research_agent import main  # noqa: E402


def _result() -> dict[str, Any]:
    return {
        "answer": "Public answer",
        "claims": ["A public claim"],
        "sources": [{"title": "Docs", "url": "https://example.com/docs"}],
        "incomplete_reasons": [],
        "security_events": [],
        "usage": {
            "search_requests": 1,
            "fetch_attempts": 1,
            "pages_fetched": 1,
            "bytes_fetched": 100,
            "llm_calls": 1,
            "input_tokens": 10,
            "output_tokens": 10,
            "estimated_cost_usd": 0.001,
        },
    }


def test_mcp_accepts_only_argument_only_research_call(monkeypatch) -> None:
    async def fake_run(arguments: main.ResearchArguments) -> dict[str, Any]:
        assert arguments.question == "What is the public FastAPI lifespan API?"
        return _result()

    monkeypatch.setattr(main, "run_public_research", fake_run)
    response = asyncio.run(
        main.mcp(
            {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {
                    "name": "web_research_clarify",
                    "arguments": {"question": "What is the public FastAPI lifespan API?"},
                },
            }
        )
    )

    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["answer"] == "Public answer"


def test_mcp_rejects_forwarded_safeplane_context() -> None:
    response = asyncio.run(
        main.mcp(
            {
                "jsonrpc": "2.0",
                "id": "call-2",
                "method": "tools/call",
                "params": {
                    "name": "web_research_clarify",
                    "arguments": {"question": "What is the public FastAPI lifespan API?"},
                    "context": {"run_id": "run_private"},
                },
            }
        )
    )

    assert response["error"]["code"] == -32602


def test_mcp_rejects_unknown_tool() -> None:
    response = asyncio.run(
        main.mcp(
            {
                "jsonrpc": "2.0",
                "id": "call-3",
                "method": "tools/call",
                "params": {"name": "browse_anything", "arguments": {}},
            }
        )
    )

    assert response["error"]["code"] == -32601


def test_read_secret_prefers_dedicated_mounted_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RESEARCH_SECRET_ROOT", tmp_path)
    (tmp_path / "brave_api_key").write_text("mounted-secret\n", encoding="utf-8")
    monkeypatch.setenv("BRAVE_API_KEY", "environment-secret")

    assert main._read_secret("BRAVE_API_KEY") == "mounted-secret"


def test_read_secret_allows_env_only_for_direct_execution(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RESEARCH_SECRET_ROOT", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "direct-test-secret")

    assert main._read_secret("OPENROUTER_API_KEY") == "direct-test-secret"
