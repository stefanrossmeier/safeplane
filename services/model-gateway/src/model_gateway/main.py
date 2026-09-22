from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Safeplane Model Gateway")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    workflow_id: str
    model_profile: str = "default"
    stage_id: str | None = None
    messages: list[ChatMessage]
    session_id: str
    turn: int = Field(ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=3600)




class DecisionRequest(BaseModel):
    model: str = "typesafe/jev-1.13"
    state: dict[str, Any]
    questions: dict[str, Any]
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class DecisionResponse(BaseModel):
    id: str | None = None
    model: str
    provider: str | None = None
    answers: dict[str, Any]
    usage: dict[str, Any] | None = None

class GatewayModelInfo(BaseModel):
    mode: str
    configured_model: str | None = None
    actual_model: str | None = None
    actual_provider: str | None = None
    generation_id: str | None = None
    workflow_id: str
    model_profile: str


class ChatResponseMessage(BaseModel):
    role: Literal["assistant"]
    content: str


class ChatResponse(BaseModel):
    status: Literal["completed"]
    message: ChatResponseMessage
    model: GatewayModelInfo
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", "/data/safeplane")).expanduser()


def read_secret_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None

    return value or None


def openrouter_api_key() -> str | None:
    secret_file = Path(
        os.environ.get(
            "OPENROUTER_API_KEY_FILE",
            "/run/secrets/openrouter_api_key",
        )
    )

    return read_secret_file(secret_file) or os.environ.get("OPENROUTER_API_KEY")


def trace_dir(session_id: str, turn: int) -> Path:
    path = safeplane_home() / "traces" / session_id / f"turn_{turn:03d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_trace(
    session_id: str,
    turn: int,
    event: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    artifact_refs: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    event_record = {
        "ts": utc_now(),
        "session_id": session_id,
        "turn": turn,
        "component": "model-gateway",
        "event": event,
        "input": input_data or {},
        "output": output_data or {},
        "artifact_refs": artifact_refs or [],
        "error": error,
    }

    path = trace_dir(session_id, turn) / "model-gateway.trace.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event_record, ensure_ascii=False) + "\n")


def workflow_contract_path(workflow_id: str) -> Path:
    root = Path(os.environ.get("WORKFLOW_CONTRACT_ROOT", "/app/workflows"))
    return root / workflow_id / "workflow.yaml"


def model_profile_override_env(model_profile: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in model_profile.upper()
    )
    return f"SAFEPLANE_MODEL_PROFILE_{normalized}"


def load_model_profile(workflow_id: str, model_profile: str) -> dict[str, Any]:
    path = workflow_contract_path(workflow_id)

    if not path.exists():
        raise FileNotFoundError(f"Workflow contract not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        contract = yaml.safe_load(f)

    profiles = contract.get("model_profiles", {})
    profile = profiles.get(model_profile)

    if profile is None:
        raise KeyError(f"Model profile '{model_profile}' not found for workflow '{workflow_id}'")
    if not isinstance(profile, dict):
        raise TypeError(
            f"Model profile '{model_profile}' for workflow '{workflow_id}' must be a mapping"
        )

    resolved = dict(profile)
    override_env = model_profile_override_env(model_profile)
    override = (os.environ.get(override_env) or "").strip()
    if override:
        resolved["litellm_model"] = override
        resolved["model_override_env"] = override_env

    return resolved


def resolve_workflow_resource(workflow_id: str, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    contract_path = workflow_contract_path(workflow_id)
    app_root = contract_path.parents[2]
    return app_root / path


def normalize_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def latest_user_message(messages: list[ChatMessage]) -> str:
    user_messages = [message.content for message in messages if message.role == "user"]
    return user_messages[-1] if user_messages else ""


def response_to_plain_dict(response: Any) -> dict[str, Any]:
    try:
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        elif hasattr(response, "dict"):
            data = response.dict()
        elif isinstance(response, dict):
            data = response
        else:
            data = dict(response)
    except Exception:
        data = {
            "repr": repr(response),
            "type": type(response).__name__,
        }

    if not isinstance(data, dict):
        return {
            "repr": repr(response),
            "type": type(response).__name__,
        }

    return data


def nested_get(data: dict[str, Any], path: list[str]) -> Any:
    current: Any = data

    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    return current


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_assistant_content(content: Any) -> str:
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])

        if parts:
            return "\n".join(parts)

    return json.dumps(content, ensure_ascii=False, default=str)


def extract_model_response_metadata(
    response: Any,
    configured_model: str,
) -> dict[str, Any]:
    data = response_to_plain_dict(response)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

    hidden_params = data.get("_hidden_params")
    if not isinstance(hidden_params, dict):
        hidden_params = {}

    choices = data.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first_choice, dict):
        first_choice = {}

    metadata = {
        "configured_model": configured_model,
        "finish_reason": first_present(
            data.get("finish_reason"),
            first_choice.get("finish_reason"),
        ),
        "actual_model": first_present(
            data.get("model"),
            data.get("actual_model"),
            hidden_params.get("model"),
        ),
        "actual_provider": first_present(
            data.get("provider"),
            data.get("actual_provider"),
            data.get("llm_provider"),
            hidden_params.get("provider"),
            hidden_params.get("custom_llm_provider"),
        ),
        "generation_id": first_present(
            data.get("id"),
            data.get("generation_id"),
            hidden_params.get("generation_id"),
        ),
        "prompt_tokens": first_present(
            usage.get("prompt_tokens"),
            nested_get(data, ["token_usage", "prompt_tokens"]),
        ),
        "completion_tokens": first_present(
            usage.get("completion_tokens"),
            nested_get(data, ["token_usage", "completion_tokens"]),
        ),
        "total_tokens": first_present(
            usage.get("total_tokens"),
            nested_get(data, ["token_usage", "total_tokens"]),
        ),
        "cost": first_present(
            usage.get("cost"),
            data.get("cost"),
            data.get("response_cost"),
            hidden_params.get("response_cost"),
        ),
    }

    return metadata


def write_raw_model_response_artifact(
    session_id: str,
    turn: int,
    response: Any,
    stage_id: str | None = None,
) -> str:
    data = response_to_plain_dict(response)

    def safe_component(value: Any, fallback: str) -> str:
        rendered = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-.")
        return rendered[:120] or fallback

    stage_component = safe_component(stage_id, "stage")
    generation_component = safe_component(
        data.get("id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "response",
    )
    artifact_name = (
        f"model-response.raw.{stage_component}.{generation_component}.json"
    )
    artifact_path = trace_dir(session_id, turn) / artifact_name
    if artifact_path.exists():
        collision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        artifact_name = (
            f"model-response.raw.{stage_component}.{generation_component}."
            f"{collision}.json"
        )
        artifact_path = trace_dir(session_id, turn) / artifact_name
    serialized = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    artifact_path.write_text(serialized, encoding="utf-8")

    # Retain the historical latest-response alias for existing operators and
    # diagnostics while preserving every individual model attempt above.
    (trace_dir(session_id, turn) / "model-response.raw.json").write_text(
        serialized,
        encoding="utf-8",
    )

    return artifact_name


def fake_completion(
    request: ChatRequest,
    configured_model: str | None,
    profile: dict[str, Any],
) -> ChatResponse:
    fake_content = f"[fake {request.workflow_id}] {latest_user_message(request.messages)}"
    fake_responses = profile.get("fake_responses", {})
    if request.stage_id and isinstance(fake_responses, dict):
        response_path_raw = fake_responses.get(request.stage_id)
        if isinstance(response_path_raw, list):
            if not response_path_raw:
                raise ValueError(
                    f"Fake response sequence is empty for stage={request.stage_id}"
                )
            assistant_turns = sum(
                1 for message in request.messages if message.role == "assistant"
            )
            response_path_raw = response_path_raw[
                min(assistant_turns, len(response_path_raw) - 1)
            ]
        if response_path_raw:
            response_path = resolve_workflow_resource(
                request.workflow_id,
                str(response_path_raw),
            )
            if not response_path.exists():
                raise FileNotFoundError(
                    f"Fake response file not found for workflow={request.workflow_id}, "
                    f"profile={request.model_profile}, stage={request.stage_id}: {response_path}"
                )
            fake_content = response_path.read_text(encoding="utf-8").strip()

    return ChatResponse(
        status="completed",
        message=ChatResponseMessage(
            role="assistant",
            content=fake_content,
        ),
        model=GatewayModelInfo(
            mode="fake",
            configured_model=configured_model,
            actual_model=f"fake/{request.model_profile}",
            actual_provider="safeplane-fake",
            workflow_id=request.workflow_id,
            model_profile=request.model_profile,
        ),
    )


def real_completion(
    request: ChatRequest,
    profile: dict[str, Any],
    configured_model: str,
) -> tuple[ChatResponse, str, dict[str, Any]]:
    api_key = openrouter_api_key()

    if not api_key:
        raise RuntimeError(
            "OpenRouter API key is required when MODEL_GATEWAY_MODE=real. "
            "Expected /run/secrets/openrouter_api_key or OPENROUTER_API_KEY."
        )

    if not configured_model.startswith("openrouter/"):
        raise RuntimeError(
            "local chat foundation real mode only supports OpenRouter models. "
            f"Configured model was: {configured_model}"
        )

    try:
        from litellm import completion
    except Exception as exc:
        raise RuntimeError(f"LiteLLM import failed: {exc}") from exc

    messages = normalize_messages(request.messages)

    kwargs: dict[str, Any] = {
        "model": configured_model,
        "messages": messages,
        "api_key": api_key,
    }

    if "temperature" in profile:
        kwargs["temperature"] = profile["temperature"]

    if "max_tokens" in profile:
        kwargs["max_tokens"] = profile["max_tokens"]

    response_format = profile.get("response_format")
    if response_format == "json_object":
        kwargs["response_format"] = {"type": "json_object"}

    kwargs["timeout"] = request.timeout_seconds
    response = completion(**kwargs)

    raw_artifact = write_raw_model_response_artifact(
        session_id=request.session_id,
        turn=request.turn,
        response=response,
        stage_id=request.stage_id,
    )

    metadata = extract_model_response_metadata(
        response=response,
        configured_model=configured_model,
    )

    message = response["choices"][0]["message"]
    content = normalize_assistant_content(message.get("content"))

    chat_response = ChatResponse(
        status="completed",
        message=ChatResponseMessage(
            role="assistant",
            content=content,
        ),
        model=GatewayModelInfo(
            mode="real",
            configured_model=configured_model,
            actual_model=metadata.get("actual_model"),
            actual_provider=metadata.get("actual_provider"),
            generation_id=metadata.get("generation_id"),
            workflow_id=request.workflow_id,
            model_profile=request.model_profile,
        ),
        usage={
            "prompt_tokens": metadata.get("prompt_tokens"),
            "completion_tokens": metadata.get("completion_tokens"),
            "total_tokens": metadata.get("total_tokens"),
            "cost": metadata.get("cost"),
        },
        finish_reason=metadata.get("finish_reason"),
    )

    return chat_response, raw_artifact, metadata




def fake_decision(request: DecisionRequest) -> DecisionResponse:
    text = str(request.state.get("request") or "").lower()
    supplied_context = request.state.get("supplied_context")
    if not isinstance(supplied_context, dict):
        supplied_context = {}
    repository_profile = str(supplied_context.get("repository_profile") or "").strip()

    assistant_terms = (
        "remind", "reminder", "calendar", "meeting", "appointment", "notify",
        "notification", "schedule", "reschedule", "cancel my", "plan my day",
    )
    developer_terms = (
        "repository", "repo", "codebase", "patch", "pull request", "commit",
        "git ", "test failure", "failing test", "fix the bug", "implement in",
        "change the code", "update the code", "inspect the code",
    )
    assistant = any(term in text for term in assistant_terms)
    developer = any(term in text for term in developer_terms)
    multiple = assistant and developer
    identifiable = bool(text.strip())
    route = "developer" if developer else "assistant" if assistant else "chat"
    probabilities = {"chat": 0.005, "assistant": 0.005, "developer": 0.005}
    probabilities[route] = 0.99
    if not identifiable:
        probabilities = {"chat": 0.34, "assistant": 0.33, "developer": 0.33}

    return DecisionResponse(
        id="fake-routing-decision",
        model=request.model,
        provider="safeplane-fake",
        answers={
            "route": {
                "choice": route,
                "confidence": probabilities[route],
                "probabilities": probabilities,
            },
            "route_identifiable": {"noul": 0.99 if identifiable else 0.01},
            "needs_clarification_before_execution": {"noul": 0.05},
            "requires_multiple_workflows": {"noul": 0.99 if multiple else 0.01},
            "repository_work": {"noul": 0.99 if developer else 0.01},
            "missing_repository_profile": {
                "noul": 0.99 if developer and not repository_profile else 0.01
            },
            "assistant_tool_need": {"noul": 0.99 if assistant else 0.01},
        },
        usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
        },
    )


def real_decision(request: DecisionRequest) -> DecisionResponse:
    api_key = openrouter_api_key()
    if not api_key:
        raise RuntimeError(
            "OpenRouter API key is required for real routing decisions. "
            "Expected /run/secrets/openrouter_api_key or OPENROUTER_API_KEY."
        )

    url = os.environ.get(
        "OPENROUTER_DECISIONS_URL",
        "https://openrouter.ai/api/alpha/decisions",
    )
    payload = {
        "model": request.model,
        "state": request.state,
        "questions": request.questions,
    }
    encoded = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    retryable = {429, 500, 502, 503, 524, 529}

    for attempt in range(4):
        http_request = urllib.request.Request(
            url,
            data=encoded,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/stefanrossmeier/safeplane",
                "X-Title": "Safeplane routing advisor",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=request.timeout_seconds,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise RuntimeError("OpenRouter decision response must be an object")
            return DecisionResponse.model_validate(data)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"OpenRouter decisions HTTP {exc.code}: {body}"
            )
            if exc.code not in retryable or attempt == 3:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 3:
                break
        time.sleep(0.5 * (2**attempt))

    raise RuntimeError(f"OpenRouter decision request failed after retries: {last_error}")


@app.post("/decisions", response_model=DecisionResponse)
def decisions(request: DecisionRequest) -> DecisionResponse:
    try:
        mode = os.environ.get("MODEL_GATEWAY_MODE", "fake").lower()
        if mode == "fake":
            return fake_decision(request)
        if mode == "real":
            return real_decision(request)
        raise RuntimeError(f"Unsupported MODEL_GATEWAY_MODE: {mode}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "model-gateway",
        "mode": os.environ.get("MODEL_GATEWAY_MODE", "fake"),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    write_trace(
        session_id=request.session_id,
        turn=request.turn,
        event="model_request_received",
        input_data={
            "workflow_id": request.workflow_id,
            "model_profile": request.model_profile,
            "stage_id": request.stage_id,
            "message_count": len(request.messages),
            "timeout_seconds": request.timeout_seconds,
        },
    )

    try:
        profile = load_model_profile(request.workflow_id, request.model_profile)
        configured_model = profile.get("litellm_model")

        if not configured_model:
            raise RuntimeError(
                f"Missing litellm_model for workflow={request.workflow_id}, "
                f"profile={request.model_profile}"
            )

        write_trace(
            session_id=request.session_id,
            turn=request.turn,
            event="model_profile_resolved",
            output_data={
                "workflow_id": request.workflow_id,
                "model_profile": request.model_profile,
                "configured_model": configured_model,
                "response_format": profile.get("response_format"),
            },
        )

        mode = os.environ.get("MODEL_GATEWAY_MODE", "fake").lower()
        artifact_refs: list[str] = []
        model_metadata: dict[str, Any] = {}

        if mode == "fake":
            response = fake_completion(request, configured_model, profile)
        elif mode == "real":
            write_trace(
                session_id=request.session_id,
                turn=request.turn,
                event="real_model_call_started",
                input_data={
                    "provider": "openrouter",
                    "configured_model": configured_model,
                },
            )
            response, raw_artifact, model_metadata = real_completion(
                request,
                profile,
                configured_model,
            )
            artifact_refs.append(raw_artifact)
        else:
            raise RuntimeError(f"Unsupported MODEL_GATEWAY_MODE: {mode}")

        trace_output = {
            "mode": response.model.mode,
            "configured_model": response.model.configured_model,
            "stage_id": request.stage_id,
            "response_role": response.message.role,
            "response_length": len(response.message.content),
        }
        trace_output.update(model_metadata)

        write_trace(
            session_id=request.session_id,
            turn=request.turn,
            event="model_response_returned",
            output_data=trace_output,
            artifact_refs=artifact_refs,
        )

        return response

    except Exception as exc:
        write_trace(
            session_id=request.session_id,
            turn=request.turn,
            event="model_error",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
