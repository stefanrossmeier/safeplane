from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.workflow_registry import (
    DisabledWorkflowError,
    UnknownEntrypointError,
    WorkflowContractValidationError,
    build_registry,
    connector_is_exposed,
    connector_registry_entries,
    resolve_entrypoint_from_registry,
)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def valid_contract(workflow_id: str, entrypoint: str) -> dict:
    return {
        "workflow_id": workflow_id,
        "version": "0.1.0",
        "description": f"{workflow_id} workflow",
        "supported_entrypoints": [entrypoint],
        "examples": ["hello"],
        "prompt": {
            "id": f"{workflow_id}.system",
            "version": "v1",
            "path": f"/app/prompts/{workflow_id}/system.v1.md",
        },
        "model_profiles": {
            "default": {
                "litellm_model": "openrouter/openrouter/free",
                "temperature": 0.3,
                "max_tokens": 1000,
            }
        },
        "session": {
            "receives_history": True,
        },
        "concurrency": {
            "same_session": "serial",
        },
        "mcp": {
            "servers": [],
            "tools": [],
        },
        "tools": {
            "enabled": False,
            "allowed": [],
        },
        "functions": {
            "enabled": False,
            "allowed": [],
        },
        "io": {
            "input": {
                "messages": "list",
            },
            "output": {
                "final_message": "string",
            },
        },
    }


def test_registry_loads_chat_and_assistant(tmp_path: Path) -> None:
    write_yaml(tmp_path / "workflows/chat/workflow.yaml", valid_contract("chat", "chat"))
    write_yaml(tmp_path / "workflows/assistant/workflow.yaml", valid_contract("assistant", "assistant"))

    config = {
        "entrypoints": {
            "chat": {
                "connector": "cli",
                "workflow": "chat",
            },
            "assistant": {
                "connector": "cli",
                "workflow": "assistant",
            },
        },
        "workflows": {
            "chat": {
                "enabled": True,
                "contract": "workflows/chat/workflow.yaml",
                "service": "harness",
                "endpoint": "internal://harness/agent-runtime",
            },
            "assistant": {
                "enabled": True,
                "contract": "workflows/assistant/workflow.yaml",
                "service": "harness",
                "endpoint": "internal://harness/agent-runtime",
            },
        },
    }

    registry = build_registry(config, tmp_path / "safeplane.yaml")

    assert sorted(registry) == ["assistant", "chat"]
    assert registry["chat"].workflow_id == "chat"
    assert registry["assistant"].workflow_id == "assistant"


def test_registry_rejects_unknown_entrypoint() -> None:
    with pytest.raises(UnknownEntrypointError, match="Unknown entrypoint: missing"):
        resolve_entrypoint_from_registry({}, "missing")


def test_registry_rejects_disabled_workflow(tmp_path: Path) -> None:
    write_yaml(tmp_path / "workflows/chat/workflow.yaml", valid_contract("chat", "chat"))

    config = {
        "entrypoints": {
            "chat": {
                "connector": "cli",
                "workflow": "chat",
            },
        },
        "workflows": {
            "chat": {
                "enabled": False,
                "contract": "workflows/chat/workflow.yaml",
                "service": "harness",
                "endpoint": "internal://harness/agent-runtime",
            },
        },
    }

    registry = build_registry(config, tmp_path / "safeplane.yaml")

    with pytest.raises(DisabledWorkflowError, match="Workflow is disabled"):
        resolve_entrypoint_from_registry(registry, "chat")


def test_registry_validation_catches_missing_required_fields(tmp_path: Path) -> None:
    contract = valid_contract("chat", "chat")
    del contract["prompt"]
    write_yaml(tmp_path / "workflows/chat/workflow.yaml", contract)

    config = {
        "entrypoints": {
            "chat": {
                "connector": "cli",
                "workflow": "chat",
            },
        },
        "workflows": {
            "chat": {
                "enabled": True,
                "contract": "workflows/chat/workflow.yaml",
                "service": "harness",
                "endpoint": "internal://harness/agent-runtime",
            },
        },
    }

    with pytest.raises(WorkflowContractValidationError, match="missing required fields: prompt"):
        build_registry(config, tmp_path / "safeplane.yaml")


def test_registry_exposes_only_operator_facing_telegram_entrypoints() -> None:
    config_path = REPO_ROOT / "safeplane.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    registry = build_registry(config, config_path)

    exposed = connector_registry_entries(registry, "telegram")

    assert [entry.entrypoint_name for entry in exposed] == [
        "assistant",
        "chat",
        "develop",
    ]
    assert connector_is_exposed(registry["assistant"], "telegram") is True
    assert connector_is_exposed(registry["slow"], "telegram") is False
    assert registry["develop"].connectors["telegram"]["run_usage"] == (
        "/run develop --repo <repository-profile> <task>"
    )


def test_registry_rejects_incomplete_exposed_connector_metadata(tmp_path: Path) -> None:
    write_yaml(tmp_path / "workflows/chat/workflow.yaml", valid_contract("chat", "chat"))
    config = {
        "entrypoints": {
            "chat": {
                "workflow": "chat",
                "connectors": {
                    "telegram": {
                        "exposed": True,
                        "command": "chat",
                    }
                },
            }
        },
        "workflows": {
            "chat": {
                "enabled": True,
                "contract": "workflows/chat/workflow.yaml",
                "service": "harness",
                "endpoint": "internal://harness/agent-runtime",
            }
        },
    }

    with pytest.raises(WorkflowContractValidationError, match="must define usage"):
        build_registry(config, tmp_path / "safeplane.yaml")
