from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_GATEWAY_SRC = REPO_ROOT / "services/model-gateway/src"
if str(MODEL_GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(MODEL_GATEWAY_SRC))



def load_model_gateway_main():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "model-gateway"
        / "src"
        / "model_gateway"
        / "main.py"
    )
    spec = importlib.util.spec_from_file_location("model_gateway_main", module_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_model_response_metadata_from_openrouter_like_response():
    module = load_model_gateway_main()

    response = {
        "id": "gen-test-123",
        "model": "tencent/hy3-20260706:free",
        "provider": "Novita",
        "usage": {
            "prompt_tokens": 62,
            "completion_tokens": 46,
            "total_tokens": 108,
            "cost": 0,
        },
    }

    metadata = module.extract_model_response_metadata(
        response=response,
        configured_model="openrouter/openrouter/free",
    )

    assert metadata == {
        "configured_model": "openrouter/openrouter/free",
        "actual_model": "tencent/hy3-20260706:free",
        "actual_provider": "Novita",
        "generation_id": "gen-test-123",
        "finish_reason": None,
        "prompt_tokens": 62,
        "completion_tokens": 46,
        "total_tokens": 108,
        "cost": 0,
    }


def test_extract_model_response_metadata_falls_back_to_hidden_params():
    module = load_model_gateway_main()

    response = {
        "id": "gen-hidden-123",
        "_hidden_params": {
            "custom_llm_provider": "openrouter",
            "response_cost": 0.001,
        },
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }

    metadata = module.extract_model_response_metadata(
        response=response,
        configured_model="openrouter/openrouter/free",
    )

    assert metadata["configured_model"] == "openrouter/openrouter/free"
    assert metadata["actual_provider"] == "openrouter"
    assert metadata["generation_id"] == "gen-hidden-123"
    assert metadata["prompt_tokens"] == 10
    assert metadata["completion_tokens"] == 5
    assert metadata["total_tokens"] == 15
    assert metadata["cost"] == 0.001


def test_normalize_assistant_content_handles_none() -> None:
    from model_gateway.main import normalize_assistant_content

    assert normalize_assistant_content(None) == ""


def test_normalize_assistant_content_handles_text_parts() -> None:
    from model_gateway.main import normalize_assistant_content

    assert normalize_assistant_content([{"text": "hello"}, {"text": "world"}]) == "hello\nworld"


def test_fake_completion_uses_profile_stage_response_file(tmp_path, monkeypatch) -> None:
    from model_gateway import main as module
    workflow_root = tmp_path / "workflows"
    contract_dir = workflow_root / "developer"
    contract_dir.mkdir(parents=True)
    (contract_dir / "workflow.yaml").write_text("model_profiles: {}\n", encoding="utf-8")
    response_path = tmp_path / "prompts" / "developer" / "fake.json"
    response_path.parent.mkdir(parents=True)
    response_path.write_text('{"verdict":"LGTM"}\n', encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_CONTRACT_ROOT", str(workflow_root))

    request = module.ChatRequest(
        workflow_id="developer",
        model_profile="developer_review",
        stage_id="review",
        session_id="sess_test",
        turn=1,
        messages=[module.ChatMessage(role="user", content="review")],
    )
    response = module.fake_completion(
        request,
        "openrouter/openrouter/free",
        {"fake_responses": {"review": "prompts/developer/fake.json"}},
    )

    assert response.message.content == '{"verdict":"LGTM"}'
    assert response.model.actual_model == "fake/developer_review"
    assert response.model.actual_provider == "safeplane-fake"


def test_model_profile_override_env_is_stable() -> None:
    from model_gateway import main as module

    assert (
        module.model_profile_override_env("developer_documentation")
        == "SAFEPLANE_MODEL_PROFILE_DEVELOPER_DOCUMENTATION"
    )


def test_load_model_profile_applies_operator_model_override(tmp_path, monkeypatch) -> None:
    from model_gateway import main as module

    workflow_root = tmp_path / "workflows"
    contract_dir = workflow_root / "developer"
    contract_dir.mkdir(parents=True)
    (contract_dir / "workflow.yaml").write_text(
        "model_profiles:\n"
        "  developer_analysis:\n"
        "    litellm_model: openrouter/openrouter/free\n"
        "    temperature: 0.2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKFLOW_CONTRACT_ROOT", str(workflow_root))
    monkeypatch.setenv(
        "SAFEPLANE_MODEL_PROFILE_DEVELOPER_ANALYSIS",
        "openrouter/example/analysis-model",
    )

    profile = module.load_model_profile("developer", "developer_analysis")

    assert profile["litellm_model"] == "openrouter/example/analysis-model"
    assert profile["temperature"] == 0.2
    assert profile["model_override_env"] == "SAFEPLANE_MODEL_PROFILE_DEVELOPER_ANALYSIS"


def test_empty_model_profile_override_keeps_contract_model(tmp_path, monkeypatch) -> None:
    from model_gateway import main as module

    workflow_root = tmp_path / "workflows"
    contract_dir = workflow_root / "developer"
    contract_dir.mkdir(parents=True)
    (contract_dir / "workflow.yaml").write_text(
        "model_profiles:\n"
        "  developer_review:\n"
        "    litellm_model: openrouter/openrouter/free\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKFLOW_CONTRACT_ROOT", str(workflow_root))
    monkeypatch.setenv("SAFEPLANE_MODEL_PROFILE_DEVELOPER_REVIEW", "")

    profile = module.load_model_profile("developer", "developer_review")

    assert profile["litellm_model"] == "openrouter/openrouter/free"
    assert "model_override_env" not in profile


def test_real_completion_passes_request_timeout_to_litellm(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from model_gateway import main as module

    observed: dict[str, object] = {}

    def fake_completion(**kwargs):
        observed.update(kwargs)
        return {
            "id": "gen-timeout-test",
            "model": "nvidia/nemotron-3-ultra-550b-a55b",
            "provider": "test-provider",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "{}"},
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost": 0,
            },
        }

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=fake_completion))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        module,
        "write_raw_model_response_artifact",
        lambda **kwargs: "model-response.raw.json",
    )

    request = module.ChatRequest(
        workflow_id="developer",
        model_profile="developer_documentation",
        stage_id="baseline_documentation",
        session_id="sess_test",
        turn=1,
        timeout_seconds=900,
        messages=[module.ChatMessage(role="user", content="document")],
    )

    response, _, _ = module.real_completion(
        request,
        {"temperature": 0.1, "max_tokens": 10000, "response_format": "json_object"},
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b",
    )

    assert observed["timeout"] == 900
    assert observed["response_format"] == {"type": "json_object"}
    assert response.message.content == "{}"


def test_raw_model_response_artifacts_preserve_each_attempt(
    monkeypatch, tmp_path
) -> None:
    from model_gateway import main as module

    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    first = module.write_raw_model_response_artifact(
        session_id="sess_test",
        turn=1,
        stage_id="baseline_documentation_preserve",
        response={"id": "gen-first", "choices": []},
    )
    second = module.write_raw_model_response_artifact(
        session_id="sess_test",
        turn=1,
        stage_id="baseline_documentation_preserve",
        response={"id": "gen-first", "choices": [{"index": 1}]},
    )

    trace = tmp_path / "traces" / "sess_test" / "turn_001"
    assert first != second
    assert json.loads((trace / first).read_text())["id"] == "gen-first"
    assert json.loads((trace / second).read_text())["choices"] == [{"index": 1}]
    assert json.loads((trace / "model-response.raw.json").read_text())["choices"] == [{"index": 1}]

def test_chat_request_accepts_one_hour_model_timeout() -> None:
    from model_gateway import main as module

    request = module.ChatRequest(
        workflow_id="developer",
        model_profile="developer_documentation",
        session_id="sess_test",
        turn=1,
        timeout_seconds=3600,
        messages=[module.ChatMessage(role="user", content="document")],
    )

    assert request.timeout_seconds == 3600


def test_fake_completion_advances_response_sequence_by_assistant_turns(
    tmp_path, monkeypatch
) -> None:
    from model_gateway import main as module

    workflow_root = tmp_path / "workflows"
    contract_dir = workflow_root / "developer"
    contract_dir.mkdir(parents=True)
    (contract_dir / "workflow.yaml").write_text("model_profiles: {}\n", encoding="utf-8")
    prompt_root = tmp_path / "prompts" / "developer"
    prompt_root.mkdir(parents=True)
    first = prompt_root / "first.json"
    second = prompt_root / "second.json"
    first.write_text('{"type":"tool_call"}\n', encoding="utf-8")
    second.write_text('{"type":"final"}\n', encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_CONTRACT_ROOT", str(workflow_root))

    profile = {
        "fake_responses": {
            "implementation": [
                "prompts/developer/first.json",
                "prompts/developer/second.json",
            ]
        }
    }
    first_request = module.ChatRequest(
        workflow_id="developer",
        model_profile="developer_implementation",
        stage_id="implementation",
        session_id="sess_test",
        turn=1,
        messages=[module.ChatMessage(role="user", content="implement")],
    )
    first_response = module.fake_completion(
        first_request,
        "openrouter/openrouter/free",
        profile,
    )
    assert first_response.message.content == '{"type":"tool_call"}'

    second_request = module.ChatRequest(
        workflow_id="developer",
        model_profile="developer_implementation",
        stage_id="implementation",
        session_id="sess_test",
        turn=1,
        messages=[
            module.ChatMessage(role="user", content="implement"),
            module.ChatMessage(role="assistant", content='{"type":"tool_call"}'),
            module.ChatMessage(role="user", content="tool result"),
        ],
    )
    second_response = module.fake_completion(
        second_request,
        "openrouter/openrouter/free",
        profile,
    )
    assert second_response.message.content == '{"type":"final"}'
