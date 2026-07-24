from __future__ import annotations

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from harness.mcp_logs import write_mcp_log
from harness.run_store import load_run
from harness.patch_approval_store import (
    PatchApprovalError,
    sha256_text,
    validate_patch_approval_token,
)
from harness.mcp_schemas import (
    McpBrokerRequest,
    McpBrokerResponse,
    model_to_dict,
    validate_model,
    validate_tool_input,
    validate_tool_output,
)


class McpBrokerError(RuntimeError):
    pass


class McpPermissionError(McpBrokerError):
    pass


class McpValidationError(McpBrokerError):
    pass


class McpToolExecutionError(McpBrokerError):
    pass


def default_config_path() -> Path:
    configured = os.environ.get("SAFEPLANE_CONFIG")

    if configured:
        return Path(configured)

    candidate = Path("safeplane.yaml")

    if candidate.exists():
        return candidate

    return Path("/app/safeplane.yaml")


def default_safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", str(Path.home() / ".safeplane"))).expanduser()


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise McpBrokerError(f"YAML file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    if not isinstance(data, dict):
        raise McpBrokerError(f"YAML root must be an object: {path}")

    return data


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class McpToolBroker:
    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        safeplane_home: Optional[Path] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.config_path = config_path or default_config_path()
        self.config_dir = self.config_path.parent
        self.safeplane_home = safeplane_home or default_safeplane_home()
        self.timeout_seconds = timeout_seconds
        self.config = load_yaml(self.config_path)

    def workflow_contract_path(self, workflow_id: str) -> Path:
        return self.config_dir / "workflows" / workflow_id / "workflow.yaml"

    def load_workflow_contract(self, workflow_id: str) -> Dict[str, Any]:
        return load_yaml(self.workflow_contract_path(workflow_id))

    def server_config(self, server_id: str) -> Dict[str, Any]:
        servers = self.config.get("mcp_servers") or {}

        if not isinstance(servers, dict) or server_id not in servers:
            raise McpPermissionError(f"MCP server is not registered: {server_id}")

        server = servers[server_id]

        if not isinstance(server, dict):
            raise McpPermissionError(f"MCP server config must be an object: {server_id}")

        if not server.get("enabled", False):
            raise McpPermissionError(f"MCP server is disabled: {server_id}")

        return server

    def workflow_max_tool_call_retries(self, workflow_id: str) -> int:
        contract = self.load_workflow_contract(workflow_id)
        mcp = contract.get("mcp") or {}

        try:
            return int(mcp.get("max_tool_call_retries", 5))
        except (TypeError, ValueError):
            return 5

    def ensure_workflow_tool_allowed(
        self,
        *,
        workflow_id: str,
        server_id: str,
        tool_name: str,
        agent_id: str | None = None,
    ) -> str:
        contract = self.load_workflow_contract(workflow_id)
        mcp = contract.get("mcp") or {}
        allowed_servers = mcp.get("allowed_servers") or {}
        approval_servers = mcp.get("approval_required_servers") or {}

        if not isinstance(allowed_servers, dict):
            raise McpPermissionError(
                f"Workflow MCP allowed_servers must be an object: {workflow_id}"
            )
        if not isinstance(approval_servers, dict):
            raise McpPermissionError(
                f"Workflow MCP approval_required_servers must be an object: {workflow_id}"
            )

        def configured_tools(policies: dict[str, Any]) -> list[str]:
            server_policy = policies.get(server_id)
            if isinstance(server_policy, dict):
                return [str(item) for item in server_policy.get("tools") or []]
            if isinstance(server_policy, list):
                return [str(item) for item in server_policy]
            return []

        access_mode: str | None = None
        if tool_name in configured_tools(allowed_servers):
            access_mode = "allowed"
        elif tool_name in configured_tools(approval_servers):
            access_mode = "approval_required"

        if access_mode is not None and agent_id is not None:
            agents = contract.get("agents") or {}
            agent = agents.get(agent_id) if isinstance(agents, dict) else None
            if not isinstance(agent, dict):
                raise McpPermissionError(f"Unknown workflow agent: {agent_id}")
            agent_servers = agent.get("allowed_mcp_servers") or {}
            if not isinstance(agent_servers, dict):
                raise McpPermissionError(
                    f"Agent MCP permissions must be an object: agent={agent_id}"
                )
            if tool_name not in configured_tools(agent_servers):
                raise McpPermissionError(
                    f"Agent is not allowed to use MCP tool: agent={agent_id}, "
                    f"server={server_id}, tool={tool_name}"
                )

        if access_mode is not None:
            if tool_name.startswith("dev_external_skill_") and not agent_id:
                raise McpPermissionError("external skill tools require an agent_id")
            return access_mode

        if server_id not in allowed_servers and server_id not in approval_servers:
            raise McpPermissionError(
                f"Workflow is not allowed to use MCP server: workflow={workflow_id}, server={server_id}"
            )
        raise McpPermissionError(
            f"Workflow is not allowed to use MCP tool: workflow={workflow_id}, server={server_id}, tool={tool_name}"
        )

    def call_tool(self, raw_request: Dict[str, Any]) -> McpBrokerResponse:
        started = time.monotonic()
        request: Optional[McpBrokerRequest] = None
        server_id = str(raw_request.get("server_id", ""))
        tool_name = str(raw_request.get("tool_name", ""))
        workflow_id = str(raw_request.get("workflow_id", ""))

        base_log: Dict[str, Any] = {
            "event": "mcp_tool_access",
            "workflow_id": workflow_id or None,
            "server_id": server_id or None,
            "tool_name": tool_name or None,
            "session_id": raw_request.get("session_id"),
            "turn": raw_request.get("turn"),
            "run_id": raw_request.get("run_id"),
            "connector": raw_request.get("connector"),
            "agent_id": raw_request.get("agent_id"),
            "input_schema_valid": None,
            "output_schema_valid": None,
            "safeplane_enforcement": "harness_permission_schema_and_approval_validation",
            "approval_id": raw_request.get("approval_id"),
        }

        try:
            request = validate_model(McpBrokerRequest, raw_request)
            server_id = request.server_id
            tool_name = request.tool_name
            workflow_id = request.workflow_id

            base_log.update(
                {
                    "workflow_id": workflow_id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "session_id": request.session_id,
                    "turn": request.turn,
                    "run_id": request.run_id,
                    "connector": request.connector,
                    "agent_id": request.agent_id,
                }
            )

            server = self.server_config(server_id)
            access_mode = self.ensure_workflow_tool_allowed(
                workflow_id=workflow_id,
                server_id=server_id,
                tool_name=tool_name,
                agent_id=request.agent_id,
            )

            validated_input = validate_tool_input(tool_name, request.arguments)
            base_log["input_schema_valid"] = True

            if access_mode == "approval_required":
                self._validate_approved_tool_request(
                    request=request,
                    validated_input=model_to_dict(validated_input),
                )

            if server_id in {"dev-workspace", "dev-workspace-apply", "dev-check"}:
                self._validate_dev_workspace_run_context(request)

            endpoint = str(server["endpoint"])
            tool_call_id = request.tool_call_id or f"tool_call_{uuid.uuid4()}"

            mcp_payload = {
                "jsonrpc": "2.0",
                "id": tool_call_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": model_to_dict(validated_input),
                    "context": {
                        "workflow_id": request.workflow_id,
                        "session_id": request.session_id,
                        "turn": request.turn,
                        "run_id": request.run_id,
                        "connector": request.connector,
                        "tool_call_id": tool_call_id,
                        "approval_id": request.approval_id,
                        "agent_id": request.agent_id,
                    },
                },
            }

            mcp_response = self._post_json(endpoint, mcp_payload)

            result = mcp_response.get("result")

            if not isinstance(result, dict):
                raise McpToolExecutionError("MCP response missing result object")

            if result.get("isError"):
                raise McpToolExecutionError(
                    json.dumps(result, ensure_ascii=False)
                )

            structured_content = result.get("structuredContent")

            if not isinstance(structured_content, dict):
                raise McpToolExecutionError(
                    "MCP result missing structuredContent object"
                )

            validated_output = validate_tool_output(tool_name, structured_content)
            normalized_output = model_to_dict(validated_output)

            if server_id in {"dev-workspace", "dev-workspace-apply", "dev-check"}:
                normalized_output = self._persist_dev_workspace_evidence(
                    request=request,
                    tool_call_id=tool_call_id,
                    arguments=model_to_dict(validated_input),
                    structured_content=normalized_output,
                )
                validated_output = validate_tool_output(tool_name, normalized_output)
                normalized_output = model_to_dict(validated_output)

            base_log["output_schema_valid"] = True

            write_mcp_log(
                {
                    **base_log,
                    "decision": "allowed",
                    "reason": "approval_validated" if access_mode == "approval_required" else "workflow_tool_allowed",
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "evidence_ref": normalized_output.get("evidence_ref"),
                    "artifact_ref": normalized_output.get("artifact_ref"),
                    "workspace_root": normalized_output.get("workspace_root"),
                    "exit_code": normalized_output.get("exit_code"),
                },
                safeplane_home=self.safeplane_home,
            )

            return McpBrokerResponse(
                server_id=server_id,
                tool_name=tool_name,
                structured_content=normalized_output,
                is_error=False,
            )

        except McpPermissionError as exc:
            write_mcp_log(
                {
                    **base_log,
                    "decision": "denied",
                    "reason": "permission_denied",
                    "error": str(exc),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                safeplane_home=self.safeplane_home,
            )
            raise

        except McpValidationError as exc:
            write_mcp_log(
                {
                    **base_log,
                    "decision": "rejected",
                    "reason": "safeplane_context_validation_failed",
                    "error": str(exc),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                safeplane_home=self.safeplane_home,
            )
            raise

        except (ValidationError, ValueError) as exc:
            write_mcp_log(
                {
                    **base_log,
                    "decision": "rejected",
                    "reason": "schema_validation_failed",
                    "input_schema_valid": False if request is not None else None,
                    "error": str(exc),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                safeplane_home=self.safeplane_home,
            )
            raise McpValidationError(str(exc)) from exc

        except McpToolExecutionError as exc:
            write_mcp_log(
                {
                    **base_log,
                    "decision": "failed",
                    "reason": "mcp_tool_execution_failed",
                    "error": str(exc),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                safeplane_home=self.safeplane_home,
            )
            raise

    def _validate_approved_tool_request(
        self,
        *,
        request: McpBrokerRequest,
        validated_input: Dict[str, Any],
    ) -> None:
        if not request.run_id or not request.approval_id or not request.approval_token:
            raise McpPermissionError(
                "approval-required MCP tool needs run_id, approval_id, and an internal approval token"
            )
        proposal_id = str(validated_input.get("proposal_id") or "")
        patch_sha256 = str(validated_input.get("patch_sha256") or "")
        try:
            validate_patch_approval_token(
                self.safeplane_home,
                run_id=request.run_id,
                approval_id=request.approval_id,
                approval_token=request.approval_token,
                proposal_id=proposal_id,
                patch_sha256=patch_sha256,
                workflow_id=request.workflow_id,
            )
        except PatchApprovalError as exc:
            raise McpPermissionError(str(exc)) from exc

    def _validate_dev_workspace_run_context(self, request: McpBrokerRequest) -> None:
        if not request.run_id:
            raise McpValidationError(
                "dev-workspace tools require a Safeplane run_id for workspace isolation"
            )

        try:
            run = load_run(self.safeplane_home, request.run_id)
        except FileNotFoundError as exc:
            raise McpValidationError(str(exc)) from exc

        if run.get("workflow_id") != request.workflow_id:
            raise McpPermissionError(
                "dev-workspace run does not belong to the requested workflow"
            )

        if request.session_id and run.get("session_id") != request.session_id:
            raise McpPermissionError(
                "dev-workspace run does not belong to the requested session"
            )

        if request.turn is not None and int(run.get("turn", -1)) != request.turn:
            raise McpPermissionError(
                "dev-workspace run does not belong to the requested turn"
            )

        if request.server_id == "dev-workspace-apply":
            if not request.approval_id:
                raise McpValidationError("dev-workspace apply requires approval_id")
            repo_root = (
                self.safeplane_home
                / "workspaces"
                / request.run_id
                / "apply"
                / request.approval_id
                / "repo"
            )
        else:
            repo_root = self.safeplane_home / "workspaces" / request.run_id / "repo"
        if not repo_root.is_dir():
            raise McpValidationError(
                f"dev-workspace snapshot not found for run: {request.run_id}"
            )

    def _persist_dev_workspace_evidence(
        self,
        *,
        request: McpBrokerRequest,
        tool_call_id: str,
        arguments: Dict[str, Any],
        structured_content: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not request.run_id:
            raise McpValidationError(
                "dev-workspace tools require a Safeplane run_id for workspace isolation"
            )

        run_root = self.safeplane_home / "workspaces" / request.run_id
        evidence_dir = run_root / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / "tool-calls.jsonl"
        evidence_ref = str(evidence_path.relative_to(self.safeplane_home))

        normalized = dict(structured_content)
        normalized["evidence_ref"] = evidence_ref

        if request.tool_name == "dev_check_run":
            check_dir = evidence_dir / "checks"
            check_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = check_dir / f"{tool_call_id}.stdout.txt"
            stderr_path = check_dir / f"{tool_call_id}.stderr.txt"
            stdout_path.write_text(str(normalized.get("stdout") or ""), encoding="utf-8")
            stderr_path.write_text(str(normalized.get("stderr") or ""), encoding="utf-8")
            normalized["stdout_ref"] = str(stdout_path.relative_to(self.safeplane_home))
            normalized["stderr_ref"] = str(stderr_path.relative_to(self.safeplane_home))
            normalized["stdout"] = ""
            normalized["stderr"] = ""

        if request.tool_name == "dev_workspace_apply_patch":
            normalized["tool_evidence_path"] = evidence_ref

        artifact_ref = normalized.get("artifact_ref")
        if request.tool_name == "dev_workspace_propose_patch":
            artifacts_dir = run_root / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            proposal_id = f"patch_proposal_{uuid.uuid4()}"
            patch_path = artifacts_dir / f"{proposal_id}.patch"
            metadata_path = artifacts_dir / f"{proposal_id}.json"
            patch_text = str(normalized.get("patch", ""))
            patch_sha256 = sha256_text(patch_text)
            patch_path.write_text(patch_text, encoding="utf-8")
            normalized["proposal_id"] = proposal_id
            normalized["approval_command"] = (
                f"safeplane approve-patch {request.run_id} {proposal_id}"
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "created_at": datetime.now(UTC).isoformat(),
                        "workflow_id": request.workflow_id,
                        "session_id": request.session_id,
                        "turn": request.turn,
                        "run_id": request.run_id,
                        "tool_call_id": tool_call_id,
                        "proposal_id": proposal_id,
                        "summary": normalized.get("summary"),
                        "patch_ref": str(patch_path.relative_to(self.safeplane_home)),
                        "patch_sha256": patch_sha256,
                        "approval_required": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            artifact_ref = str(patch_path.relative_to(self.safeplane_home))
            normalized["artifact_ref"] = artifact_ref

        evidence_record = {
            "ts": datetime.now(UTC).isoformat(),
            "workflow_id": request.workflow_id,
            "session_id": request.session_id,
            "turn": request.turn,
            "run_id": request.run_id,
            "connector": request.connector,
            "agent_id": request.agent_id,
            "tool_call_id": tool_call_id,
            "server_id": request.server_id,
            "tool_name": request.tool_name,
            "arguments": arguments,
            "structured_content": normalized,
            "workspace_root": normalized.get("workspace_root"),
            "cwd": normalized.get("cwd"),
            "exit_code": normalized.get("exit_code"),
            "artifact_ref": artifact_ref,
            "approval_id": request.approval_id,
        }
        with evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence_record, ensure_ascii=False, sort_keys=True) + "\n")

        return normalized

    def _post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        if endpoint.startswith("unix://"):
            socket_path = endpoint.removeprefix("unix://")
            connection = UnixSocketHTTPConnection(socket_path, self.timeout_seconds)
            try:
                connection.request(
                    "POST",
                    "/mcp",
                    body=encoded,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                body = response.read().decode("utf-8", errors="replace")
                if response.status >= 400:
                    raise McpToolExecutionError(
                        f"MCP Unix-socket HTTP error {response.status}: {body}"
                    )
            except (OSError, http.client.HTTPException) as exc:
                raise McpToolExecutionError(f"MCP Unix-socket server unavailable: {exc}") from exc
            finally:
                connection.close()
        else:
            request = urllib.request.Request(
                endpoint,
                data=encoded,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise McpToolExecutionError(
                    f"MCP server HTTP error {exc.code}: {body}"
                ) from exc
            except urllib.error.URLError as exc:
                raise McpToolExecutionError(f"MCP server unavailable: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise McpToolExecutionError("MCP server returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise McpToolExecutionError("MCP server response must be an object")

        return parsed


def call_tool_from_http_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    broker = McpToolBroker()
    response = broker.call_tool(payload)
    return model_to_dict(response)
