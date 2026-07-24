from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from harness.developer_pipeline import (
    StageModelCallResult,
    run_developer_pipeline,
)
from harness.developer_workspace import prepare_developer_workspace
from harness.mcp_broker import McpBrokerError, McpToolBroker
from harness.run_store import update_run
from harness.tools.model_proposals import (
    ModelProposalError,
    parse_model_proposal,
    tool_instruction_block,
)
from harness.tools.registry import (
    enabled_deterministic_adapters,
    format_tool_result,
    parse_deterministic_tool_invocation,
)
from harness.tools.runtime import ToolCommandError, execute_tool_invocation
from harness.workflow_registry import WorkflowRegistryEntry, load_yaml_file, resolve_contract_path


@dataclass(frozen=True)
class AgentRuntimeRequest:
    session_id: str
    turn: int
    run_id: str
    workflow_entry: WorkflowRegistryEntry
    messages: list[dict[str, str]]
    safeplane_home: Path
    safeplane_config_path: Path
    model_gateway_url: str
    repository_profile: str | None = None


@dataclass(frozen=True)
class AgentRuntimeResponse:
    status: str
    final_message: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_dir(safeplane_home: Path, session_id: str, turn: int) -> Path:
    path = safeplane_home / "traces" / session_id / f"turn_{turn:03d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_runtime_trace(
    *,
    safeplane_home: Path,
    session_id: str,
    turn: int,
    run_id: str,
    workflow_id: str,
    event: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    artifact_refs: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    record = {
        "ts": utc_now(),
        "session_id": session_id,
        "turn": turn,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "component": "agent-runtime",
        "event": event,
        "input": input_data or {},
        "output": output_data or {},
        "artifact_refs": artifact_refs or [],
        "error": error,
    }

    path = trace_dir(safeplane_home, session_id, turn) / "agent-runtime.trace.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_markdown_with_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    raw = path.read_text(encoding="utf-8")

    if not raw.startswith("---\n"):
        return {}, raw

    parts = raw.split("---\n", 2)

    if len(parts) < 3:
        return {}, raw

    frontmatter_raw = parts[1]
    body = parts[2].lstrip("\n")
    frontmatter = yaml.safe_load(frontmatter_raw) or {}

    return frontmatter, body


def resolve_runtime_path(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return config_path.parent / path


def load_prompt(
    *,
    contract: dict[str, Any],
    config_path: Path,
) -> tuple[dict[str, Any], str, Path]:
    prompt_config = contract.get("prompt", {})
    prompt_path_raw = prompt_config.get("path")

    if not prompt_path_raw:
        raise ValueError("Workflow contract is missing prompt.path")

    prompt_path = resolve_runtime_path(config_path, str(prompt_path_raw))
    frontmatter, body = parse_markdown_with_frontmatter(prompt_path)

    return frontmatter, body, prompt_path


def redact_external_skill_content_for_artifact(
    stage_id: str,
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    if stage_id not in {"baseline_documentation", "final_documentation"}:
        return messages
    redacted = [dict(message) for message in messages]
    for message in redacted:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(str(message.get("content") or ""))
        except json.JSONDecodeError:
            continue
        evidence = (payload.get("input_artifacts") or {}).get("documentation_evidence")
        if not isinstance(evidence, dict):
            continue
        skill_files = evidence.get("skill_files")
        if isinstance(skill_files, list):
            for item in skill_files:
                if isinstance(item, dict) and "content" in item:
                    item["content"] = "[external skill content supplied at runtime; not persisted]"
        message["content"] = json.dumps(payload, ensure_ascii=False, indent=2)
    return redacted


def write_messages_artifact(
    *,
    safeplane_home: Path,
    session_id: str,
    turn: int,
    workflow_id: str,
    messages: list[dict[str, str]],
    artifact_name: str = "messages.full.json",
) -> str:
    artifact_path = trace_dir(safeplane_home, session_id, turn) / artifact_name

    artifact = {
        "session_id": session_id,
        "turn": turn,
        "workflow_id": workflow_id,
        "message_role_schema": "llm_chat_roles",
        "messages": messages,
    }

    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return artifact_name


def call_model_gateway(
    *,
    model_gateway_url: str,
    session_id: str,
    turn: int,
    workflow_id: str,
    model_profile: str,
    messages: list[dict[str, str]],
    stage_id: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    payload = {
        "workflow_id": workflow_id,
        "model_profile": model_profile,
        "stage_id": stage_id,
        "session_id": session_id,
        "turn": turn,
        "messages": messages,
        "timeout_seconds": timeout_seconds,
    }

    request = urllib.request.Request(
        model_gateway_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds + 5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model gateway HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Model gateway connection error: {exc}") from exc


def latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def parse_delay_seconds(message: str) -> int:
    try:
        delay = int(message.strip())
    except ValueError:
        delay = 5

    return max(1, min(delay, 30))


def is_model_free_workflow(contract: dict[str, Any]) -> bool:
    default_profile = contract.get("model_profiles", {}).get("default", {})
    return str(default_profile.get("litellm_model", "")).lower() == "none"


def run_deterministic_tool_invocation(
    request: AgentRuntimeRequest,
    contract: dict[str, Any],
) -> AgentRuntimeResponse | None:
    workflow_id = request.workflow_entry.workflow_id
    user_message = latest_user_message(request.messages)
    enabled_adapters = enabled_deterministic_adapters(contract)

    invocation = parse_deterministic_tool_invocation(
        message=user_message,
        enabled_adapters=enabled_adapters,
    )

    if invocation is None:
        return None

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="deterministic_tool_invocation_detected",
        input_data={
            "source": invocation.source,
            "adapter_id": invocation.adapter_id,
            "server_id": invocation.server_id,
            "tool_name": invocation.tool_name,
            "arguments": invocation.arguments,
        },
    )

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="tool_invocation_started",
        input_data={
            "source": invocation.source,
            "adapter_id": invocation.adapter_id,
            "server_id": invocation.server_id,
            "tool_name": invocation.tool_name,
        },
    )

    result = execute_tool_invocation(
        invocation=invocation,
        workflow_id=workflow_id,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        safeplane_home=request.safeplane_home,
        safeplane_config_path=request.safeplane_config_path,
        connector="harness-agent-runtime",
    )

    final_message = format_tool_result(result)

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="tool_invocation_completed",
        output_data={
            "source": invocation.source,
            "adapter_id": invocation.adapter_id,
            "server_id": result.server_id,
            "tool_name": result.tool_name,
            "is_error": result.is_error,
            "final_message_length": len(final_message),
        },
    )

    return AgentRuntimeResponse(
        status="completed",
        final_message=final_message,
    )


def run_model_free_workflow(
    request: AgentRuntimeRequest,
    contract: dict[str, Any],
) -> AgentRuntimeResponse:
    workflow_id = request.workflow_entry.workflow_id
    user_message = latest_user_message(request.messages)
    delay = parse_delay_seconds(user_message)

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="model_free_runtime_started",
        input_data={
            "delay_seconds": delay,
            "message_count": len(request.messages),
        },
    )

    time.sleep(delay)

    final_message = f"[slow workflow] Slept for {delay} seconds."

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="model_free_runtime_completed",
        output_data={
            "status": "completed",
            "final_message_length": len(final_message),
        },
    )

    return AgentRuntimeResponse(
        status="completed",
        final_message=final_message,
    )


def workflow_has_model_tools(contract: dict[str, Any]) -> bool:
    return bool(contract.get("mcp", {}).get("allowed_servers", {}))


def max_tool_call_retries(contract: dict[str, Any]) -> int:
    raw_value = contract.get("mcp", {}).get("max_tool_call_retries", 5)

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 5

    return max(0, value)


def runtime_timezone_name(contract: dict[str, Any]) -> str:
    runtime_context = contract.get("runtime_context", {})
    return str(runtime_context.get("timezone", "Europe/Berlin"))


def runtime_time_context_block(
    contract: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> str:
    timezone_name = runtime_timezone_name(contract)
    local_timezone = ZoneInfo(timezone_name)
    current_utc = now_utc or datetime.now(UTC)

    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=UTC)

    current_local = current_utc.astimezone(local_timezone).replace(microsecond=0)

    return (
        "Runtime time context:\n"
        f"- Current local datetime: {current_local.isoformat()}\n"
        f"- Current local date: {current_local.date().isoformat()}\n"
        f"- Current local weekday: {current_local.strftime('%A')}\n"
        f"- Timezone: {timezone_name}\n\n"
        "Resolve relative date/time phrases such as today, tomorrow, yesterday, "
        "and weekday names using this runtime context. Never copy a date from an "
        "example unless the user explicitly specified that date."
    )


def append_runtime_time_context(
    system_prompt: str,
    contract: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> str:
    context = runtime_time_context_block(contract, now_utc=now_utc)
    return system_prompt.rstrip() + "\n\n" + context.strip() + "\n"


def append_tool_instructions(system_prompt: str, contract: dict[str, Any]) -> str:
    instructions = tool_instruction_block(contract)

    if not instructions:
        return system_prompt

    return system_prompt.rstrip() + "\n\n" + instructions.strip() + "\n"


def parse_gateway_content_as_model_proposal(
    *,
    content: str,
    contract: dict[str, Any],
) -> Any:
    return parse_model_proposal(
        content=content,
        contract=contract,
    )


def append_repair_message(
    *,
    messages: list[dict[str, str]],
    error_message: str,
) -> list[dict[str, str]]:
    repair_message = {
        "role": "user",
        "content": (
            "Your previous response did not match the required Safeplane JSON schema.\n"
            f"Validation error:\n{error_message}\n\n"
            "Return only corrected JSON. Do not use Markdown."
        ),
    }

    return [*messages, repair_message]


def model_metadata_from_gateway_response(response: dict[str, Any]) -> dict[str, Any]:
    model = response.get("model", {}) or {}
    usage = response.get("usage", {}) or {}

    return {
        "model_mode": model.get("mode"),
        "configured_model": model.get("configured_model"),
        "actual_model": model.get("actual_model"),
        "actual_provider": model.get("actual_provider"),
        "generation_id": model.get("generation_id"),
        "finish_reason": response.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost": usage.get("cost"),
    }


def run_model_tool_loop(
    *,
    request: AgentRuntimeRequest,
    contract: dict[str, Any],
    model_messages: list[dict[str, str]],
    model_profile: str,
) -> AgentRuntimeResponse:
    workflow_id = request.workflow_entry.workflow_id
    attempts: list[str] = []
    retry_budget = max_tool_call_retries(contract)
    current_messages = list(model_messages)

    for attempt_index in range(retry_budget + 1):
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_proposal_call_started",
            input_data={
                "attempt": attempt_index + 1,
                "max_attempts": retry_budget + 1,
            },
        )

        gateway_response = call_model_gateway(
            model_gateway_url=request.model_gateway_url,
            session_id=request.session_id,
            turn=request.turn,
            workflow_id=workflow_id,
            model_profile=model_profile,
            messages=current_messages,
        )

        content = gateway_response["message"]["content"]

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_proposal_call_completed",
            output_data={
                "attempt": attempt_index + 1,
                "response_length": len(content),
                **model_metadata_from_gateway_response(gateway_response),
            },
        )

        try:
            parsed = parse_gateway_content_as_model_proposal(
                content=content,
                contract=contract,
            )
        except ModelProposalError as exc:
            attempts.append(str(exc))

            write_runtime_trace(
                safeplane_home=request.safeplane_home,
                session_id=request.session_id,
                turn=request.turn,
                run_id=request.run_id,
                workflow_id=workflow_id,
                event="model_tool_proposal_invalid",
                output_data={
                    "attempt": attempt_index + 1,
                    "remaining_retries": retry_budget - attempt_index,
                },
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )

            if attempt_index >= retry_budget:
                final_message = (
                    "I could not produce a valid tool call after "
                    f"{retry_budget + 1} attempt(s)."
                )

                return AgentRuntimeResponse(
                    status="completed",
                    final_message=final_message,
                )

            current_messages = append_repair_message(
                messages=current_messages,
                error_message=str(exc),
            )
            continue

        if parsed.type == "final":
            assert parsed.message is not None

            write_runtime_trace(
                safeplane_home=request.safeplane_home,
                session_id=request.session_id,
                turn=request.turn,
                run_id=request.run_id,
                workflow_id=workflow_id,
                event="model_final_response_received",
                output_data={
                    "attempt": attempt_index + 1,
                    "message_length": len(parsed.message),
                },
            )

            return AgentRuntimeResponse(
                status="completed",
                final_message=parsed.message,
            )

        invocation = parsed.invocation
        assert invocation is not None

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_invocation_validated",
            output_data={
                "attempt": attempt_index + 1,
                "source": invocation.source,
                "adapter_id": invocation.adapter_id,
                "server_id": invocation.server_id,
                "tool_name": invocation.tool_name,
            },
        )

        result = execute_tool_invocation(
            invocation=invocation,
            workflow_id=workflow_id,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            safeplane_home=request.safeplane_home,
            safeplane_config_path=request.safeplane_config_path,
            connector="harness-agent-runtime",
        )

        deterministic_fallback = format_tool_result(result)

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_invocation_completed",
            output_data={
                "source": invocation.source,
                "adapter_id": invocation.adapter_id,
                "server_id": result.server_id,
                "tool_name": result.tool_name,
                "is_error": result.is_error,
            },
        )

        final_messages = [
            *current_messages,
            {
                "role": "assistant",
                "content": content,
            },
            {
                "role": "user",
                "content": (
                    "The harness executed the tool successfully.\n"
                    "Tool result JSON:\n"
                    f"{json.dumps(result.structured_content, ensure_ascii=False, indent=2)}\n\n"
                    "Return only final JSON with this shape:\n"
                    '{"type":"final","message":"..."}'
                ),
            },
        ]

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_final_response_call_started",
            input_data={
                "tool_name": result.tool_name,
            },
        )

        final_gateway_response = call_model_gateway(
            model_gateway_url=request.model_gateway_url,
            session_id=request.session_id,
            turn=request.turn,
            workflow_id=workflow_id,
            model_profile=model_profile,
            messages=final_messages,
        )

        final_content = final_gateway_response["message"]["content"]

        try:
            final_parsed = parse_model_proposal(
                content=final_content,
                contract=contract,
            )

            if final_parsed.type == "final" and final_parsed.message:
                final_message = final_parsed.message
            else:
                final_message = deterministic_fallback

        except ModelProposalError:
            final_message = final_content.strip() or deterministic_fallback

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="model_tool_final_response_call_completed",
            output_data={
                "tool_name": result.tool_name,
                "final_message_length": len(final_message),
                **model_metadata_from_gateway_response(final_gateway_response),
            },
        )

        return AgentRuntimeResponse(
            status="completed",
            final_message=final_message,
        )

    return AgentRuntimeResponse(
        status="completed",
        final_message="I could not complete the tool loop.",
    )


def run_model_gateway_workflow(
    request: AgentRuntimeRequest,
    contract: dict[str, Any],
) -> AgentRuntimeResponse:
    workflow_id = request.workflow_entry.workflow_id

    prompt_frontmatter, system_prompt, prompt_path = load_prompt(
        contract=contract,
        config_path=request.safeplane_config_path,
    )

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="prompt_loaded",
        input_data={
            "prompt_path": str(prompt_path),
        },
        output_data={
            "prompt_id": prompt_frontmatter.get("prompt_id"),
            "version": prompt_frontmatter.get("version"),
            "description": prompt_frontmatter.get("description"),
        },
    )

    system_prompt = append_runtime_time_context(system_prompt, contract)
    system_prompt = append_tool_instructions(system_prompt, contract)

    model_messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *request.messages,
    ]

    messages_artifact = write_messages_artifact(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        workflow_id=workflow_id,
        messages=model_messages,
    )

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="model_messages_prepared",
        output_data={
            "message_count": len(model_messages),
            "conversation_message_count": len(request.messages),
        },
        artifact_refs=[messages_artifact],
    )

    model_profile = "default"

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="model_gateway_call_started",
        input_data={
            "workflow_id": workflow_id,
            "model_profile": model_profile,
            "model_gateway_url": request.model_gateway_url,
        },
    )

    gateway_response = call_model_gateway(
        model_gateway_url=request.model_gateway_url,
        session_id=request.session_id,
        turn=request.turn,
        workflow_id=workflow_id,
        model_profile=model_profile,
        messages=model_messages,
    )

    final_message = gateway_response["message"]["content"]
    model_mode = gateway_response.get("model", {}).get("mode")

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="model_gateway_call_completed",
        output_data={
            "response_length": len(final_message),
            "model_mode": model_mode,
            "configured_model": gateway_response.get("model", {}).get("configured_model"),
        },
    )

    if workflow_has_model_tools(contract) and model_mode != "fake":
        try:
            parsed = parse_gateway_content_as_model_proposal(
                content=final_message,
                contract=contract,
            )
        except ModelProposalError:
            return run_model_tool_loop(
                request=request,
                contract=contract,
                model_messages=model_messages,
                model_profile=model_profile,
            )

        if parsed.type == "final" and parsed.message is not None:
            return AgentRuntimeResponse(
                status="completed",
                final_message=parsed.message,
            )

        # The first model call already produced a valid tool call. Reuse it by
        # running the loop with no repair state and allowing the loop to call
        # the model again. This keeps traces simple and avoids duplicating the
        # execution path.
        return run_model_tool_loop(
            request=request,
            contract=contract,
            model_messages=model_messages,
            model_profile=model_profile,
        )

    return AgentRuntimeResponse(
        status="completed",
        final_message=final_message,
    )


def run_developer_pipeline_workflow(
    request: AgentRuntimeRequest,
    contract: dict[str, Any],
    workspace_manifest: dict[str, Any],
) -> AgentRuntimeResponse:
    workflow_id = request.workflow_entry.workflow_id

    def trace(
        event: str,
        input_data: dict[str, Any] | None,
        output_data: dict[str, Any] | None,
        artifact_refs: list[str] | None,
        error: dict[str, Any] | None,
    ) -> None:
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event=event,
            input_data=input_data,
            output_data=output_data,
            artifact_refs=artifact_refs,
            error=error,
        )

    def call_stage_model(
        stage_id: str,
        response_key: str,
        model_profile: str,
        messages: list[dict[str, str]],
    ) -> StageModelCallResult:
        artifact_name = f"messages.developer.{stage_id}.json"
        messages_ref = write_messages_artifact(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            workflow_id=workflow_id,
            messages=redact_external_skill_content_for_artifact(stage_id, messages),
            artifact_name=artifact_name,
        )
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="developer_pipeline_model_call_started",
            input_data={
                "stage_id": stage_id,
                "response_key": response_key,
                "model_profile": model_profile,
                "message_count": len(messages),
                "request_timeout_seconds": int(
                    contract["model_profiles"][model_profile].get(
                        "request_timeout_seconds", 30
                    )
                ),
            },
            artifact_refs=[messages_ref],
        )
        profile = contract["model_profiles"][model_profile]
        timeout_seconds = int(profile.get("request_timeout_seconds", 30))
        response = call_model_gateway(
            model_gateway_url=request.model_gateway_url,
            session_id=request.session_id,
            turn=request.turn,
            workflow_id=workflow_id,
            model_profile=model_profile,
            messages=messages,
            stage_id=response_key,
            timeout_seconds=timeout_seconds,
        )
        model = dict(response.get("model") or {})
        content = str((response.get("message") or {}).get("content") or "")
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="developer_pipeline_model_call_completed",
            input_data={
                "stage_id": stage_id,
                "response_key": response_key,
                "model_profile": model_profile,
            },
            output_data={
                **model_metadata_from_gateway_response(response),
                "response_length": len(content),
            },
            artifact_refs=[messages_ref],
        )
        return StageModelCallResult(
            content=content,
            model=model,
            usage=response.get("usage"),
            finish_reason=response.get("finish_reason"),
        )

    def call_stage_tool(
        stage_id: str,
        agent_id: str | None,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        approval_id: str | None,
        approval_token: str | None,
    ) -> dict[str, Any]:
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="developer_pipeline_tool_call_started",
            input_data={
                "stage_id": stage_id,
                "agent_id": agent_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "approval_id": approval_id,
            },
        )
        broker = McpToolBroker(
            config_path=request.safeplane_config_path,
            safeplane_home=request.safeplane_home,
        )
        raw_request: dict[str, Any] = {
            "workflow_id": workflow_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "session_id": request.session_id,
            "turn": request.turn,
            "run_id": request.run_id,
            "connector": f"developer-pipeline:{stage_id}",
        }
        if agent_id is not None:
            raw_request["agent_id"] = agent_id
        if approval_id is not None:
            raw_request["approval_id"] = approval_id
        if approval_token is not None:
            raw_request["approval_token"] = approval_token
        response = broker.call_tool(raw_request)
        content = dict(response.structured_content)
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="developer_pipeline_tool_call_completed",
            input_data={
                "stage_id": stage_id,
                "agent_id": agent_id,
                "server_id": server_id,
                "tool_name": tool_name,
            },
            output_data={
                "evidence_ref": content.get("evidence_ref"),
                "artifact_ref": content.get("artifact_ref"),
                "exit_code": content.get("exit_code"),
            },
            artifact_refs=[
                str(ref)
                for ref in (content.get("evidence_ref"), content.get("artifact_ref"))
                if ref
            ],
        )
        return content

    result = run_developer_pipeline(
        contract=contract,
        config_path=request.safeplane_config_path,
        safeplane_home=request.safeplane_home,
        run_id=request.run_id,
        operator_message=latest_user_message(request.messages),
        workspace_manifest=workspace_manifest,
        call_stage_model=call_stage_model,
        trace=trace,
        call_stage_tool=call_stage_tool,
    )
    return AgentRuntimeResponse(status="completed", final_message=result.final_message)


def ensure_developer_workspace_ready(
    *,
    request: AgentRuntimeRequest,
    workflow_id: str,
    workspace_manifest: dict[str, Any],
) -> dict[str, Any] | None:
    if workspace_manifest.get("workspace_kind") != "git_multi_repository":
        return None

    broker = McpToolBroker(
        config_path=request.safeplane_config_path,
        safeplane_home=request.safeplane_home,
        timeout_seconds=20.0,
    )
    response = broker.call_tool(
        {
            "workflow_id": workflow_id,
            "server_id": "dev-workspace",
            "tool_name": "dev_workspace_ready",
            "arguments": {"timeout_seconds": 15},
            "session_id": request.session_id,
            "turn": request.turn,
            "run_id": request.run_id,
            "connector": "developer-workspace-setup",
        }
    )
    ready = dict(response.structured_content)

    target = workspace_manifest.get("target") or {}
    expected_target_commit = str(target.get("resolved_commit") or "").lower()
    if ready.get("target_commit") != expected_target_commit:
        raise RuntimeError("prepared target commit is not visible through the MCP boundary")

    expected_sources = {
        str(source_id): str(source.get("resolved_commit") or "").lower()
        for source_id, source in (workspace_manifest.get("external_sources") or {}).items()
    }
    if ready.get("external_source_commits") != expected_sources:
        raise RuntimeError("prepared external source commits are not visible through the MCP boundary")

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="developer_workspace_ready",
        output_data={
            "target_commit": ready.get("target_commit"),
            "external_source_commits": ready.get("external_source_commits"),
            "workspace_version": ready.get("workspace_version"),
        },
        artifact_refs=[
            str(ref)
            for ref in (ready.get("evidence_ref"), workspace_manifest.get("manifest_ref"))
            if ref
        ],
    )
    return ready


def run_agent_runtime(request: AgentRuntimeRequest) -> AgentRuntimeResponse:
    workflow_id = request.workflow_entry.workflow_id
    contract_path = resolve_contract_path(
        request.safeplane_config_path,
        request.workflow_entry.contract_path,
    )

    write_runtime_trace(
        safeplane_home=request.safeplane_home,
        session_id=request.session_id,
        turn=request.turn,
        run_id=request.run_id,
        workflow_id=workflow_id,
        event="agent_runtime_started",
        input_data={
            "workflow_id": workflow_id,
            "entrypoint": request.workflow_entry.entrypoint_name,
            "conversation_message_count": len(request.messages),
        },
    )

    try:
        contract = load_yaml_file(contract_path)

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="workflow_contract_loaded",
            output_data={
                "workflow_id": workflow_id,
                "contract_path": str(contract_path),
            },
        )

        workspace_manifest = prepare_developer_workspace(
            contract=contract,
            safeplane_home=request.safeplane_home,
            run_id=request.run_id,
            entrypoint_name=request.workflow_entry.entrypoint_name,
            repository_profile=request.repository_profile,
        )
        if workspace_manifest is not None:
            ensure_developer_workspace_ready(
                request=request,
                workflow_id=workflow_id,
                workspace_manifest=workspace_manifest,
            )
            target = workspace_manifest.get("target") or {}
            external_sources = workspace_manifest.get("external_sources") or {}
            update_run(
                request.safeplane_home,
                request.run_id,
                repository_workspace={
                    "workspace_kind": workspace_manifest.get(
                        "workspace_kind", "local_snapshot"
                    ),
                    "manifest_ref": workspace_manifest.get("manifest_ref"),
                    "repository_profile": target.get("profile_id"),
                    "target_commit": target.get("resolved_commit"),
                    "external_source_commits": {
                        source_id: source.get("resolved_commit")
                        for source_id, source in external_sources.items()
                    },
                },
            )
            write_runtime_trace(
                safeplane_home=request.safeplane_home,
                session_id=request.session_id,
                turn=request.turn,
                run_id=request.run_id,
                workflow_id=workflow_id,
                event="developer_workspace_prepared",
                output_data={
                    "workspace_kind": workspace_manifest.get("workspace_kind", "local_snapshot"),
                    "repository_profile": (
                        (workspace_manifest.get("target") or {}).get("profile_id")
                    ),
                    "repository_root": workspace_manifest["repository_root"],
                    "container_logical_root": workspace_manifest["container_logical_root"],
                    "read_only": workspace_manifest["read_only"],
                    "excluded_names": workspace_manifest.get("excluded_names", []),
                    "target_commit": (
                        (workspace_manifest.get("target") or {}).get("resolved_commit")
                    ),
                    "external_source_commits": {
                        source_id: source.get("resolved_commit")
                        for source_id, source in (
                            workspace_manifest.get("external_sources") or {}
                        ).items()
                    },
                },
                artifact_refs=[workspace_manifest["manifest_ref"]],
            )

        if request.workflow_entry.entrypoint_name == "develop":
            if workspace_manifest is None:
                raise RuntimeError("developer pipeline requires a prepared workspace")
            response = run_developer_pipeline_workflow(request, contract, workspace_manifest)
            mode = "developer_pipeline"
        else:
            tool_response = run_deterministic_tool_invocation(request, contract)

            if tool_response is not None:
                write_runtime_trace(
                    safeplane_home=request.safeplane_home,
                    session_id=request.session_id,
                    turn=request.turn,
                    run_id=request.run_id,
                    workflow_id=workflow_id,
                    event="agent_runtime_completed",
                    output_data={
                        "status": tool_response.status,
                        "final_message_length": len(tool_response.final_message),
                        "mode": "deterministic_tool_invocation",
                    },
                )
                return tool_response

            if is_model_free_workflow(contract):
                response = run_model_free_workflow(request, contract)
                mode = "model_free"
            else:
                response = run_model_gateway_workflow(request, contract)
                mode = "model_gateway"

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="agent_runtime_completed",
            output_data={
                "status": response.status,
                "final_message_length": len(response.final_message),
                "mode": mode,
            },
        )

        return response

    except ToolCommandError as exc:
        final_message = f"Tool command error: {exc}"

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="deterministic_tool_command_error",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )

        return AgentRuntimeResponse(
            status="completed",
            final_message=final_message,
        )

    except McpBrokerError as exc:
        # A staged developer pipeline must fail visibly when a required MCP
        # operation fails. Converting the error into a successful chat message
        # would leave a partial pipeline while the run is marked completed.
        if request.workflow_entry.entrypoint_name == "develop":
            raise
        final_message = f"Tool execution error: {exc}"

        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="tool_execution_error",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )

        return AgentRuntimeResponse(
            status="completed",
            final_message=final_message,
        )

    except Exception as exc:
        write_runtime_trace(
            safeplane_home=request.safeplane_home,
            session_id=request.session_id,
            turn=request.turn,
            run_id=request.run_id,
            workflow_id=workflow_id,
            event="agent_runtime_error",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise
