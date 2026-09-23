from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.developer_pipeline import (  # noqa: E402
    StageModelCallResult,
    _run_analysis_agent_loop,
)


class StubStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append_event(self, **event) -> None:
        self.events.append(event)


def _analysis_result() -> dict[str, object]:
    return {
        "requirements_markdown": "# Requirements\nUse the documented public API.",
        "architecture_tasks_markdown": "# Architecture Tasks\nIntegrate the public API.",
        "assumptions": [],
        "open_questions": [],
        "scope_risks": [],
    }


def test_analysis_agent_can_research_once_then_return_normal_analysis_artifact() -> None:
    model_responses = iter(
        [
            {
                "type": "tool_call",
                "server_id": "web-research",
                "tool_name": "web_research_clarify",
                "arguments": {
                    "question": "What is the documented FastAPI lifespan API?",
                    "allowed_domains": ["fastapi.tiangolo.com"],
                },
            },
            _analysis_result(),
        ]
    )
    tool_calls: list[tuple[object, ...]] = []

    def call_model(stage_id, response_key, model_profile, messages):
        assert stage_id == "analysis"
        return StageModelCallResult(
            content=json.dumps(next(model_responses)),
            model={"mode": "live", "actual_model": "test"},
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.01},
        )

    def call_tool(*args):
        tool_calls.append(args)
        return {
            "answer": "Use FastAPI lifespan handlers.",
            "claims": [],
            "sources": [{"title": "FastAPI", "url": "https://fastapi.tiangolo.com/advanced/events/"}],
            "incomplete_reasons": [],
            "security_events": [],
            "usage": {
                "search_requests": 1,
                "fetch_attempts": 1,
                "pages_fetched": 1,
                "bytes_fetched": 100,
                "llm_calls": 2,
                "input_tokens": 100,
                "output_tokens": 20,
                "estimated_cost_usd": 0.001,
            },
        }

    result = _run_analysis_agent_loop(
        agent={
            "allowed_mcp_servers": {
                "web-research": {"tools": ["web_research_clarify"]}
            }
        },
        model_profile="developer_analysis",
        response_key="analysis",
        system_prompt="system",
        user_message="user",
        max_attempts=3,
        call_stage_model=call_model,
        call_stage_tool=call_tool,
        trace=lambda *args: None,
        store=StubStore(),
    )

    assert result.artifact.requirements_markdown.startswith("# Requirements")
    assert result.model_call_count == 2
    assert result.tool_call_count == 1
    assert result.final_call.usage == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
        "cost": 0.02,
    }
    assert tool_calls[0][0:4] == (
        "analysis",
        "analysis",
        "web-research",
        "web_research_clarify",
    )
