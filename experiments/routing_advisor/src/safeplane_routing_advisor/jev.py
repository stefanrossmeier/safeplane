from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .models import EvaluationCase, JevAssessment, Usage, WorkflowCatalog

DEFAULT_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        url: str = DEFAULT_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model
        self._url = url
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/stefanrossmeier/safeplane",
                "X-Title": "Safeplane routing advisor experiment",
            },
        )

    async def __aenter__(self) -> "JevClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    def _payload(self, case: EvaluationCase, catalog: WorkflowCatalog) -> dict[str, Any]:
        route_criteria = {
            name: route.criterion_text() for name, route in catalog.routes.items()
        }
        state = {
            "request": case.request_text,
            "supplied_context": case.context,
        }

        if catalog.semantics_version == 1:
            if not catalog.unclear_summary or not catalog.ambiguity_instructions:
                raise ValueError("Incomplete V1 routing semantics")
            route_criteria["unclear"] = catalog.unclear_summary
            questions: dict[str, Any] = {
                "route": {
                    "type": "choice",
                    "instructions": catalog.route_instructions,
                    "criteria": route_criteria,
                },
                "ambiguous": {
                    "type": "noul",
                    "instructions": catalog.ambiguity_instructions,
                    "criteria": {
                        "true": "The request lacks enough information for a confident workflow choice, or two workflows are comparably plausible.",
                        "false": "One workflow is clearly the best semantic match.",
                    },
                },
            }
        elif catalog.semantics_version == 2:
            if not (
                catalog.route_identifiable_instructions
                and catalog.needs_clarification_instructions
                and catalog.requires_multiple_workflows_instructions
            ):
                raise ValueError("Incomplete V2 routing semantics")
            questions = {
                "route": {
                    "type": "choice",
                    "instructions": catalog.route_instructions,
                    "criteria": route_criteria,
                },
                "route_identifiable": {
                    "type": "noul",
                    "instructions": catalog.route_identifiable_instructions,
                    "criteria": {
                        "true": "The request contains enough semantic information to identify the relevant Safeplane workflow intent, even if task-specific details are still missing.",
                        "false": "The request is too content-free or underspecified to identify even the relevant workflow intent.",
                    },
                },
                "needs_clarification_before_execution": {
                    "type": "noul",
                    "instructions": catalog.needs_clarification_instructions,
                    "criteria": {
                        "true": "The workflow intent is identifiable, but task-specific content, target, identifier, artifact, or other execution detail is missing and should be clarified before performing the task.",
                        "false": "The selected workflow has enough task-specific information to begin the requested work. A missing repository_profile is evaluated separately and does not make this true by itself.",
                    },
                },
                "requires_multiple_workflows": {
                    "type": "noul",
                    "instructions": catalog.requires_multiple_workflows_instructions,
                    "criteria": {
                        "true": "Completing the request as written requires capabilities from more than one of chat, assistant, and developer, such as repository work plus a calendar/reminder action.",
                        "false": "One Safeplane workflow is sufficient for the request as written.",
                    },
                },
            }
        else:
            raise ValueError(f"Unsupported semantics version: {catalog.semantics_version}")

        questions.update(
            {
                "repository_work": {
                    "type": "noul",
                    "instructions": catalog.repository_work_instructions,
                    "criteria": {
                        "true": "The request is about inspecting or changing a specific software repository or its files, tests, configuration, history, or repository documentation.",
                        "false": "The request is generic software knowledge, standalone code help, or unrelated to a specific repository.",
                    },
                },
                "missing_repository_profile": {
                    "type": "noul",
                    "instructions": catalog.missing_repository_profile_instructions,
                    "criteria": {
                        "true": "Repository work is semantically required but no usable repository_profile is present in supplied_context.",
                        "false": "Repository context is not needed, or supplied_context already contains a repository_profile.",
                    },
                },
                "assistant_tool_need": {
                    "type": "noul",
                    "instructions": catalog.assistant_tool_need_instructions,
                    "criteria": {
                        "true": "The request asks to list/create/move/cancel calendar entries or schedule/list/cancel notifications or reminders.",
                        "false": "The request can be answered without Safeplane calendar or notification actions.",
                    },
                },
            }
        )
        return {"model": self._model, "state": state, "questions": questions}

    async def assess(self, case: EvaluationCase, catalog: WorkflowCatalog) -> JevAssessment:
        payload = self._payload(case, catalog)
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(self._url, json=payload)
                if response.status_code in {429, 500, 502, 503, 524, 529} and attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                response.raise_for_status()
                return self._parse(response.json())
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"Jev request failed after retries: {last_error}") from last_error

    @staticmethod
    def _parse(data: dict[str, Any]) -> JevAssessment:
        answers = data["answers"]
        route = answers["route"]
        usage = data.get("usage") or {}
        cost = usage.get("cost", usage.get("estimated_cost_usd", 0.0)) or 0.0

        def noul(name: str) -> float | None:
            answer = answers.get(name)
            return None if answer is None else float(answer["noul"])

        return JevAssessment(
            model=str(data.get("model", "unknown")),
            provider=str(data["provider"]) if data.get("provider") is not None else None,
            route=str(route["choice"]),  # type: ignore[arg-type]
            route_confidence=float(route.get("confidence", 0.0)),
            route_probabilities={key: float(value) for key, value in route["probabilities"].items()},
            ambiguous_probability=noul("ambiguous"),
            route_identifiable_probability=noul("route_identifiable"),
            needs_clarification_probability=noul("needs_clarification_before_execution"),
            requires_multiple_workflows_probability=noul("requires_multiple_workflows"),
            repository_work_probability=float(answers["repository_work"]["noul"]),
            missing_repository_profile_probability=float(answers["missing_repository_profile"]["noul"]),
            assistant_tool_need_probability=float(answers["assistant_tool_need"]["noul"]),
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                estimated_cost_usd=float(cost),
            ),
            raw_id=str(data["id"]) if data.get("id") is not None else None,
        )
