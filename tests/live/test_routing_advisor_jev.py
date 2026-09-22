from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "services/model-gateway/src"))

from harness.routing_advisor import (  # noqa: E402
    RoutingAdvisorAbstainedError,
    build_decision_request,
    evaluate_decision_response,
)
from harness.workflow_registry import build_registry  # noqa: E402
from model_gateway.main import DecisionRequest, real_decision  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("SAFEPLANE_RUN_LIVE_JEV") != "1",
    reason="set SAFEPLANE_RUN_LIVE_JEV=1 or run `make test-routing-jev`",
)


def _openrouter_key() -> str:
    direct = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if direct:
        return direct
    secret_root = Path(
        os.environ.get(
            "SAFEPLANE_SECRET_ROOT",
            str(Path.home() / ".config/safeplane/secrets"),
        )
    )
    secret_file = Path(
        os.environ.get(
            "SAFEPLANE_OPENROUTER_API_KEY_FILE",
            str(secret_root / "openrouter_api_key"),
        )
    )
    if not secret_file.exists():
        pytest.skip(f"OpenRouter secret file not found: {secret_file}")
    value = secret_file.read_text(encoding="utf-8").strip()
    if not value:
        pytest.skip(f"OpenRouter secret file is empty: {secret_file}")
    return value


def _config_and_registry() -> tuple[dict, dict]:
    path = REPO_ROOT / "safeplane.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config, build_registry(config, path)


def _live_route(
    monkeypatch,
    text: str,
    *,
    repository_profile: str | None = None,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", _openrouter_key())
    config, registry = _config_and_registry()
    payload = build_decision_request(
        config=config,
        registry=registry,
        connector="cli",
        message=text,
        repository_profile=repository_profile,
    )
    response = real_decision(DecisionRequest.model_validate(payload)).model_dump()
    return config, registry, response


@pytest.mark.parametrize(
    ("text", "repository_profile", "expected_route", "expected_entrypoint"),
    [
        (
            "Remind me tomorrow at 09:00 to call the dentist.",
            None,
            "assistant",
            "assistant",
        ),
        (
            "Explain why database indexes usually speed up reads.",
            None,
            "chat",
            "chat",
        ),
        (
            "In the selected repository, inspect the failing tests and propose a focused fix.",
            "fixture",
            "developer",
            "develop",
        ),
    ],
)
def test_live_jev_routes_clear_typical_requests(
    monkeypatch,
    text: str,
    repository_profile: str | None,
    expected_route: str,
    expected_entrypoint: str,
) -> None:
    config, registry, response = _live_route(
        monkeypatch,
        text,
        repository_profile=repository_profile,
    )
    decision = evaluate_decision_response(
        config=config,
        registry=registry,
        connector="cli",
        routing_id="live_test",
        response=response,
        duration_ms=0.0,
        repository_profile=repository_profile,
    )
    assert decision.semantic_route == expected_route
    assert decision.entrypoint == expected_entrypoint
    assert decision.accepted is True


def test_live_jev_abstains_for_repo_plus_reminder_compound_request(monkeypatch) -> None:
    config, registry, response = _live_route(
        monkeypatch,
        "Inspect the selected repository for the failing test and remind me tomorrow at 09:00 to review the result.",
        repository_profile="fixture",
    )
    with pytest.raises(RoutingAdvisorAbstainedError) as exc_info:
        evaluate_decision_response(
            config=config,
            registry=registry,
            connector="cli",
            routing_id="live_multi",
            response=response,
            duration_ms=0.0,
            repository_profile="fixture",
        )
    assert exc_info.value.decision.reason == "multiple_workflows_required"
