from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.mcp_broker import McpToolBroker  # noqa: E402


class FakeDevBroker(McpToolBroker):
    def _post_json(self, endpoint: str, payload: dict) -> dict:
        assert payload["params"]["context"]["run_id"] == "run_broker"
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "isError": False,
                "structuredContent": {
                    "command": ["propose-patch"],
                    "cwd": "/workspace",
                    "workspace_root": "/workspace",
                    "exit_code": 0,
                    "truncated": False,
                    "evidence_ref": None,
                    "summary": "Update greeting",
                    "patch": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n"
                        "+++ b/README.md\n"
                        "@@ -1 +1 @@\n"
                        "-old\n"
                        "+new\n"
                    ),
                    "artifact_ref": None,
                },
            },
        }


def write_config(tmp_path: Path) -> Path:
    (tmp_path / "workflows" / "developer").mkdir(parents=True)
    (tmp_path / "safeplane.yaml").write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "dev-workspace": {
                        "enabled": True,
                        "transport": "internal_http_jsonrpc",
                        "endpoint": "http://dev-workspace-mcp:8080/mcp",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "developer" / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "workflow_id": "developer",
                "mcp": {
                    "allowed_servers": {
                        "dev-workspace": {"tools": ["dev_workspace_propose_patch"]}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "safeplane.yaml"


def test_broker_persists_patch_and_tool_evidence(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    home = tmp_path / "home"
    (home / "workspaces" / "run_broker" / "repo").mkdir(parents=True)
    (home / "runs").mkdir(parents=True)
    (home / "runs" / "run_broker.json").write_text(
        json.dumps(
            {
                "run_id": "run_broker",
                "workflow_id": "developer",
                "session_id": "sess_test",
                "turn": 1,
                "status": "running",
            }
        ),
        encoding="utf-8",
    )

    broker = FakeDevBroker(config_path=config, safeplane_home=home)
    response = broker.call_tool(
        {
            "workflow_id": "developer",
            "server_id": "dev-workspace",
            "tool_name": "dev_workspace_propose_patch",
            "arguments": {
                "summary": "Update greeting",
                "patch": (
                    "diff --git a/README.md b/README.md\n"
                    "--- a/README.md\n"
                    "+++ b/README.md\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
            },
            "session_id": "sess_test",
            "turn": 1,
            "run_id": "run_broker",
            "connector": "cli",
        }
    )

    artifact = home / response.structured_content["artifact_ref"]
    evidence = home / response.structured_content["evidence_ref"]
    assert artifact.read_text(encoding="utf-8").endswith("+new\n")

    rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["tool_name"] == "dev_workspace_propose_patch"
    assert rows[-1]["workspace_root"] == "/workspace"
    assert rows[-1]["exit_code"] == 0


def test_broker_rejects_unsafe_run_id_before_path_use(tmp_path: Path) -> None:
    import pytest

    config = write_config(tmp_path)
    broker = FakeDevBroker(config_path=config, safeplane_home=tmp_path / "home")

    with pytest.raises(Exception, match="run_id contains unsafe characters"):
        broker.call_tool(
            {
                "workflow_id": "developer",
                "server_id": "dev-workspace",
                "tool_name": "dev_workspace_propose_patch",
                "arguments": {
                    "summary": "unsafe",
                    "patch": "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -0,0 +1 @@\n+x\n",
                },
                "run_id": "run_../../outside",
            }
        )


class FakeApplyBroker(McpToolBroker):
    def _post_json(self, endpoint: str, payload: dict) -> dict:
        assert endpoint == "http://dev-workspace-apply-mcp:8080/mcp"
        assert payload["params"]["context"]["approval_id"].startswith("patch_approval_")
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "isError": False,
                "structuredContent": {
                    "command": ["patch", "--batch", "--forward", "-p1"],
                    "cwd": "/workspace",
                    "workspace_root": "/workspace",
                    "exit_code": 0,
                    "truncated": False,
                    "evidence_ref": None,
                    "proposal_id": payload["params"]["arguments"]["proposal_id"],
                    "patch_sha256": payload["params"]["arguments"]["patch_sha256"],
                    "changed_files": [
                        {
                            "path": "README.md",
                            "operation": "modified",
                            "before_sha256": "a" * 64,
                            "after_sha256": "b" * 64,
                            "before_size_bytes": 4,
                            "after_size_bytes": 4,
                        }
                    ],
                },
            },
        }


def write_apply_config(tmp_path: Path) -> Path:
    config = write_config(tmp_path)
    config_data = yaml.safe_load(config.read_text(encoding="utf-8"))
    config_data["mcp_servers"]["dev-workspace-apply"] = {
        "enabled": True,
        "transport": "internal_http_jsonrpc",
        "endpoint": "http://dev-workspace-apply-mcp:8080/mcp",
    }
    config.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    workflow = tmp_path / "workflows" / "developer" / "workflow.yaml"
    workflow_data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    workflow_data["mcp"]["approval_required_servers"] = {
        "dev-workspace-apply": {"tools": ["dev_workspace_apply_patch"]}
    }
    workflow_data["agents"] = {
        "documentation": {
            "allowed_mcp_servers": {
                "dev-workspace": {"tools": ["dev_workspace_propose_patch"]}
            }
        }
    }
    workflow.write_text(yaml.safe_dump(workflow_data), encoding="utf-8")
    return config


def test_approval_required_tool_needs_internal_token(tmp_path: Path) -> None:
    import pytest

    from harness.patch_approval_store import create_patch_approval, sha256_text

    config = write_apply_config(tmp_path)
    home = tmp_path / "home"
    run = {
        "run_id": "run_broker",
        "workflow_id": "developer",
        "session_id": "sess_test",
        "turn": 1,
        "status": "completed",
    }
    (home / "runs").mkdir(parents=True)
    (home / "runs" / "run_broker.json").write_text(json.dumps(run), encoding="utf-8")
    (home / "workspaces" / "run_broker" / "repo").mkdir(parents=True)

    patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
    proposal = {
        "proposal_id": "patch_proposal_broker",
        "patch_ref": "workspaces/run_broker/artifacts/patch_proposal_broker.patch",
        "patch_sha256": sha256_text(patch),
    }
    approval, token = create_patch_approval(
        home,
        run=run,
        proposal=proposal,
        connector="test",
    )
    (home / "workspaces" / "run_broker" / "apply" / approval["approval_id"] / "repo").mkdir(parents=True)

    broker = FakeApplyBroker(config_path=config, safeplane_home=home)
    request = {
        "workflow_id": "developer",
        "server_id": "dev-workspace-apply",
        "tool_name": "dev_workspace_apply_patch",
        "arguments": {
            "proposal_id": proposal["proposal_id"],
            "patch": patch,
            "patch_sha256": proposal["patch_sha256"],
        },
        "session_id": "sess_test",
        "turn": 1,
        "run_id": "run_broker",
        "connector": "test",
        "approval_id": approval["approval_id"],
    }

    with pytest.raises(Exception, match="internal approval token"):
        broker.call_tool(request)

    with pytest.raises(Exception, match="Agent is not allowed to use MCP tool"):
        broker.call_tool(
            {
                **request,
                "approval_token": token,
                "agent_id": "documentation",
            }
        )

    response = broker.call_tool({**request, "approval_token": token})
    assert response.structured_content["changed_files"][0]["path"] == "README.md"
    evidence = home / response.structured_content["evidence_ref"]
    row = json.loads(evidence.read_text(encoding="utf-8").splitlines()[-1])
    assert row["approval_id"] == approval["approval_id"]
    assert row["tool_name"] == "dev_workspace_apply_patch"
