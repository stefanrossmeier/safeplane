from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.routing_advisor import (  # noqa: E402
    RoutingAdvisorAbstainedError,
    RoutingAdvisorPrerequisiteError,
    build_decision_request,
    evaluate_decision_response,
)
from harness.workflow_registry import build_registry  # noqa: E402


def repo_config() -> tuple[dict, dict]:
    path = REPO_ROOT / "safeplane.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config, build_registry(config, path)


def response(
    route: str,
    *,
    probabilities: dict[str, float] | None = None,
    identifiable: float = 0.99,
    multiple: float = 0.01,
    repository_work: float = 0.01,
    missing_repository_profile: float = 0.01,
    assistant_tool_need: float = 0.01,
) -> dict:
    probabilities = probabilities or {
        "chat": 0.005,
        "assistant": 0.99,
        "developer": 0.005,
    }
    return {
        "id": "decision_1",
        "model": "typesafe/jev-1.13-20260917",
        "provider": "TypeSafe",
        "answers": {
            "route": {
                "choice": route,
                "confidence": probabilities[route],
                "probabilities": probabilities,
            },
            "route_identifiable": {"noul": identifiable},
            "needs_clarification_before_execution": {"noul": 0.02},
            "requires_multiple_workflows": {"noul": multiple},
            "repository_work": {"noul": repository_work},
            "missing_repository_profile": {"noul": missing_repository_profile},
            "assistant_tool_need": {"noul": assistant_tool_need},
        },
        "usage": {
            "input_tokens": 123,
            "output_tokens": 7,
            "cost": 0.00001,
        },
    }


def test_decision_request_uses_versioned_workflow_routing_metadata() -> None:
    config, registry = repo_config()

    payload = build_decision_request(
        config=config,
        registry=registry,
        connector="cli",
        message="Remind me tomorrow at 09:00 to call the dentist",
        repository_profile=None,
    )

    assert payload["model"] == "typesafe/jev-1.13"
    assert payload["state"]["supplied_context"]["repository_profile"] is None
    criteria = payload["questions"]["route"]["criteria"]
    assert set(criteria) == {"chat", "assistant", "developer"}
    assert "Schedule, list, or cancel reminders" in criteria["assistant"]
    assert "selected software repository" in criteria["developer"]
    assert "General knowledge questions" in criteria["chat"]


def test_policy_accepts_clear_assistant_route() -> None:
    config, registry = repo_config()

    decision = evaluate_decision_response(
        config=config,
        registry=registry,
        connector="cli",
        routing_id="route_test",
        response=response("assistant", assistant_tool_need=0.99),
        duration_ms=12.5,
        repository_profile=None,
    )

    assert decision.accepted is True
    assert decision.entrypoint == "assistant"
    assert decision.semantic_route == "assistant"
    assert decision.policy.min_route_identifiable_probability == 0.80


def test_policy_abstains_on_multi_workflow_request() -> None:
    config, registry = repo_config()

    with pytest.raises(RoutingAdvisorAbstainedError) as exc_info:
        evaluate_decision_response(
            config=config,
            registry=registry,
            connector="cli",
            routing_id="route_multi",
            response=response("developer", multiple=0.91),
            duration_ms=10.0,
            repository_profile="fixture",
        )

    assert exc_info.value.decision.accepted is False
    assert exc_info.value.decision.reason == "multiple_workflows_required"


def test_developer_route_preserves_intent_but_blocks_without_repo_profile() -> None:
    config, registry = repo_config()
    developer_probabilities = {
        "chat": 0.01,
        "assistant": 0.01,
        "developer": 0.98,
    }

    with pytest.raises(RoutingAdvisorPrerequisiteError) as exc_info:
        evaluate_decision_response(
            config=config,
            registry=registry,
            connector="cli",
            routing_id="route_dev_missing",
            response=response(
                "developer",
                probabilities=developer_probabilities,
                repository_work=0.99,
                missing_repository_profile=0.99,
            ),
            duration_ms=9.0,
            repository_profile=None,
        )

    assert exc_info.value.decision.semantic_route == "developer"
    assert exc_info.value.decision.entrypoint == "develop"


def test_developer_route_accepts_when_repo_profile_is_supplied() -> None:
    config, registry = repo_config()
    probabilities = {"chat": 0.01, "assistant": 0.01, "developer": 0.98}

    decision = evaluate_decision_response(
        config=config,
        registry=registry,
        connector="cli",
        routing_id="route_dev",
        response=response(
            "developer",
            probabilities=probabilities,
            repository_work=0.99,
            missing_repository_profile=0.01,
        ),
        duration_ms=8.0,
        repository_profile="fixture",
    )

    assert decision.entrypoint == "develop"
    assert decision.accepted is True
