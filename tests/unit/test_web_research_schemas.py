from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.mcp_schemas import validate_tool_input, validate_tool_output  # noqa: E402


def valid_output() -> dict[str, object]:
    return {
        "answer": "FastAPI supports lifespan handlers for application startup and shutdown.",
        "claims": ["FastAPI supports lifespan handlers."],
        "sources": [{"title": "FastAPI docs", "url": "https://fastapi.tiangolo.com/advanced/events/"}],
        "incomplete_reasons": [],
        "security_events": [],
        "usage": {
            "search_requests": 1,
            "fetch_attempts": 1,
            "pages_fetched": 1,
            "bytes_fetched": 1000,
            "llm_calls": 2,
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost_usd": 0.001,
        },
    }


def test_web_research_input_accepts_small_public_question() -> None:
    validated = validate_tool_input(
        "web_research_clarify",
        {
            "question": "What is the documented FastAPI lifespan API?",
            "allowed_domains": ["fastapi.tiangolo.com"],
            "freshness_days": 365,
        },
    )

    assert validated.question == "What is the documented FastAPI lifespan API?"
    assert validated.allowed_domains == ["fastapi.tiangolo.com"]


@pytest.mark.parametrize(
    "question",
    [
        "Read /workspace/src/private.py and explain its framework requirements",
        "Check /Users/alice/private/project/config.toml against the public docs",
        "Is api_key=sk-abcdefghijklmnopqrstuvwxyz123456789 valid for this SDK?",
        "Compare this token eyJaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbb.ccccccccccc with docs",
        "Research this pasted context:\ninternal implementation details",
        "Research this code: ```python print('private')```",
    ],
)
def test_web_research_input_rejects_obvious_declassification_failures(question: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        validate_tool_input("web_research_clarify", {"question": question})


def test_web_research_input_rejects_context_blob_field() -> None:
    with pytest.raises((ValidationError, ValueError)):
        validate_tool_input(
            "web_research_clarify",
            {
                "question": "What is the documented FastAPI lifespan API?",
                "context": "repository contents",
            },
        )


def test_web_research_input_rejects_internal_domain() -> None:
    with pytest.raises((ValidationError, ValueError)):
        validate_tool_input(
            "web_research_clarify",
            {
                "question": "What API does this public package expose?",
                "allowed_domains": ["docs.corp.internal"],
            },
        )


def test_web_research_output_schema_is_bounded_and_structured() -> None:
    validated = validate_tool_output("web_research_clarify", valid_output())
    assert validated.answer.startswith("FastAPI")
    assert validated.usage.llm_calls == 2
