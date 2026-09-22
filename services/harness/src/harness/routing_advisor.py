from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, Literal
import urllib.error
import urllib.request

from harness.workflow_registry import (
    WorkflowRegistryEntry,
    connector_is_exposed,
    resolve_entrypoint_from_registry,
)

SemanticRoute = Literal["chat", "assistant", "developer"]


class RoutingAdvisorError(RuntimeError):
    pass


class RoutingAdvisorUnavailableError(RoutingAdvisorError):
    pass


class RoutingAdvisorAbstainedError(RoutingAdvisorError):
    def __init__(self, message: str, *, decision: "RoutingDecision") -> None:
        super().__init__(message)
        self.decision = decision


class RoutingAdvisorPrerequisiteError(RoutingAdvisorError):
    def __init__(self, message: str, *, decision: "RoutingDecision") -> None:
        super().__init__(message)
        self.decision = decision


@dataclass(frozen=True)
class RoutingPolicy:
    min_top_probability: float = 0.50
    min_margin: float = 0.00
    min_route_identifiable_probability: float = 0.80
    max_multiple_workflows_probability: float = 0.50


@dataclass(frozen=True)
class RoutingDecision:
    routing_id: str
    semantic_route: SemanticRoute | None
    entrypoint: str | None
    accepted: bool
    reason: str
    route_probabilities: dict[str, float]
    route_confidence: float
    route_margin: float
    route_identifiable_probability: float
    needs_clarification_probability: float
    requires_multiple_workflows_probability: float
    repository_work_probability: float
    missing_repository_profile_probability: float
    assistant_tool_need_probability: float
    model: str
    provider: str | None
    decision_id: str | None
    usage: dict[str, Any]
    duration_ms: float
    policy: RoutingPolicy

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["policy"] = asdict(self.policy)
        return value


def routing_config(config: dict[str, Any]) -> dict[str, Any]:
    configured = config.get("routing_advisor")
    if not isinstance(configured, dict):
        raise RoutingAdvisorUnavailableError("routing_advisor is not configured")
    if not configured.get("enabled", False):
        raise RoutingAdvisorUnavailableError("routing_advisor is disabled")
    return configured


def routing_policy(config: dict[str, Any]) -> RoutingPolicy:
    configured = routing_config(config)
    raw = configured.get("policy") or {}
    if not isinstance(raw, dict):
        raise RoutingAdvisorUnavailableError("routing_advisor.policy must be a mapping")
    return RoutingPolicy(
        min_top_probability=float(raw.get("min_top_probability", 0.50)),
        min_margin=float(raw.get("min_margin", 0.00)),
        min_route_identifiable_probability=float(
            raw.get("min_route_identifiable_probability", 0.80)
        ),
        max_multiple_workflows_probability=float(
            raw.get("max_multiple_workflows_probability", 0.50)
        ),
    )


def _criterion_text(entry: WorkflowRegistryEntry) -> str:
    routing = entry.routing
    summary = str(routing.get("summary") or "").strip()
    positive = [str(item) for item in routing.get("positive_signals") or []]
    negative = [str(item) for item in routing.get("negative_signals") or []]
    if not summary or not positive or not negative:
        raise RoutingAdvisorUnavailableError(
            f"Workflow {entry.workflow_id!r} is missing complete routing metadata"
        )

    pieces = [
        summary,
        f"Workflow description: {entry.description}",
        f"Positive signals: {'; '.join(positive)}",
        f"Do not use when: {'; '.join(negative)}",
    ]
    servers = [str(item) for item in entry.mcp.get("servers", [])]
    tools = [str(item) for item in entry.deterministic_tools.get("enabled", [])]
    if servers:
        pieces.append(f"Available MCP servers: {', '.join(servers)}")
    if tools:
        pieces.append(f"Deterministic tools: {', '.join(tools)}")
    return " ".join(pieces)


def build_decision_request(
    *,
    config: dict[str, Any],
    registry: dict[str, WorkflowRegistryEntry],
    connector: str,
    message: str,
    repository_profile: str | None,
) -> dict[str, Any]:
    configured = routing_config(config)
    routes = configured.get("routes")
    questions = configured.get("questions")
    if not isinstance(routes, dict) or not isinstance(questions, dict):
        raise RoutingAdvisorUnavailableError(
            "routing_advisor.routes and routing_advisor.questions must be mappings"
        )

    criteria: dict[str, str] = {}
    for semantic_route in ("chat", "assistant", "developer"):
        entrypoint = str(routes.get(semantic_route) or "").strip()
        if not entrypoint:
            raise RoutingAdvisorUnavailableError(
                f"routing_advisor.routes.{semantic_route} is missing"
            )
        entry = resolve_entrypoint_from_registry(registry, entrypoint)
        if not entry.operator_facing or not connector_is_exposed(entry, connector):
            raise RoutingAdvisorUnavailableError(
                f"Routing target {entrypoint!r} is not exposed to connector {connector!r}"
            )
        criteria[semantic_route] = _criterion_text(entry)

    def instruction(name: str) -> str:
        value = str(questions.get(name) or "").strip()
        if not value:
            raise RoutingAdvisorUnavailableError(
                f"routing_advisor.questions.{name} is missing"
            )
        return value

    decision_questions = {
        "route": {
            "type": "choice",
            "instructions": instruction("route"),
            "criteria": criteria,
        },
        "route_identifiable": {
            "type": "noul",
            "instructions": instruction("route_identifiable"),
            "criteria": {
                "true": "The request contains enough semantic information to identify the relevant Safeplane workflow intent, even if task-specific details are still missing.",
                "false": "The request is too content-free or underspecified to identify even the relevant workflow intent.",
            },
        },
        "needs_clarification_before_execution": {
            "type": "noul",
            "instructions": instruction("needs_clarification_before_execution"),
            "criteria": {
                "true": "The workflow intent is identifiable, but task-specific content, target, identifier, artifact, or other execution detail is missing and should be clarified before performing the task.",
                "false": "The selected workflow has enough task-specific information to begin the requested work. A missing repository_profile is evaluated separately and does not make this true by itself.",
            },
        },
        "requires_multiple_workflows": {
            "type": "noul",
            "instructions": instruction("requires_multiple_workflows"),
            "criteria": {
                "true": "Completing the request as written requires capabilities from more than one of chat, assistant, and developer, such as repository work plus a calendar/reminder action.",
                "false": "One Safeplane workflow is sufficient for the request as written.",
            },
        },
        "repository_work": {
            "type": "noul",
            "instructions": instruction("repository_work"),
            "criteria": {
                "true": "The request is about inspecting or changing a specific software repository or its files, tests, configuration, history, or repository documentation.",
                "false": "The request is generic software knowledge, standalone code help, or unrelated to a specific repository.",
            },
        },
        "missing_repository_profile": {
            "type": "noul",
            "instructions": instruction("missing_repository_profile"),
            "criteria": {
                "true": "Repository work is semantically required but no usable repository_profile is present in supplied_context.",
                "false": "Repository context is not needed, or supplied_context already contains a repository_profile.",
            },
        },
        "assistant_tool_need": {
            "type": "noul",
            "instructions": instruction("assistant_tool_need"),
            "criteria": {
                "true": "The request asks to list/create/move/cancel calendar entries or schedule/list/cancel notifications or reminders.",
                "false": "The request can be answered without Safeplane calendar or notification actions.",
            },
        },
    }

    return {
        "model": str(configured.get("model") or "typesafe/jev-1.13"),
        "state": {
            "request": message,
            "supplied_context": {
                "connector": connector,
                "repository_profile": repository_profile,
            },
        },
        "questions": decision_questions,
        "timeout_seconds": int(configured.get("timeout_seconds", 30)),
    }


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RoutingAdvisorUnavailableError(
            f"model gateway decision request failed with HTTP {exc.code}: {body}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RoutingAdvisorUnavailableError(
            f"model gateway decision request failed: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RoutingAdvisorUnavailableError("model gateway decision response must be an object")
    return data


def _noul(answers: dict[str, Any], name: str, *, default: float) -> float:
    value = answers.get(name)
    if not isinstance(value, dict) or "noul" not in value:
        return default
    return float(value["noul"])


def evaluate_decision_response(
    *,
    config: dict[str, Any],
    registry: dict[str, WorkflowRegistryEntry],
    connector: str,
    routing_id: str,
    response: dict[str, Any],
    duration_ms: float,
    repository_profile: str | None,
) -> RoutingDecision:
    configured = routing_config(config)
    policy = routing_policy(config)
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise RoutingAdvisorUnavailableError("decision response is missing answers")
    route_answer = answers.get("route")
    if not isinstance(route_answer, dict):
        raise RoutingAdvisorUnavailableError("decision response is missing route answer")

    route = str(route_answer.get("choice") or "")
    if route not in {"chat", "assistant", "developer"}:
        raise RoutingAdvisorUnavailableError(f"decision response returned invalid route: {route!r}")

    raw_probabilities = route_answer.get("probabilities")
    if not isinstance(raw_probabilities, dict):
        raise RoutingAdvisorUnavailableError("decision response route is missing probabilities")
    probabilities = {
        name: float(raw_probabilities.get(name, 0.0))
        for name in ("chat", "assistant", "developer")
    }
    ordered = sorted(probabilities.values(), reverse=True)
    top = ordered[0] if ordered else 0.0
    second = ordered[1] if len(ordered) > 1 else 0.0
    margin = top - second
    identifiable = _noul(answers, "route_identifiable", default=0.0)
    multiple = _noul(answers, "requires_multiple_workflows", default=1.0)

    accepted = True
    reason = "accepted"
    if top < policy.min_top_probability:
        accepted = False
        reason = "top_probability_below_threshold"
    elif margin < policy.min_margin:
        accepted = False
        reason = "route_margin_below_threshold"
    elif identifiable < policy.min_route_identifiable_probability:
        accepted = False
        reason = "route_not_identifiable"
    elif multiple > policy.max_multiple_workflows_probability:
        accepted = False
        reason = "multiple_workflows_required"

    routes = configured.get("routes") or {}
    entrypoint = str(routes.get(route) or "") if accepted else None
    if accepted:
        entry = resolve_entrypoint_from_registry(registry, entrypoint)
        if not entry.operator_facing or not connector_is_exposed(entry, connector):
            raise RoutingAdvisorUnavailableError(
                f"accepted route target {entrypoint!r} is not exposed to connector {connector!r}"
            )

    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    decision = RoutingDecision(
        routing_id=routing_id,
        semantic_route=route,  # type: ignore[arg-type]
        entrypoint=entrypoint or None,
        accepted=accepted,
        reason=reason,
        route_probabilities=probabilities,
        route_confidence=float(route_answer.get("confidence", top) or 0.0),
        route_margin=margin,
        route_identifiable_probability=identifiable,
        needs_clarification_probability=_noul(
            answers, "needs_clarification_before_execution", default=0.0
        ),
        requires_multiple_workflows_probability=multiple,
        repository_work_probability=_noul(answers, "repository_work", default=0.0),
        missing_repository_profile_probability=_noul(
            answers, "missing_repository_profile", default=0.0
        ),
        assistant_tool_need_probability=_noul(answers, "assistant_tool_need", default=0.0),
        model=str(response.get("model") or configured.get("model") or "unknown"),
        provider=str(response["provider"]) if response.get("provider") is not None else None,
        decision_id=str(response["id"]) if response.get("id") is not None else None,
        usage=dict(usage),
        duration_ms=duration_ms,
        policy=policy,
    )

    if not accepted:
        raise RoutingAdvisorAbstainedError(
            f"Automatic routing abstained: {reason}. Use an explicit workflow command.",
            decision=decision,
        )
    if route == "developer" and not repository_profile:
        raise RoutingAdvisorPrerequisiteError(
            "Automatic routing selected the developer workflow, but repository context is required. "
            "Use --repo with CLI auto routing or /develop <repository-profile> <task> in Telegram.",
            decision=decision,
        )
    return decision


def route_message(
    *,
    config: dict[str, Any],
    registry: dict[str, WorkflowRegistryEntry],
    connector: str,
    message: str,
    repository_profile: str | None,
    routing_id: str,
) -> RoutingDecision:
    configured = routing_config(config)
    payload = build_decision_request(
        config=config,
        registry=registry,
        connector=connector,
        message=message,
        repository_profile=repository_profile,
    )
    endpoint = str(
        configured.get("model_gateway_endpoint")
        or "http://model-gateway:8080/decisions"
    )
    timeout_seconds = int(configured.get("timeout_seconds", 30))
    started = time.perf_counter()
    response = _post_json(endpoint, payload, timeout_seconds)
    duration_ms = (time.perf_counter() - started) * 1000.0
    return evaluate_decision_response(
        config=config,
        registry=registry,
        connector=connector,
        routing_id=routing_id,
        response=response,
        duration_ms=duration_ms,
        repository_profile=repository_profile,
    )


def write_routing_trace(
    *,
    safeplane_home: Path,
    routing_id: str,
    connector: str,
    message: str,
    repository_profile: str | None,
    decision: RoutingDecision | None = None,
    error: Exception | None = None,
) -> Path:
    path = safeplane_home / "traces" / "routing"
    path.mkdir(parents=True, exist_ok=True)
    trace_path = path / f"{routing_id}.json"
    payload: dict[str, Any] = {
        "routing_id": routing_id,
        "connector": connector,
        "message": message,
        "repository_profile": repository_profile,
        "decision": decision.to_dict() if decision is not None else None,
        "error": (
            {"type": type(error).__name__, "message": str(error)}
            if error is not None
            else None
        ),
    }
    trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return trace_path
