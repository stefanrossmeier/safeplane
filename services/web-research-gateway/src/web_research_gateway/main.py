from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Literal
import urllib.error
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


TOOL_NAME = "web_research_clarify"
DEFAULT_UPSTREAM = "http://web-research-agent:8080/mcp"
DEFAULT_TIMEOUT_SECONDS = 115.0


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
    if "\n" in question or "\r" in question or "```" in question:
        raise ValueError("question must be one line and must not contain pasted code/context")
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
    name: Literal["web_research_clarify"]
    arguments: ResearchArguments


class JsonRpcRequest(StrictModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: Literal["tools/call"]
    params: ToolCallParams


app = FastAPI(title="Safeplane Web Research Gateway", version="1.0")


def _upstream_timeout_seconds() -> float:
    raw = os.getenv("SAFEPLANE_WEB_RESEARCH_UPSTREAM_TIMEOUT_SECONDS")
    timeout = DEFAULT_TIMEOUT_SECONDS if raw is None else float(raw)
    if timeout <= 0 or timeout > 120:
        raise RuntimeError("research gateway upstream timeout must be > 0 and <= 120 seconds")
    return timeout


def _forward(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.getenv("SAFEPLANE_WEB_RESEARCH_UPSTREAM", DEFAULT_UPSTREAM)
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_upstream_timeout_seconds()) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise RuntimeError("isolated research upstream is unavailable") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("isolated research upstream returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("isolated research upstream returned a non-object response")
    return result


def _rpc_error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(payload: dict[str, Any]) -> dict[str, Any]:
    request_id: str | int | None = payload.get("id") if isinstance(payload, dict) else None
    try:
        request = JsonRpcRequest.model_validate(payload)
    except ValidationError:
        return _rpc_error(request_id, -32602, "invalid public-research request")

    sanitized = request.model_dump(mode="json")
    try:
        result = await asyncio.to_thread(_forward, sanitized)
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "structuredContent": {"error": type(exc).__name__},
                "isError": True,
            },
        }
    if result.get("id") != request.id:
        return _rpc_error(request.id, -32603, "isolated research upstream response id mismatch")
    return result
