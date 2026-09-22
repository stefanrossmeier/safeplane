from __future__ import annotations

import json
from contextlib import asynccontextmanager
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from harness.agent_runtime import AgentRuntimeRequest, run_agent_runtime
from harness.remote_write import (
    RemoteWriteConflictError,
    RemoteWriteError,
    RemoteWritePolicyError,
    RemoteWriteResult,
    execute_remote_write,
)
from harness.routing_advisor import (
    RoutingAdvisorAbstainedError,
    RoutingAdvisorPrerequisiteError,
    RoutingAdvisorUnavailableError,
    RoutingDecision,
    route_message,
    write_routing_trace,
)
from harness.run_store import (
    TERMINAL_RUN_STATUSES,
    create_run,
    find_active_run_for_session,
    list_runs,
    load_run,
    mark_completed,
    mark_failed,
    mark_running,
    update_run,
)
from harness.patch_approval_store import (
    PatchApprovalConflictError,
    PatchApprovalError,
    cleanup_patch_apply_workspace,
    create_patch_approval,
    load_patch_proposal,
    prepare_patch_apply_workspace,
    publish_patch_apply_workspace,
    update_patch_approval,
)
from harness.workflow_registry import (
    DisabledWorkflowError,
    UnknownEntrypointError,
    WorkflowContractValidationError,
    build_registry,
    connector_is_exposed,
    connector_registry_entries,
    registry_entry_to_public_dict,
    resolve_contract_path,
    resolve_entrypoint_from_registry,
)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    recover_incomplete_developer_runs()
    yield


app = FastAPI(title="Safeplane Harness", lifespan=app_lifespan)

RUN_EXECUTOR = ThreadPoolExecutor(max_workers=8)
RUN_LOCK = threading.RLock()
REMOTE_WRITE_LOCKS_GUARD = threading.Lock()
REMOTE_WRITE_LOCKS: dict[str, threading.Lock] = {}


class ConnectorMessageRequest(BaseModel):
    connector: Literal["cli", "telegram"]
    message: str
    session_ref: str | None = None
    repository_profile: str | None = None


class ConnectorMessageResponse(BaseModel):
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    session_id: str
    session_display_id: str
    turn: int
    run_id: str
    workflow_id: str
    entrypoint: str
    final_message: str | None = None
    trace_path: str
    routing: dict[str, Any] | None = None


class PatchApprovalRequest(BaseModel):
    approved: Literal[True]


class PatchApprovalResponse(BaseModel):
    status: Literal["applied"]
    approval_id: str
    proposal_id: str
    run_id: str
    workspace_ref: str
    changed_files: list[dict[str, Any]]
    evidence_ref: str | None = None


class RemoteApprovalRequestBody(BaseModel):
    approved: Literal[True]
    connector: Literal["cli", "telegram"] = "cli"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", "/data/safeplane")).expanduser()


def safeplane_config_path() -> Path:
    return Path(os.environ.get("SAFEPLANE_CONFIG", "/app/safeplane.yaml"))


def ensure_runtime_dirs() -> None:
    home = safeplane_home()
    (home / "sessions").mkdir(parents=True, exist_ok=True)
    (home / "runs").mkdir(parents=True, exist_ok=True)
    (home / "traces").mkdir(parents=True, exist_ok=True)


def create_session_id() -> tuple[str, str]:
    session_uuid = str(uuid.uuid4())
    session_id = f"sess_{session_uuid}"
    session_display_id = session_uuid[:8]
    return session_id, session_display_id


def display_id_from_session_id(session_id: str) -> str:
    if not session_id.startswith("sess_"):
        return session_id[:8]
    return session_id.removeprefix("sess_")[:8]


def trace_dir(session_id: str, turn: int) -> Path:
    path = safeplane_home() / "traces" / session_id / f"turn_{turn:03d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(session_id: str) -> Path:
    return safeplane_home() / "sessions" / f"{session_id}.json"


def write_trace(
    session_id: str,
    turn: int,
    event: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    artifact_refs: list[str] | None = None,
    error: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> None:
    event_record = {
        "ts": utc_now(),
        "session_id": session_id,
        "turn": turn,
        "run_id": run_id,
        "component": "harness",
        "event": event,
        "input": input_data or {},
        "output": output_data or {},
        "artifact_refs": artifact_refs or [],
        "error": error,
    }

    path = trace_dir(session_id, turn) / "harness.trace.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event_record, ensure_ascii=False) + "\n")


def load_safeplane_config() -> dict[str, Any]:
    path = safeplane_config_path()

    if not path.exists():
        raise FileNotFoundError(f"Safeplane config not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_workflow_registry() -> dict[str, Any]:
    config = load_safeplane_config()
    return build_registry(config, safeplane_config_path())


def resolve_entrypoint(config: dict[str, Any], entrypoint_name: str) -> dict[str, Any]:
    registry = build_registry(config, safeplane_config_path())
    entry = resolve_entrypoint_from_registry(registry, entrypoint_name)

    return {
        "entrypoint_name": entry.entrypoint_name,
        "workflow_id": entry.workflow_id,
        "workflow": {
            "endpoint": entry.endpoint,
            "service": entry.service,
            "contract": entry.contract_path,
        },
        "registry_entry": entry,
    }


def load_session(session_id: str) -> dict[str, Any]:
    path = session_path(session_id)

    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")

    return json.loads(path.read_text(encoding="utf-8"))


def save_session(session: dict[str, Any]) -> None:
    session_id = session["session_id"]
    path = session_path(session_id)
    path.write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_session_reference(session_ref: str) -> dict[str, Any]:
    sessions_dir = safeplane_home() / "sessions"

    if session_ref.startswith("sess_"):
        try:
            return load_session(session_ref)
        except FileNotFoundError as exc:
            raise LookupError(f"Unknown session: {session_ref}") from exc

    matches = sorted(sessions_dir.glob(f"sess_{session_ref}*.json"))

    if not matches:
        raise LookupError(f"Unknown session: {session_ref}")

    if len(matches) > 1:
        matched_ids = [path.stem for path in matches]
        raise ValueError(
            f"Ambiguous session reference: {session_ref} matched {len(matches)} sessions: "
            + ", ".join(matched_ids)
        )

    return json.loads(matches[0].read_text(encoding="utf-8"))


def session_next_turn(session: dict[str, Any]) -> int:
    turns = session.get("turns", [])
    if not turns:
        return 1
    return max(int(turn["turn"]) for turn in turns) + 1


def session_history_messages(session: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for turn in sorted(session.get("turns", []), key=lambda item: int(item.get("turn", 0))):
        if turn.get("status") == "failed":
            continue

        user_message = turn.get("operator_message")
        assistant_message = turn.get("final_message")

        if user_message:
            messages.append(
                {
                    "role": "user",
                    "content": str(user_message),
                }
            )

        if assistant_message:
            messages.append(
                {
                    "role": "assistant",
                    "content": str(assistant_message),
                }
            )

    return messages


def create_session(connector: str, workflow_id: str) -> dict[str, Any]:
    now = utc_now()
    session_id, session_display_id = create_session_id()

    return {
        "session_id": session_id,
        "session_display_id": session_display_id,
        "workflow_id": workflow_id,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "connector": connector,
        "turns": [],
    }


def call_workflow(
    session_id: str,
    turn: int,
    run_id: str,
    messages: list[dict[str, str]],
    endpoint: str,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "turn": turn,
        "run_id": run_id,
        "messages": messages,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Workflow HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Workflow connection error: {exc}") from exc


def append_completed_session_turn(
    session: dict[str, Any],
    turn: int,
    operator_message: str,
    final_message: str,
    trace_path: Path,
    run_id: str,
) -> None:
    now = utc_now()

    session.setdefault("turns", []).append(
        {
            "turn": turn,
            "operator_message": operator_message,
            "final_message": final_message,
            "status": "completed",
            "runs": [
                {
                    "run_id": run_id,
                    "status": "completed",
                    "trace_path": str(trace_path),
                }
            ],
            "trace_path": str(trace_path),
            "created_at": now,
        }
    )

    session["updated_at"] = now
    session["status"] = "completed"


def append_failed_session_turn(
    session: dict[str, Any],
    turn: int,
    operator_message: str,
    trace_path: Path,
    run_id: str,
    error: dict[str, Any],
) -> None:
    now = utc_now()

    session.setdefault("turns", []).append(
        {
            "turn": turn,
            "operator_message": operator_message,
            "final_message": None,
            "status": "failed",
            "runs": [
                {
                    "run_id": run_id,
                    "status": "failed",
                    "trace_path": str(trace_path),
                    "error": error,
                }
            ],
            "trace_path": str(trace_path),
            "created_at": now,
        }
    )

    session["updated_at"] = now
    session["status"] = "failed"


def write_output_artifact(
    session_id: str,
    turn: int,
    run_id: str,
    final_message: str,
    session_display_id: str,
    workflow_id: str,
) -> str:
    output_path = trace_dir(session_id, turn) / "output.json"

    output = {
        "session_id": session_id,
        "session_display_id": session_display_id,
        "workflow_id": workflow_id,
        "turn": turn,
        "run_id": run_id,
        "status": "completed",
        "final_message": final_message,
    }

    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return "output.json"


def execute_run(
    *,
    run_id: str,
    session_id: str,
    session_display_id: str,
    turn: int,
    workflow_entry: Any,
    model_gateway_url: str,
    entrypoint_name: str,
    operator_message: str,
    history_messages: list[dict[str, str]],
    repository_profile: str | None,
) -> None:
    home = safeplane_home()
    current_trace_dir = trace_dir(session_id, turn)

    try:
        mark_running(home, run_id)

        workflow_id = workflow_entry.workflow_id

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="run_started",
            output_data={
                "run_id": run_id,
                "workflow_id": workflow_id,
                "entrypoint": entrypoint_name,
                "status": "running",
            },
        )

        messages = [
            *history_messages,
            {
                "role": "user",
                "content": operator_message,
            },
        ]

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="agent_runtime_call_started",
            input_data={
                "workflow_id": workflow_id,
                "runtime_owner": "harness",
                "message_count": len(messages),
            },
        )

        runtime_response = run_agent_runtime(
            AgentRuntimeRequest(
                session_id=session_id,
                turn=turn,
                run_id=run_id,
                workflow_entry=workflow_entry,
                messages=messages,
                safeplane_home=home,
                safeplane_config_path=safeplane_config_path(),
                model_gateway_url=model_gateway_url,
                repository_profile=repository_profile,
            )
        )

        final_message = runtime_response.final_message

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="agent_runtime_call_completed",
            output_data={
                "workflow_id": workflow_id,
                "status": runtime_response.status,
                "final_message_length": len(final_message),
            },
        )

        if (
            entrypoint_name == "develop"
            and _draft_pr_creation_mode(home, run_id) == "automatic"
        ):
            try:
                run_record = load_run(home, run_id)
                connector = str(run_record.get("connector") or "cli")
                if connector not in {"cli", "telegram"}:
                    connector = "cli"
                with REMOTE_WRITE_LOCKS_GUARD:
                    lock = REMOTE_WRITE_LOCKS.setdefault(run_id, threading.Lock())
                with lock:
                    result = execute_remote_write(
                        safeplane_home=home,
                        contract=_developer_contract(),
                        run_id=run_id,
                        connector=connector,
                        authorization_source="repository_policy",
                    )
                final_message = (
                    load_run(home, run_id).get("final_message")
                    or f"Draft pull request created: {result.pull_request_url}. Safeplane did not merge it."
                )
                write_trace(
                    session_id=session_id,
                    turn=turn,
                    run_id=run_id,
                    event="automatic_draft_pr_completed",
                    input_data={
                        "repository_profile": repository_profile,
                        "connector": connector,
                    },
                    output_data={
                        "pull_request_url": result.pull_request_url,
                        "branch_name": result.branch_name,
                        "draft": result.draft,
                        "merged": False,
                    },
                    artifact_refs=[result.approval_ref, result.evidence_ref],
                )
            except Exception as exc:
                detail = getattr(exc, "detail", str(exc))
                final_message = (
                    "Developer pipeline completed, but automatic draft PR creation failed. "
                    f"The immutable run remains available for retry: {detail}"
                )
                update_run(
                    home,
                    run_id,
                    final_message=final_message,
                    automatic_draft_pr_error={
                        "type": type(exc).__name__,
                        "message": str(detail),
                    },
                )
                write_trace(
                    session_id=session_id,
                    turn=turn,
                    run_id=run_id,
                    event="automatic_draft_pr_failed",
                    input_data={"repository_profile": repository_profile},
                    error={
                        "type": type(exc).__name__,
                        "message": str(detail),
                    },
                )

        with RUN_LOCK:
            session = load_session(session_id)
            append_completed_session_turn(
                session=session,
                turn=turn,
                operator_message=operator_message,
                final_message=final_message,
                trace_path=current_trace_dir,
                run_id=run_id,
            )
            save_session(session)

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="session_updated",
            output_data={
                "session_path": str(session_path(session_id)),
                "workflow_id": workflow_id,
                "turn_count": len(session.get("turns", [])),
                "status": session.get("status"),
            },
        )

        output_artifact = write_output_artifact(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            final_message=final_message,
            session_display_id=session_display_id,
            workflow_id=workflow_id,
        )

        mark_completed(
            home,
            run_id,
            final_message=final_message,
        )

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="run_completed",
            output_data={
                "run_id": run_id,
                "status": "completed",
                "session_display_id": session_display_id,
                "workflow_id": workflow_id,
                "turn": turn,
            },
            artifact_refs=[output_artifact],
        )

    except Exception as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

        mark_failed(
            home,
            run_id,
            error_type=error["type"],
            error_message=error["message"],
        )

        with RUN_LOCK:
            try:
                session = load_session(session_id)
                append_failed_session_turn(
                    session=session,
                    turn=turn,
                    operator_message=operator_message,
                    trace_path=current_trace_dir,
                    run_id=run_id,
                    error=error,
                )
                save_session(session)
            except Exception:
                pass

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="run_failed",
            error=error,
        )


def approve_patch_proposal(
    *,
    run_id: str,
    proposal_id: str,
    request: PatchApprovalRequest,
) -> PatchApprovalResponse:
    del request  # Literal[True] validation is the explicit approval signal.
    ensure_runtime_dirs()
    home = safeplane_home()

    try:
        run = load_run(home, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if run.get("workflow_id") != "developer":
        raise HTTPException(
            status_code=409,
            detail="patch approval is only available for developer workflow runs",
        )
    if run.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"developer run must be completed before approval: {run.get('status')}",
        )

    try:
        proposal = load_patch_proposal(
            home,
            run_id=run_id,
            proposal_id=proposal_id,
        )
        if proposal.get("workflow_id") != run.get("workflow_id"):
            raise PatchApprovalError("patch proposal workflow does not match the run")
        if proposal.get("session_id") != run.get("session_id"):
            raise PatchApprovalError("patch proposal session does not match the run")
        if int(proposal.get("turn", -1)) != int(run.get("turn", -2)):
            raise PatchApprovalError("patch proposal turn does not match the run")

        with RUN_LOCK:
            approval, approval_token = create_patch_approval(
                home,
                run=run,
                proposal=proposal,
                connector="cli-explicit-approval",
            )
            prepare_patch_apply_workspace(
                home,
                run_id=run_id,
                approval_id=approval["approval_id"],
            )
    except PatchApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PatchApprovalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    approval_id = str(approval["approval_id"])
    session_id = str(run["session_id"])
    turn = int(run["turn"])

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event="patch_approval_granted",
        input_data={
            "approval_id": approval_id,
            "proposal_id": proposal_id,
            "connector": "cli-explicit-approval",
        },
        output_data={
            "status": "approved",
            "patch_sha256": proposal["patch_sha256"],
        },
        artifact_refs=[str(proposal["patch_ref"])],
    )

    try:
        from harness.mcp_broker import McpBrokerError, McpToolBroker

        broker = McpToolBroker(
            config_path=safeplane_config_path(),
            safeplane_home=home,
        )
        response = broker.call_tool(
            {
                "workflow_id": "developer",
                "server_id": "dev-workspace-apply",
                "tool_name": "dev_workspace_apply_patch",
                "arguments": {
                    "proposal_id": proposal_id,
                    "patch": proposal["patch"],
                    "patch_sha256": proposal["patch_sha256"],
                },
                "session_id": session_id,
                "turn": turn,
                "run_id": run_id,
                "connector": "harness-explicit-approval",
                "approval_id": approval_id,
                "approval_token": approval_token,
            }
        )
        content = response.structured_content
        changed_files = list(content.get("changed_files") or [])
        publish_patch_apply_workspace(
            home,
            run_id=run_id,
            approval_id=approval_id,
        )
        approval = update_patch_approval(
            home,
            approval,
            status="applied",
            applied_at=utc_now(),
            changed_files=changed_files,
            evidence_ref=content.get("evidence_ref"),
            error=None,
        )

        for file_write in changed_files:
            write_trace(
                session_id=session_id,
                turn=turn,
                run_id=run_id,
                event="patch_file_written",
                input_data={
                    "approval_id": approval_id,
                    "proposal_id": proposal_id,
                },
                output_data=file_write,
            )

        current_run = load_run(home, run_id)
        approvals = list(current_run.get("patch_approvals") or [])
        approvals.append(
            {
                "approval_id": approval_id,
                "proposal_id": proposal_id,
                "status": "applied",
                "applied_at": approval["applied_at"],
                "workspace_ref": approval["workspace_ref"],
                "changed_files": changed_files,
                "evidence_ref": approval.get("evidence_ref"),
            }
        )
        update_run(home, run_id, patch_approvals=approvals)

        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="patch_apply_completed",
            input_data={
                "approval_id": approval_id,
                "proposal_id": proposal_id,
            },
            output_data={
                "status": "applied",
                "workspace_ref": approval["workspace_ref"],
                "changed_file_count": len(changed_files),
                "evidence_ref": approval.get("evidence_ref"),
            },
            artifact_refs=[str(proposal["patch_ref"])],
        )

        return PatchApprovalResponse(
            status="applied",
            approval_id=approval_id,
            proposal_id=proposal_id,
            run_id=run_id,
            workspace_ref=str(approval["workspace_ref"]),
            changed_files=changed_files,
            evidence_ref=approval.get("evidence_ref"),
        )
    except McpBrokerError as exc:
        cleanup_patch_apply_workspace(
            home,
            run_id=run_id,
            approval_id=approval_id,
        )
        approval = update_patch_approval(
            home,
            approval,
            status="failed",
            failed_at=utc_now(),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="patch_apply_failed",
            input_data={
                "approval_id": approval_id,
                "proposal_id": proposal_id,
            },
            error=approval["error"],
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        cleanup_patch_apply_workspace(
            home,
            run_id=run_id,
            approval_id=approval_id,
        )
        approval = update_patch_approval(
            home,
            approval,
            status="failed",
            failed_at=utc_now(),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="patch_apply_failed",
            input_data={
                "approval_id": approval_id,
                "proposal_id": proposal_id,
            },
            error=approval["error"],
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc



def _developer_contract() -> dict[str, Any]:
    config = load_safeplane_config()
    resolved = resolve_entrypoint(config, "develop")
    workflow_entry = resolved["registry_entry"]
    contract_path = resolve_contract_path(
        safeplane_config_path(),
        workflow_entry.contract_path,
    )
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise RemoteWriteError("developer workflow contract must be a mapping")
    return raw


def _draft_pr_creation_mode(home: Path, run_id: str) -> str:
    run = load_run(home, run_id)
    pipeline = run.get("developer_pipeline") or {}
    binding = pipeline.get("remote_approval_binding") or {}
    mode = str(binding.get("draft_pr_creation") or "approval_required")
    return mode if mode in {"approval_required", "automatic"} else "approval_required"


def approve_remote_write(
    *,
    run_id: str,
    request: RemoteApprovalRequestBody,
) -> RemoteWriteResult:
    _ = request.approved
    ensure_runtime_dirs()
    home = safeplane_home()
    try:
        run = load_run(home, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with REMOTE_WRITE_LOCKS_GUARD:
        lock = REMOTE_WRITE_LOCKS.setdefault(run_id, threading.Lock())

    try:
        with lock:
            result = execute_remote_write(
                safeplane_home=home,
                contract=_developer_contract(),
                run_id=run_id,
                connector=request.connector,
            )
        write_trace(
            session_id=str(run["session_id"]),
            turn=int(run["turn"]),
            run_id=run_id,
            event="remote_write_completed",
            input_data={
                "approval_id": result.approval_id,
                "connector": request.connector,
            },
            output_data={
                "status": result.status,
                "branch_name": result.branch_name,
                "commit_sha": result.commit_sha,
                "pull_request_number": result.pull_request_number,
                "pull_request_url": result.pull_request_url,
                "draft": result.draft,
                "branch_reused": result.branch_reused,
                "pull_request_reused": result.pull_request_reused,
            },
            artifact_refs=[result.approval_ref, result.evidence_ref],
        )
        return result
    except RemoteWriteConflictError as exc:
        write_trace(
            session_id=str(run["session_id"]),
            turn=int(run["turn"]),
            run_id=run_id,
            event="remote_write_blocked",
            input_data={"connector": request.connector},
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemoteWritePolicyError as exc:
        write_trace(
            session_id=str(run["session_id"]),
            turn=int(run["turn"]),
            run_id=run_id,
            event="remote_write_rejected",
            input_data={"connector": request.connector},
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemoteWriteError as exc:
        write_trace(
            session_id=str(run["session_id"]),
            turn=int(run["turn"]),
            run_id=run_id,
            event="remote_write_failed",
            input_data={"connector": request.connector},
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

def wait_for_run(run_id: str, timeout_seconds: int = 600) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    home = safeplane_home()

    while time.time() < deadline:
        run = load_run(home, run_id)

        if run.get("status") in TERMINAL_RUN_STATUSES:
            return run

        time.sleep(0.1)

    raise TimeoutError(f"Run did not finish within {timeout_seconds} seconds: {run_id}")


def handle_connector_entrypoint(
    entrypoint_name: str,
    request: ConnectorMessageRequest,
    *,
    wait_for_completion: bool = True,
    routing_decision: RoutingDecision | None = None,
) -> ConnectorMessageResponse:
    ensure_runtime_dirs()

    config = load_safeplane_config()

    if entrypoint_name == "auto":
        registry = build_registry(config, safeplane_config_path())
        if request.session_ref:
            try:
                session = resolve_session_reference(request.session_ref)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            workflow_id = str(session.get("workflow_id") or "")
            routes = dict((config.get("routing_advisor") or {}).get("routes") or {})
            candidates = [
                str(entrypoint)
                for entrypoint in routes.values()
                if str(entrypoint) in registry
                and registry[str(entrypoint)].workflow_id == workflow_id
                and connector_is_exposed(registry[str(entrypoint)], request.connector)
            ]
            if len(candidates) != 1:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot continue automatic session for workflow {workflow_id!r}; "
                        "use an explicit workflow command."
                    ),
                )
            return handle_connector_entrypoint(
                candidates[0],
                request,
                wait_for_completion=wait_for_completion,
            )

        routing_id = f"route_{uuid.uuid4()}"
        decision: RoutingDecision | None = None
        try:
            decision = route_message(
                config=config,
                registry=registry,
                connector=request.connector,
                message=request.message,
                repository_profile=request.repository_profile,
                routing_id=routing_id,
            )
        except RoutingAdvisorAbstainedError as exc:
            write_routing_trace(
                safeplane_home=safeplane_home(),
                routing_id=routing_id,
                connector=request.connector,
                message=request.message,
                repository_profile=request.repository_profile,
                decision=exc.decision,
                error=exc,
            )
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RoutingAdvisorPrerequisiteError as exc:
            write_routing_trace(
                safeplane_home=safeplane_home(),
                routing_id=routing_id,
                connector=request.connector,
                message=request.message,
                repository_profile=request.repository_profile,
                decision=exc.decision,
                error=exc,
            )
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RoutingAdvisorUnavailableError as exc:
            write_routing_trace(
                safeplane_home=safeplane_home(),
                routing_id=routing_id,
                connector=request.connector,
                message=request.message,
                repository_profile=request.repository_profile,
                error=exc,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Automatic routing is unavailable: {exc}. Use an explicit workflow command.",
            ) from exc

        write_routing_trace(
            safeplane_home=safeplane_home(),
            routing_id=decision.routing_id,
            connector=request.connector,
            message=request.message,
            repository_profile=request.repository_profile,
            decision=decision,
        )
        return handle_connector_entrypoint(
            str(decision.entrypoint),
            request,
            wait_for_completion=wait_for_completion,
            routing_decision=decision,
        )

    try:
        resolved = resolve_entrypoint(config, entrypoint_name)
    except UnknownEntrypointError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DisabledWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowContractValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    workflow_id = resolved["workflow_id"]
    workflow_entry = resolved["registry_entry"]

    if not connector_is_exposed(workflow_entry, request.connector):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Entrypoint {entrypoint_name!r} is not exposed to connector "
                f"{request.connector!r}"
            ),
        )

    if request.repository_profile and entrypoint_name != "develop":
        raise HTTPException(
            status_code=422,
            detail="repository_profile is only valid for the develop entrypoint",
        )
    model_gateway_url = str(
        config.get("model_gateway", {}).get(
            "endpoint",
            os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:8080/chat"),
        )
    )

    with RUN_LOCK:
        if request.session_ref:
            try:
                session = resolve_session_reference(request.session_ref)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            if session.get("workflow_id") != workflow_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Session belongs to workflow {session.get('workflow_id')!r}, "
                        f"cannot continue with {workflow_id!r}"
                    ),
                )

            session_id = session["session_id"]
            active_run = find_active_run_for_session(safeplane_home(), session_id)

            if active_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Session has an active run: {active_run['run_id']}",
                )

            session_display_id = session.get("session_display_id") or display_id_from_session_id(session_id)
            turn = session_next_turn(session)
            history_messages = session_history_messages(session)
            session["status"] = "active"
            session["updated_at"] = utc_now()
            save_session(session)
            session_event = "session_continued"
        else:
            session = create_session(connector=request.connector, workflow_id=workflow_id)
            session_id = session["session_id"]
            session_display_id = session["session_display_id"]
            turn = 1
            history_messages = []
            save_session(session)
            session_event = "session_created"

        current_trace_dir = trace_dir(session_id, turn)

        run = create_run(
            safeplane_home=safeplane_home(),
            session_id=session_id,
            session_display_id=session_display_id,
            turn=turn,
            workflow_id=workflow_id,
            entrypoint=entrypoint_name,
            connector=request.connector,
            trace_path=str(current_trace_dir),
            repository_profile=request.repository_profile,
            operator_message=request.message,
        )
        run_id = run["run_id"]

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event="connector_message_received",
        input_data={
            "connector": request.connector,
            "entrypoint": entrypoint_name,
            "message": request.message,
            "session_ref": request.session_ref,
            "repository_profile": request.repository_profile,
        },
    )

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event=session_event,
        output_data={
            "session_id": session_id,
            "session_display_id": session_display_id,
            "workflow_id": workflow_id,
            "turn": turn,
            "prior_message_count": len(history_messages),
        },
    )

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event="run_queued",
        output_data={
            "run_id": run_id,
            "status": "queued",
            "trace_path": str(current_trace_dir),
        },
    )

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event="safeplane_config_loaded",
        output_data={
            "config_path": str(safeplane_config_path()),
        },
    )

    write_trace(
        session_id=session_id,
        turn=turn,
        run_id=run_id,
        event="entrypoint_resolved",
        output_data={
            "entrypoint": entrypoint_name,
            "workflow_id": workflow_id,
            "runtime_owner": "harness",
            "legacy_workflow_endpoint": resolved["workflow"].get("endpoint"),
        },
    )

    if routing_decision is not None:
        write_trace(
            session_id=session_id,
            turn=turn,
            run_id=run_id,
            event="routing_advisor_decision",
            input_data={
                "routing_id": routing_decision.routing_id,
                "requested_entrypoint": "auto",
            },
            output_data=routing_decision.to_dict(),
            artifact_refs=[
                str(
                    safeplane_home()
                    / "traces"
                    / "routing"
                    / f"{routing_decision.routing_id}.json"
                )
            ],
        )

    RUN_EXECUTOR.submit(
        execute_run,
        run_id=run_id,
        session_id=session_id,
        session_display_id=session_display_id,
        turn=turn,
        workflow_entry=workflow_entry,
        model_gateway_url=model_gateway_url,
        entrypoint_name=entrypoint_name,
        operator_message=request.message,
        history_messages=history_messages,
        repository_profile=request.repository_profile,
    )

    if not wait_for_completion:
        return ConnectorMessageResponse(
            status="queued",
            session_id=session_id,
            session_display_id=session_display_id,
            turn=turn,
            run_id=run_id,
            workflow_id=workflow_id,
            entrypoint=entrypoint_name,
            final_message=None,
            trace_path=str(current_trace_dir),
            routing=routing_decision.to_dict() if routing_decision is not None else None,
        )

    try:
        completed_run = wait_for_run(run_id)
    except Exception as exc:
        mark_failed(
            safeplane_home(),
            run_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if completed_run["status"] == "failed":
        error = completed_run.get("error") or {}
        raise HTTPException(
            status_code=500,
            detail=f"Run failed: {completed_run['run_id']}: {error.get('message')}",
        )

    return ConnectorMessageResponse(
        status=completed_run["status"],
        session_id=session_id,
        session_display_id=session_display_id,
        turn=turn,
        run_id=run_id,
        workflow_id=workflow_id,
        entrypoint=entrypoint_name,
        final_message=completed_run.get("final_message"),
        trace_path=str(current_trace_dir),
        routing=routing_decision.to_dict() if routing_decision is not None else None,
    )


def recover_incomplete_developer_runs() -> None:
    ensure_runtime_dirs()
    try:
        config = load_safeplane_config()
        resolved = resolve_entrypoint(config, "develop")
    except Exception:
        return
    workflow_entry = resolved["registry_entry"]
    model_gateway_url = str(
        config.get("model_gateway", {}).get(
            "endpoint",
            os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:8080/chat"),
        )
    )
    for run in list_runs(safeplane_home()):
        if run.get("entrypoint") != "develop" or run.get("status") not in {"queued", "running"}:
            continue
        operator_message = str(run.get("operator_message") or "").strip()
        if not operator_message:
            mark_failed(
                safeplane_home(),
                str(run["run_id"]),
                error_type="RunRecoveryError",
                error_message="developer run cannot resume without its operator message",
            )
            continue
        try:
            session = load_session(str(run["session_id"]))
            history_messages = session_history_messages(session)
        except Exception as exc:
            mark_failed(
                safeplane_home(),
                str(run["run_id"]),
                error_type=type(exc).__name__,
                error_message=f"developer run recovery failed: {exc}",
            )
            continue
        update_run(
            safeplane_home(),
            str(run["run_id"]),
            recovery_count=int(run.get("recovery_count") or 0) + 1,
            recovery_started_at=utc_now(),
        )
        RUN_EXECUTOR.submit(
            execute_run,
            run_id=str(run["run_id"]),
            session_id=str(run["session_id"]),
            session_display_id=str(run["session_display_id"]),
            turn=int(run["turn"]),
            workflow_entry=workflow_entry,
            model_gateway_url=model_gateway_url,
            entrypoint_name="develop",
            operator_message=operator_message,
            history_messages=history_messages,
            repository_profile=run.get("repository_profile"),
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "harness",
    }


@app.get("/workflows")
def list_workflows(
    connector: Literal["cli", "telegram"] | None = None,
    exposed_only: bool = False,
) -> dict[str, Any]:
    try:
        config = load_safeplane_config()
        registry = build_registry(config, safeplane_config_path())
    except WorkflowContractValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if connector is None:
        entries = sorted(registry.values(), key=lambda item: item.entrypoint_name)
    else:
        entries = connector_registry_entries(
            registry,
            connector,
            exposed_only=exposed_only,
        )

    response: dict[str, Any] = {
        "workflows": [registry_entry_to_public_dict(entry) for entry in entries]
    }
    if connector is not None:
        connector_config = dict((config.get("connectors") or {}).get(connector) or {})
        default_entrypoint = connector_config.get("default_entrypoint")
        if exposed_only and default_entrypoint and not any(
            entry.entrypoint_name == default_entrypoint for entry in entries
        ):
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Connector {connector!r} default entrypoint {default_entrypoint!r} "
                    "is not enabled and exposed"
                ),
            )
        response["connector"] = connector
        response["default_entrypoint"] = default_entrypoint
        response["routing_mode"] = connector_config.get("routing_mode", "default_entrypoint")
        response["automatic_routing"] = bool(
            (config.get("routing_advisor") or {}).get("enabled", False)
            and response["routing_mode"] == "automatic"
        )
    return response


@app.get("/workflows/{entrypoint_name}")
def get_workflow(entrypoint_name: str) -> dict[str, Any]:
    try:
        registry = load_workflow_registry()
        entry = resolve_entrypoint_from_registry(registry, entrypoint_name)
    except UnknownEntrypointError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DisabledWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowContractValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return registry_entry_to_public_dict(entry)


@app.get("/runs")
def list_run_records() -> dict[str, Any]:
    ensure_runtime_dirs()
    return {
        "runs": list_runs(safeplane_home()),
    }


@app.get("/runs/{run_id}")
def get_run_record(run_id: str) -> dict[str, Any]:
    ensure_runtime_dirs()

    try:
        return load_run(safeplane_home(), run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/runs/{run_id}/patches/{proposal_id}/approve",
    response_model=PatchApprovalResponse,
)
def approve_patch_endpoint(
    run_id: str,
    proposal_id: str,
    request: PatchApprovalRequest,
) -> PatchApprovalResponse:
    return approve_patch_proposal(
        run_id=run_id,
        proposal_id=proposal_id,
        request=request,
    )



@app.post(
    "/runs/{run_id}/remote/approve",
    response_model=RemoteWriteResult,
)
def approve_remote_write_endpoint(
    run_id: str,
    request: RemoteApprovalRequestBody,
) -> RemoteWriteResult:
    return approve_remote_write(run_id=run_id, request=request)

@app.post("/connector/{entrypoint_name}", response_model=ConnectorMessageResponse)
def connector_entrypoint(
    entrypoint_name: str,
    request: ConnectorMessageRequest,
) -> ConnectorMessageResponse:
    return handle_connector_entrypoint(entrypoint_name, request)


@app.post("/connector/{entrypoint_name}/start", response_model=ConnectorMessageResponse)
def connector_entrypoint_start(
    entrypoint_name: str,
    request: ConnectorMessageRequest,
) -> ConnectorMessageResponse:
    return handle_connector_entrypoint(
        entrypoint_name,
        request,
        wait_for_completion=False,
    )


# MCP foundation MCP broker endpoint
@app.post("/mcp/tools/call")
def mcp_tools_call(payload: dict):
    from fastapi import HTTPException
    from harness.mcp_broker import (
        McpBrokerError,
        McpPermissionError,
        McpValidationError,
        call_tool_from_http_payload,
    )

    try:
        return call_tool_from_http_payload(payload)
    except McpPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except McpValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except McpBrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
