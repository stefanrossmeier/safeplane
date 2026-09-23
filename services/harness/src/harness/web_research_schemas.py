from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


WEB_RESEARCH_TOOL_NAME = "web_research_clarify"


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


def validate_public_research_question(value: str) -> str:
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


def validate_public_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError("allowed_domains entries must be public DNS hostnames")
    if domain == "localhost" or domain.endswith((".local", ".internal", ".localhost")):
        raise ValueError("allowed_domains must not reference local/internal hosts")
    return domain


class WebResearchInput(StrictModel):
    question: str = Field(min_length=8, max_length=600)
    allowed_domains: list[str] = Field(default_factory=list, max_length=8)
    freshness_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return validate_public_research_question(value)

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        normalized = [validate_public_domain(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_domains must not contain duplicates")
        return normalized


class WebResearchSource(StrictModel):
    title: str = ""
    url: str = Field(min_length=1, max_length=4096)


class WebResearchUsage(StrictModel):
    search_requests: int = Field(ge=0)
    fetch_attempts: int = Field(ge=0)
    pages_fetched: int = Field(ge=0)
    bytes_fetched: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class WebResearchOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=30000)
    claims: list[str] = Field(default_factory=list, max_length=50)
    sources: list[WebResearchSource] = Field(default_factory=list, max_length=50)
    incomplete_reasons: list[str] = Field(default_factory=list, max_length=50)
    security_events: list[str] = Field(default_factory=list, max_length=50)
    usage: WebResearchUsage


WEB_RESEARCH_TOOL_SCHEMAS: dict[str, dict[str, type[BaseModel]]] = {
    WEB_RESEARCH_TOOL_NAME: {
        "input_model": WebResearchInput,
        "output_model": WebResearchOutput,
    }
}


def normalized_web_research_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    return WebResearchInput.model_validate(payload).model_dump(mode="json")
