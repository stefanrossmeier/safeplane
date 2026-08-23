from __future__ import annotations

import json
from typing import Any

from safeplane_connector.errors import HarnessProtocolError
from safeplane_connector.models import ConnectorMessageResult, WorkflowListResult


def render_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_workflows(result: WorkflowListResult) -> str:
    lines: list[str] = []
    for workflow in result.workflows:
        status = "enabled" if workflow.enabled else "disabled"
        lines.append(
            f"{workflow.entrypoint}: {workflow.workflow_id} {workflow.version} ({status})"
        )
        lines.append(f"  {workflow.description}")
    return "\n".join(lines)


def render_connector_result(result: ConnectorMessageResult) -> str:
    lines = [result.final_message or "", ""]
    lines.extend(
        [
            f"session: {result.session_display_id}",
            f"turn: {result.turn}",
            f"run: {result.run_id}",
            f"status: {result.status}",
            f"trace: {result.trace_path}",
        ]
    )
    return "\n".join(lines)


def render_runs(runs: tuple[dict[str, Any], ...]) -> str:
    return "\n".join(
        f"{run['run_id']} {run['status']} {run['workflow_id']} "
        f"session={run['session_display_id']} turn={run['turn']}"
        for run in runs
    )


def render_patch_approval(value: dict[str, Any]) -> str:
    lines = [
        f"approval: {value['approval_id']}",
        f"proposal: {value['proposal_id']}",
        f"run: {value['run_id']}",
        f"status: {value['status']}",
        f"workspace: {value['workspace_ref']}",
    ]
    if value.get("evidence_ref"):
        lines.append(f"evidence: {value['evidence_ref']}")
    lines.append("changed files:")
    for item in value.get("changed_files", []):
        lines.append(f"  {item['operation']}: {item['path']}")
    return "\n".join(lines)


def render_remote_approval(value: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"approval: {value['approval_id']}",
            f"run: {value['run_id']}",
            f"status: {value['status']}",
            f"branch: {value['branch_name']}",
            f"commit: {value['commit_sha']}",
            f"draft PR: {value['pull_request_url']}",
            f"branch reused: {str(value['branch_reused']).lower()}",
            f"PR reused: {str(value['pull_request_reused']).lower()}",
            f"evidence: {value['evidence_ref']}",
        ]
    )


def render_run(run: dict[str, Any]) -> str:
    required = ("run_id", "status", "session_display_id", "turn", "workflow_id", "entrypoint", "trace_path")
    missing = [key for key in required if key not in run]
    if missing:
        raise HarnessProtocolError(
            "Harness run response is missing required field(s): " + ", ".join(missing)
        )

    lines = [
        f"run: {run['run_id']}",
        f"status: {run['status']}",
        f"session: {run['session_display_id']}",
        f"turn: {run['turn']}",
        f"workflow: {run['workflow_id']}",
        f"entrypoint: {run['entrypoint']}",
    ]
    if run.get("repository_profile"):
        lines.append(f"repository profile: {run['repository_profile']}")
    lines.append(f"trace: {run['trace_path']}")

    pipeline_value = run.get("developer_pipeline")
    if pipeline_value is not None and not isinstance(pipeline_value, dict):
        raise HarnessProtocolError("Harness run field 'developer_pipeline' must be an object or null")
    pipeline = pipeline_value or {}
    if pipeline:
        lines.append(f"pipeline state: {pipeline.get('current_state')}")
        completed = pipeline.get("completed_stages") or []
        if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
            raise HarnessProtocolError("Harness pipeline field 'completed_stages' must be a list of strings")
        if completed:
            lines.append(f"completed stages: {', '.join(completed)}")
        check_summary = pipeline.get("check_summary") or {}
        if not isinstance(check_summary, dict):
            raise HarnessProtocolError("Harness pipeline field 'check_summary' must be an object or null")
        if check_summary:
            lines.append(f"checks: {check_summary.get('status')}")
        if pipeline.get("review_verdict"):
            lines.append(f"review: {pipeline['review_verdict']}")
        lines.append(
            "remote approval: "
            + ("available" if pipeline.get("remote_approval_possible") else "not available")
        )
        binding = pipeline.get("remote_approval_binding") or {}
        if not isinstance(binding, dict):
            raise HarnessProtocolError(
                "Harness pipeline field 'remote_approval_binding' must be an object or null"
            )
        if binding:
            lines.append(f"planned branch: {binding.get('branch_name')}")
            lines.append(f"approved workspace: {binding.get('workspace_tree_sha256')}")
        remote_write = pipeline.get("remote_write") or run.get("remote_write") or {}
        if not isinstance(remote_write, dict):
            raise HarnessProtocolError("Harness remote-write field must be an object or null")
        if remote_write:
            lines.append(f"remote branch: {remote_write.get('branch_name')}")
            lines.append(f"remote commit: {remote_write.get('commit_sha')}")
            lines.append(f"draft PR: {remote_write.get('pull_request_url')}")
        agent_runs = pipeline.get("agent_runs") or []
        if not isinstance(agent_runs, list) or not all(isinstance(item, dict) for item in agent_runs):
            raise HarnessProtocolError("Harness pipeline field 'agent_runs' must be a list of objects")
        if agent_runs:
            lines.append("models:")
            for item in agent_runs:
                details = [
                    f"duration={item.get('duration_ms', 0)}ms",
                    f"retries={item.get('retry_count', 0)}",
                ]
                if item.get("total_tokens") is not None:
                    details.append(f"tokens={item.get('total_tokens')}")
                if item.get("cost") is not None:
                    details.append(f"cost={item.get('cost')}")
                lines.append(
                    f"  {item.get('stage_id')}: {item.get('model_profile')} -> "
                    f"{item.get('actual_provider') or '?'} / {item.get('actual_model') or '?'} "
                    f"({' '.join(details)})"
                )

    if run.get("final_message"):
        lines.extend(["", str(run["final_message"])])
    if run.get("error"):
        lines.extend(["", json.dumps(run["error"], indent=2, ensure_ascii=False)])
    return "\n".join(lines)
