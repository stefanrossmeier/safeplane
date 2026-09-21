from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .models import WorkflowCatalog, WorkflowRoute


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML object in {path}")
    return data


def _question(questions: dict[str, Any], name: str, *, required: bool = True) -> str | None:
    value = questions.get(name)
    if value is None:
        if required:
            raise ValueError(f"Missing routing question {name!r}")
        return None
    return str(value)


def load_catalog(repo_root: Path, semantics_path: Path) -> WorkflowCatalog:
    repo_root = repo_root.resolve()
    safeplane_path = repo_root / "safeplane.yaml"
    if not safeplane_path.exists():
        raise FileNotFoundError(f"Safeplane registry not found: {safeplane_path}")

    registry = _load_yaml(safeplane_path)
    semantics = _load_yaml(semantics_path)
    semantics_version = int(semantics.get("version", 1))
    if semantics_version not in {1, 2}:
        raise ValueError(f"Unsupported routing semantics version: {semantics_version}")

    route_semantics = semantics.get("routes", {})
    questions = semantics.get("questions", {})
    if not isinstance(route_semantics, dict) or not isinstance(questions, dict):
        raise ValueError("routing semantics must contain routes and questions objects")

    entrypoints = registry.get("entrypoints", {})
    workflows = registry.get("workflows", {})
    route_to_entrypoint = {"chat": "chat", "assistant": "assistant", "developer": "develop"}
    resolved: dict[str, WorkflowRoute] = {}

    for route_name, entrypoint_name in route_to_entrypoint.items():
        entrypoint = entrypoints.get(entrypoint_name)
        if not isinstance(entrypoint, dict) or not entrypoint.get("operator_facing"):
            raise ValueError(f"Expected operator-facing entrypoint {entrypoint_name!r}")
        workflow_id = entrypoint.get("workflow")
        workflow_registry = workflows.get(workflow_id)
        if not isinstance(workflow_registry, dict) or not workflow_registry.get("enabled"):
            raise ValueError(f"Workflow {workflow_id!r} is missing or disabled")

        contract_rel = workflow_registry.get("contract")
        contract_path = repo_root / str(contract_rel)
        if not contract_path.exists():
            raise FileNotFoundError(f"Workflow contract not found: {contract_path}")
        contract = _load_yaml(contract_path)
        if contract.get("workflow_id") != workflow_id:
            raise ValueError(f"Workflow id mismatch in {contract_path}")

        semantic = route_semantics.get(route_name)
        if not isinstance(semantic, dict):
            raise ValueError(f"Missing routing semantics for {route_name}")

        mcp = contract.get("mcp", {}) or {}
        deterministic = contract.get("deterministic_tools", {}) or {}
        resolved[route_name] = WorkflowRoute(
            name=route_name,  # type: ignore[arg-type]
            workflow_id=str(workflow_id),
            operator_entrypoint=entrypoint_name,
            source_path=str(contract_rel),
            source_sha256=_sha256(contract_path),
            version=str(contract.get("version", "unknown")),
            description=str(contract.get("description", "")),
            examples=[str(item) for item in contract.get("examples", [])],
            mcp_servers=[str(item) for item in mcp.get("servers", [])],
            deterministic_tools=[str(item) for item in deterministic.get("enabled", [])],
            routing_summary=str(semantic["summary"]),
            positive_signals=[str(item) for item in semantic.get("positive_signals", [])],
            negative_signals=[str(item) for item in semantic.get("negative_signals", [])],
        )

    unclear_summary: str | None = None
    if semantics_version == 1:
        unclear = route_semantics.get("unclear")
        if not isinstance(unclear, dict):
            raise ValueError("V1 routing semantics require routes.unclear")
        unclear_summary = str(unclear["summary"])

    return WorkflowCatalog(
        safeplane_yaml_sha256=_sha256(safeplane_path),
        semantics_sha256=_sha256(semantics_path),
        semantics_version=semantics_version,
        routes=resolved,
        unclear_summary=unclear_summary,
        route_instructions=str(_question(questions, "route")),
        ambiguity_instructions=_question(questions, "ambiguous", required=semantics_version == 1),
        route_identifiable_instructions=_question(
            questions, "route_identifiable", required=semantics_version == 2
        ),
        needs_clarification_instructions=_question(
            questions, "needs_clarification_before_execution", required=semantics_version == 2
        ),
        requires_multiple_workflows_instructions=_question(
            questions, "requires_multiple_workflows", required=semantics_version == 2
        ),
        repository_work_instructions=str(_question(questions, "repository_work")),
        missing_repository_profile_instructions=str(
            _question(questions, "missing_repository_profile")
        ),
        assistant_tool_need_instructions=str(_question(questions, "assistant_tool_need")),
    )
