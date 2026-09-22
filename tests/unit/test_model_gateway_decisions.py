from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/model-gateway/src"))

from model_gateway.main import (  # noqa: E402
    DecisionRequest,
    fake_decision,
    real_decision,
)


def request(text: str, repository_profile: str | None = None) -> DecisionRequest:
    return DecisionRequest(
        state={
            "request": text,
            "supplied_context": {"repository_profile": repository_profile},
        },
        questions={"route": {"type": "choice", "criteria": {}}},
    )


def test_fake_decision_routes_reminders_to_assistant() -> None:
    result = fake_decision(request("Remind me tomorrow to call the dentist"))
    assert result.answers["route"]["choice"] == "assistant"
    assert result.answers["assistant_tool_need"]["noul"] == 0.99


def test_fake_decision_marks_repo_plus_reminder_as_multi_workflow() -> None:
    result = fake_decision(
        request("Inspect the repository and remind me tomorrow to review it", "fixture")
    )
    assert result.answers["route"]["choice"] == "developer"
    assert result.answers["requires_multiple_workflows"]["noul"] == 0.99


def test_real_decision_forwards_provider_neutral_contract(monkeypatch) -> None:
    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": "dec_live",
                    "model": "typesafe/jev-1.13-20260917",
                    "provider": "TypeSafe",
                    "answers": {
                        "route": {
                            "choice": "chat",
                            "confidence": 0.99,
                            "probabilities": {
                                "chat": 0.99,
                                "assistant": 0.005,
                                "developer": 0.005,
                            },
                        }
                    },
                    "usage": {"input_tokens": 10, "output_tokens": 1, "cost": 0.0},
                }
            ).encode()

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = http_request.headers.get("Authorization")
        captured["payload"] = json.loads(http_request.data.decode())
        return Response()

    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-test-key")
    monkeypatch.setattr("model_gateway.main.urllib.request.urlopen", fake_urlopen)

    result = real_decision(request("Explain indexes"))

    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["authorization"] == "Bearer secret-test-key"
    assert captured["payload"]["model"] == "typesafe/jev-1.13"
    assert set(captured["payload"]) == {"model", "state", "questions"}
    assert result.answers["route"]["choice"] == "chat"
