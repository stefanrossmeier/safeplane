from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

import harness.agent_runtime as agent_runtime  # noqa: E402


def test_pipeline_workspace_readiness_barrier_validates_mcp_visible_commits(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict] = []
    traces: list[dict] = []

    class FakeBroker:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs})

        def call_tool(self, payload):
            calls.append(payload)
            return SimpleNamespace(
                structured_content={
                    "ready": True,
                    "workspace_version": 2,
                    "target_commit": "a" * 40,
                    "external_source_commits": {"archdoc": "b" * 40},
                    "evidence_ref": "workspaces/run_ready/evidence/tool-calls.jsonl",
                }
            )

    monkeypatch.setattr(agent_runtime, "McpToolBroker", FakeBroker)
    monkeypatch.setattr(
        agent_runtime,
        "write_runtime_trace",
        lambda **kwargs: traces.append(kwargs),
    )

    request = SimpleNamespace(
        safeplane_config_path=tmp_path / "safeplane.yaml",
        safeplane_home=tmp_path,
        session_id="sess_ready",
        turn=1,
        run_id="run_ready",
    )
    manifest = {
        "workspace_kind": "git_multi_repository",
        "manifest_ref": "workspaces/run_ready/workspace.json",
        "target": {"resolved_commit": "a" * 40},
        "external_sources": {"archdoc": {"resolved_commit": "b" * 40}},
    }

    result = agent_runtime.ensure_developer_workspace_ready(
        request=request,
        workflow_id="developer",
        workspace_manifest=manifest,
    )

    assert result is not None and result["ready"] is True
    payload = calls[1]
    assert payload["tool_name"] == "dev_workspace_ready"
    assert payload["connector"] == "developer-workspace-setup"
    assert "agent_id" not in payload
    assert traces[0]["event"] == "developer_workspace_ready"


def test_pipeline_workspace_readiness_barrier_rejects_commit_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeBroker:
        def __init__(self, **kwargs):
            pass

        def call_tool(self, payload):
            return SimpleNamespace(
                structured_content={
                    "ready": True,
                    "workspace_version": 2,
                    "target_commit": "c" * 40,
                    "external_source_commits": {"archdoc": "b" * 40},
                }
            )

    monkeypatch.setattr(agent_runtime, "McpToolBroker", FakeBroker)
    request = SimpleNamespace(
        safeplane_config_path=tmp_path / "safeplane.yaml",
        safeplane_home=tmp_path,
        session_id="sess_ready",
        turn=1,
        run_id="run_ready",
    )
    manifest = {
        "workspace_kind": "git_multi_repository",
        "target": {"resolved_commit": "a" * 40},
        "external_sources": {"archdoc": {"resolved_commit": "b" * 40}},
    }

    with pytest.raises(RuntimeError, match="target commit"):
        agent_runtime.ensure_developer_workspace_ready(
            request=request,
            workflow_id="developer",
            workspace_manifest=manifest,
        )
