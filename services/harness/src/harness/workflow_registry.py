from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harness.developer_pipeline import validate_developer_pipeline_contract


REQUIRED_CONTRACT_FIELDS = [
    "workflow_id",
    "version",
    "description",
    "supported_entrypoints",
    "prompt",
    "model_profiles",
    "session",
    "io",
    "tools",
    "functions",
    "mcp",
]


@dataclass(frozen=True)
class WorkflowRegistryEntry:
    entrypoint_name: str
    workflow_id: str
    version: str
    description: str
    enabled: bool
    service: str
    endpoint: str
    contract_path: str
    supported_entrypoints: list[str]
    examples: list[str]
    prompt: dict[str, Any]
    model_profiles: dict[str, Any]
    session: dict[str, Any]
    io: dict[str, Any]
    tools: dict[str, Any]
    functions: dict[str, Any]
    mcp: dict[str, Any]
    agents: dict[str, Any]
    developer_pipeline: dict[str, Any]
    operator_facing: bool
    connectors: dict[str, dict[str, Any]]


class WorkflowRegistryError(Exception):
    pass


class UnknownEntrypointError(WorkflowRegistryError):
    pass


class DisabledWorkflowError(WorkflowRegistryError):
    pass


class WorkflowContractValidationError(WorkflowRegistryError):
    pass


def repo_config_root(config_path: Path) -> Path:
    return config_path.parent


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise WorkflowContractValidationError(f"Workflow contract not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise WorkflowContractValidationError(f"Workflow contract must be a mapping: {path}")

    return data


def validate_contract(
    *,
    workflow_id: str,
    entrypoint_name: str,
    contract_path: Path,
    contract: dict[str, Any],
) -> None:
    missing = [field for field in REQUIRED_CONTRACT_FIELDS if field not in contract]
    if missing:
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} is missing required fields: {', '.join(missing)}"
        )

    if contract["workflow_id"] != workflow_id:
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} has workflow_id {contract['workflow_id']!r}, "
            f"expected {workflow_id!r}"
        )

    supported_entrypoints = contract.get("supported_entrypoints")
    if not isinstance(supported_entrypoints, list) or not supported_entrypoints:
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} must define non-empty supported_entrypoints"
        )

    if entrypoint_name not in supported_entrypoints:
        raise WorkflowContractValidationError(
            f"Entrypoint {entrypoint_name!r} is not declared in supported_entrypoints "
            f"for workflow {workflow_id!r}"
        )

    prompt = contract.get("prompt")
    if not isinstance(prompt, dict) or not prompt.get("id") or not prompt.get("version") or not prompt.get("path"):
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} must define prompt.id, prompt.version, and prompt.path"
        )

    model_profiles = contract.get("model_profiles")
    if not isinstance(model_profiles, dict) or "default" not in model_profiles:
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} must define model_profiles.default"
        )

    io = contract.get("io")
    if not isinstance(io, dict) or "input" not in io or "output" not in io:
        raise WorkflowContractValidationError(
            f"Workflow contract {contract_path} must define io.input and io.output"
        )

    for policy_field in ["tools", "functions", "mcp"]:
        if not isinstance(contract.get(policy_field), dict):
            raise WorkflowContractValidationError(
                f"Workflow contract {contract_path} must define {policy_field} as a mapping"
            )

    if contract.get("developer_pipeline") is not None:
        try:
            validate_developer_pipeline_contract(contract)
        except Exception as exc:
            raise WorkflowContractValidationError(
                f"Workflow contract {contract_path} has an invalid developer pipeline: {exc}"
            ) from exc


def resolve_contract_path(config_path: Path, configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path

    return repo_config_root(config_path) / path


def normalize_connector_metadata(
    *,
    entrypoint_name: str,
    entrypoint: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    configured = entrypoint.get("connectors")
    if configured is None:
        legacy_connector = str(entrypoint.get("connector") or "cli")
        return {
            legacy_connector: {
                "exposed": True,
                "command": entrypoint_name,
                "usage": f"{entrypoint_name} <message>",
                "start_mode": "wait",
                "session_continuation": True,
                "arguments": [
                    {
                        "name": "message",
                        "required": True,
                        "consume_rest": True,
                    }
                ],
            }
        }

    if not isinstance(configured, dict) or not configured:
        raise WorkflowContractValidationError(
            f"Entrypoint {entrypoint_name!r} must define connectors as a non-empty mapping"
        )

    normalized: dict[str, dict[str, Any]] = {}
    for connector_name, raw_metadata in configured.items():
        if not isinstance(raw_metadata, dict):
            raise WorkflowContractValidationError(
                f"Entrypoint {entrypoint_name!r} connector {connector_name!r} must be a mapping"
            )
        metadata = dict(raw_metadata)
        exposed = metadata.get("exposed")
        if not isinstance(exposed, bool):
            raise WorkflowContractValidationError(
                f"Entrypoint {entrypoint_name!r} connector {connector_name!r} must define exposed as a boolean"
            )

        metadata.setdefault("session_continuation", False)
        if not isinstance(metadata["session_continuation"], bool):
            raise WorkflowContractValidationError(
                f"Entrypoint {entrypoint_name!r} connector {connector_name!r} must define session_continuation as a boolean"
            )

        metadata.setdefault("start_mode", "wait")
        if metadata["start_mode"] not in {"wait", "async"}:
            raise WorkflowContractValidationError(
                f"Entrypoint {entrypoint_name!r} connector {connector_name!r} start_mode must be 'wait' or 'async'"
            )

        arguments = metadata.get("arguments", [])
        if not isinstance(arguments, list):
            raise WorkflowContractValidationError(
                f"Entrypoint {entrypoint_name!r} connector {connector_name!r} arguments must be a list"
            )
        for index, argument in enumerate(arguments):
            if not isinstance(argument, dict) or not str(argument.get("name") or "").strip():
                raise WorkflowContractValidationError(
                    f"Entrypoint {entrypoint_name!r} connector {connector_name!r} argument {index} must define a name"
                )
            if argument.get("consume_rest") and index != len(arguments) - 1:
                raise WorkflowContractValidationError(
                    f"Entrypoint {entrypoint_name!r} connector {connector_name!r} consume_rest is only valid on the last argument"
                )

        if exposed:
            for field in ("command", "usage"):
                if not str(metadata.get(field) or "").strip():
                    raise WorkflowContractValidationError(
                        f"Entrypoint {entrypoint_name!r} connector {connector_name!r} must define {field} when exposed"
                    )
            if not arguments:
                raise WorkflowContractValidationError(
                    f"Entrypoint {entrypoint_name!r} connector {connector_name!r} must define arguments when exposed"
                )

        normalized[str(connector_name)] = metadata

    return normalized


def connector_metadata(
    entry: WorkflowRegistryEntry, connector_name: str
) -> dict[str, Any] | None:
    metadata = entry.connectors.get(connector_name)
    return dict(metadata) if metadata is not None else None


def connector_is_exposed(entry: WorkflowRegistryEntry, connector_name: str) -> bool:
    metadata = connector_metadata(entry, connector_name)
    return bool(entry.enabled and metadata and metadata.get("exposed"))


def connector_registry_entries(
    registry: dict[str, WorkflowRegistryEntry],
    connector_name: str,
    *,
    exposed_only: bool = True,
) -> list[WorkflowRegistryEntry]:
    entries = sorted(registry.values(), key=lambda item: item.entrypoint_name)
    if not exposed_only:
        return [entry for entry in entries if connector_name in entry.connectors]
    return [
        entry
        for entry in entries
        if entry.operator_facing and connector_is_exposed(entry, connector_name)
    ]


def build_registry(config: dict[str, Any], config_path: Path) -> dict[str, WorkflowRegistryEntry]:
    entrypoints = config.get("entrypoints", {})
    workflows = config.get("workflows", {})

    if not isinstance(entrypoints, dict):
        raise WorkflowContractValidationError("safeplane.yaml field 'entrypoints' must be a mapping")

    if not isinstance(workflows, dict):
        raise WorkflowContractValidationError("safeplane.yaml field 'workflows' must be a mapping")

    registry: dict[str, WorkflowRegistryEntry] = {}

    for entrypoint_name, entrypoint in entrypoints.items():
        if not isinstance(entrypoint, dict):
            raise WorkflowContractValidationError(f"Entrypoint {entrypoint_name!r} must be a mapping")

        workflow_id = entrypoint.get("workflow")
        if not workflow_id:
            raise WorkflowContractValidationError(f"Entrypoint {entrypoint_name!r} must define workflow")

        workflow_config = workflows.get(workflow_id)
        if not isinstance(workflow_config, dict):
            raise UnknownEntrypointError(
                f"Entrypoint {entrypoint_name!r} references unknown workflow {workflow_id!r}"
            )

        enabled = bool(workflow_config.get("enabled", True))
        contract_config_path = workflow_config.get("contract")
        endpoint = workflow_config.get("endpoint")
        service = workflow_config.get("service")

        if not contract_config_path:
            raise WorkflowContractValidationError(f"Workflow {workflow_id!r} must define contract")

        if not endpoint:
            raise WorkflowContractValidationError(f"Workflow {workflow_id!r} must define endpoint")

        if not service:
            raise WorkflowContractValidationError(f"Workflow {workflow_id!r} must define service")

        connector_definitions = normalize_connector_metadata(
            entrypoint_name=str(entrypoint_name),
            entrypoint=entrypoint,
        )
        contract_path = resolve_contract_path(config_path, str(contract_config_path))
        contract = load_yaml_file(contract_path)

        validate_contract(
            workflow_id=str(workflow_id),
            entrypoint_name=str(entrypoint_name),
            contract_path=contract_path,
            contract=contract,
        )

        registry[str(entrypoint_name)] = WorkflowRegistryEntry(
            entrypoint_name=str(entrypoint_name),
            workflow_id=str(workflow_id),
            version=str(contract["version"]),
            description=str(contract["description"]),
            enabled=enabled,
            service=str(service),
            endpoint=str(endpoint),
            contract_path=str(contract_config_path),
            supported_entrypoints=list(contract.get("supported_entrypoints", [])),
            examples=list(contract.get("examples", [])),
            prompt=dict(contract["prompt"]),
            model_profiles=dict(contract["model_profiles"]),
            session=dict(contract["session"]),
            io=dict(contract["io"]),
            tools=dict(contract["tools"]),
            functions=dict(contract["functions"]),
            mcp=dict(contract["mcp"]),
            agents=dict(contract.get("agents", {})),
            developer_pipeline=dict(contract.get("developer_pipeline", {})),
            operator_facing=bool(entrypoint.get("operator_facing", True)),
            connectors=connector_definitions,
        )

    return registry


def registry_entry_to_public_dict(entry: WorkflowRegistryEntry) -> dict[str, Any]:
    return {
        "entrypoint": entry.entrypoint_name,
        "workflow_id": entry.workflow_id,
        "version": entry.version,
        "description": entry.description,
        "enabled": entry.enabled,
        "service": entry.service,
        "endpoint": entry.endpoint,
        "contract": entry.contract_path,
        "supported_entrypoints": entry.supported_entrypoints,
        "examples": entry.examples,
        "prompt": entry.prompt,
        "model_profiles": entry.model_profiles,
        "session": entry.session,
        "io": entry.io,
        "tools": entry.tools,
        "functions": entry.functions,
        "mcp": entry.mcp,
        "agents": entry.agents,
        "developer_pipeline": entry.developer_pipeline,
        "operator_facing": entry.operator_facing,
        "connectors": entry.connectors,
    }


def resolve_entrypoint_from_registry(
    registry: dict[str, WorkflowRegistryEntry],
    entrypoint_name: str,
) -> WorkflowRegistryEntry:
    entry = registry.get(entrypoint_name)

    if entry is None:
        raise UnknownEntrypointError(f"Unknown entrypoint: {entrypoint_name}")

    if not entry.enabled:
        raise DisabledWorkflowError(f"Workflow is disabled for entrypoint: {entrypoint_name}")

    return entry
