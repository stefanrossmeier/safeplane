from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


TOOL_NAME = "web_research_clarify"
DEFAULT_MODEL = "openai/gpt-5-mini"
RESEARCH_SECRET_ROOT = Path("/run/secrets/web-research")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:ghp_|github_pat_|xox[baprs]-|AKIA)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(
        r"\b(?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{64,}(?![A-Za-z0-9])"),
)
_PATH_PATTERNS = (
    re.compile(r"(?:^|[\s'\"(])/(?:Users|home|workspace|data/safeplane)(?:/|\b)", re.IGNORECASE),
    re.compile(r"(?:^|[\s'\"(])[A-Za-z]:\\"),
    re.compile(r"\bSAFEPLANE_[A-Z0-9_]+\b"),
)
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)


def _public_question(value: str) -> str:
    question = value.strip()
    if not question:
        raise ValueError("question must not be empty")
    if "\n" in question or "\r" in question:
        raise ValueError("question must be a single line; do not send pasted context")
    if "```" in question:
        raise ValueError("question must not contain code fences")
    for pattern in (*_SECRET_PATTERNS, *_PATH_PATTERNS):
        if pattern.search(question):
            raise ValueError("question failed the public-research declassification guard")
    return question


def _public_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError("allowed_domains entries must be public DNS hostnames")
    if domain == "localhost" or domain.endswith((".local", ".internal", ".localhost")):
        raise ValueError("allowed_domains must not reference local/internal hosts")
    return domain


class ResearchArguments(StrictModel):
    question: str = Field(min_length=8, max_length=600)
    allowed_domains: list[str] = Field(default_factory=list, max_length=8)
    freshness_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return _public_question(value)

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        normalized = [_public_domain(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_domains must not contain duplicates")
        return normalized


class ToolCallParams(StrictModel):
    name: str
    arguments: dict[str, Any]


class JsonRpcRequest(StrictModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: Literal["tools/call"]
    params: ToolCallParams


app = FastAPI(title="Safeplane Web Research Agent", version="1.0")


def _read_secret(name: str) -> str:
    # In the container, credentials are mounted at a fixed, dedicated path.
    # Environment values remain supported only for direct/local execution and
    # the explicitly opt-in live test; Compose never injects credential values
    # or credential-path variables into the base service definition.
    secret_path = RESEARCH_SECRET_ROOT / name.lower()
    if secret_path.is_file():
        value = secret_path.read_text(encoding="utf-8").strip()
    else:
        value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"missing required research credential: {name}")
    return value


def _project_result(result: Any) -> dict[str, Any]:
    raw = result.model_dump(mode="json")
    claims = [str(item.get("text") or "") for item in raw.get("claims") or []]
    claims = [item for item in claims if item][:50]
    sources = [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
        }
        for item in raw.get("sources") or []
        if item.get("url")
    ][:50]
    security_events = [
        ": ".join(
            part
            for part in (
                str(item.get("severity") or ""),
                str(item.get("event_type") or ""),
                str(item.get("message") or ""),
            )
            if part
        )
        for item in raw.get("security_events") or []
    ][:50]
    usage = raw.get("usage") or {}
    return {
        "answer": str(raw.get("answer") or ""),
        "claims": claims,
        "sources": sources,
        "incomplete_reasons": [str(item) for item in raw.get("incomplete_reasons") or []][:50],
        "security_events": security_events,
        "usage": {
            "search_requests": int(usage.get("search_requests") or 0),
            "fetch_attempts": int(usage.get("fetch_attempts") or 0),
            "pages_fetched": int(usage.get("pages_fetched") or 0),
            "bytes_fetched": int(usage.get("bytes_fetched") or 0),
            "llm_calls": int(usage.get("llm_calls") or 0),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "estimated_cost_usd": float(usage.get("estimated_cost_usd") or 0.0),
        },
    }


async def run_public_research(arguments: ResearchArguments) -> dict[str, Any]:
    # Keep safe-web-research imports lazy so health checks and contract tests do not
    # initialize an Internet-capable research stack.
    from safe_web_research.domain import ResearchBudget, ResearchRequest
    from safe_web_research.extraction import WebExtractor
    from safe_web_research.fetch import SafeFetcher, SystemDNSResolver, URLPolicy
    from safe_web_research.llm import OpenRouterLLMProvider
    from safe_web_research.research import (
        EvidenceGatherer,
        ResearchPlanner,
        ResearchService,
        ResearchSynthesizer,
        ResearchVerifier,
    )
    from safe_web_research.search import BraveSearchProvider

    llm = OpenRouterLLMProvider(
        _read_secret("OPENROUTER_API_KEY"),
        model=os.getenv("SAFEPLANE_WEB_RESEARCH_MODEL", DEFAULT_MODEL),
    )
    service = ResearchService(
        ResearchPlanner(llm),
        EvidenceGatherer(
            BraveSearchProvider(_read_secret("BRAVE_API_KEY")),
            SafeFetcher(URLPolicy(SystemDNSResolver())),
            WebExtractor(),
        ),
        ResearchSynthesizer(llm),
        ResearchVerifier(llm),
    )
    request = ResearchRequest(
        question=arguments.question,
        allowed_domains=arguments.allowed_domains,
        freshness_days=arguments.freshness_days,
        budget=ResearchBudget(
            max_searches=4,
            max_fetch_attempts=12,
            max_pages=6,
            max_bytes_per_page=1_000_000,
            max_total_bytes=5_000_000,
            max_redirects=3,
            max_llm_calls=6,
            max_input_tokens=100_000,
            max_output_tokens=10_000,
        ),
    )
    result = await service.research(request)
    projected = _project_result(result)
    if not projected["answer"]:
        raise RuntimeError("safe-web-research returned no synthesized answer")
    return projected


def _rpc_error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(payload: dict[str, Any]) -> dict[str, Any]:
    request_id: str | int | None = payload.get("id") if isinstance(payload, dict) else None
    try:
        request = JsonRpcRequest.model_validate(payload)
        if request.params.name != TOOL_NAME:
            return _rpc_error(request.id, -32601, f"unknown tool: {request.params.name}")
        arguments = ResearchArguments.model_validate(request.params.arguments)
        result = await run_public_research(arguments)
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "structuredContent": result,
                "isError": False,
            },
        }
    except ValidationError:
        return _rpc_error(request_id, -32602, "invalid public-research request")
    except Exception as exc:
        # Return an MCP error without echoing request arguments or credentials.
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": {"error": type(exc).__name__},
                "isError": True,
            },
        }
