from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/web-research-agent/src"))


@pytest.mark.skipif(
    os.getenv("SAFEPLANE_RUN_LIVE_WEB_RESEARCH") != "1",
    reason="set SAFEPLANE_RUN_LIVE_WEB_RESEARCH=1 to run paid web research",
)
def test_live_public_research_returns_sources() -> None:
    pytest.importorskip("safe_web_research")
    if not os.getenv("BRAVE_API_KEY") or not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("BRAVE_API_KEY and OPENROUTER_API_KEY are required")

    from web_research_agent.main import ResearchArguments, run_public_research

    result = asyncio.run(
        run_public_research(
            ResearchArguments(
                question="What Python versions does the current FastAPI documentation support?",
                allowed_domains=["fastapi.tiangolo.com"],
            )
        )
    )

    assert result["answer"]
    assert result["sources"]
    assert result["usage"]["search_requests"] >= 1
    assert result["usage"]["estimated_cost_usd"] >= 0
