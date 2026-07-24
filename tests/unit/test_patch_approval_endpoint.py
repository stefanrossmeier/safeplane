from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.main import PatchApprovalRequest, approve_patch_proposal  # noqa: E402
from harness.mcp_schemas import McpBrokerResponse  # noqa: E402
from harness.patch_approval_store import sha256_text  # noqa: E402
from harness.run_store import save_run  # noqa: E402


class ApplyingBroker:
    def __init__(self, *, config_path: Path, safeplane_home: Path) -> None:
        self.home = safeplane_home

    def call_tool(self, request: dict) -> McpBrokerResponse:
        assert request["server_id"] == "dev-workspace-apply"
        assert request["approval_token"]
        repo = (
            self.home
            / "workspaces"
            / request["run_id"]
            / "apply"
            / request["approval_id"]
            / "repo"
        )
        target = repo / "src" / "app.py"
        before = target.read_text(encoding="utf-8")
        target.write_text("new\n", encoding="utf-8")
        return McpBrokerResponse(
            server_id="dev-workspace-apply",
            tool_name="dev_workspace_apply_patch",
            structured_content={
                "command": ["patch", "--batch", "--forward", "-p1"],
                "cwd": "/workspace",
                "workspace_root": "/workspace",
                "exit_code": 0,
                "truncated": False,
                "evidence_ref": f"workspaces/{request['run_id']}/evidence/tool-calls.jsonl",
                "proposal_id": request["arguments"]["proposal_id"],
                "patch_sha256": request["arguments"]["patch_sha256"],
                "changed_files": [
                    {
                        "path": "src/app.py",
                        "operation": "modified",
                        "before_sha256": sha256_text(before),
                        "after_sha256": sha256_text("new\n"),
                        "before_size_bytes": len(before.encode("utf-8")),
                        "after_size_bytes": 4,
                    }
                ],
            },
            is_error=False,
        )


def prepare_run(home: Path) -> tuple[dict, str]:
    run = {
        "run_id": "run_endpoint",
        "session_id": "sess_endpoint",
        "session_display_id": "endpoint",
        "turn": 1,
        "workflow_id": "developer",
        "entrypoint": "developer",
        "connector": "cli",
        "status": "completed",
        "trace_path": str(home / "traces" / "sess_endpoint" / "turn_001"),
        "created_at": "2026-07-18T12:00:00Z",
        "updated_at": "2026-07-18T12:00:00Z",
    }
    save_run(home, run)
    repo = home / "workspaces" / run["run_id"] / "repo"
    artifacts = home / "workspaces" / run["run_id"] / "artifacts"
    (repo / "src").mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (repo / "src" / "app.py").write_text("old\n", encoding="utf-8")

    proposal_id = "patch_proposal_endpoint"
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    patch_ref = f"workspaces/{run['run_id']}/artifacts/{proposal_id}.patch"
    (home / patch_ref).write_text(patch, encoding="utf-8")
    (artifacts / f"{proposal_id}.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run["run_id"],
                "workflow_id": "developer",
                "session_id": run["session_id"],
                "turn": 1,
                "proposal_id": proposal_id,
                "patch_ref": patch_ref,
                "patch_sha256": sha256_text(patch),
            }
        ),
        encoding="utf-8",
    )
    return run, proposal_id


def test_explicit_approval_applies_and_traces_file_writes(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config = tmp_path / "safeplane.yaml"
    config.write_text("mcp_servers: {}\n", encoding="utf-8")
    monkeypatch.setenv("SAFEPLANE_HOME", str(home))
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(config))

    import harness.mcp_broker as broker_module

    monkeypatch.setattr(broker_module, "McpToolBroker", ApplyingBroker)
    run, proposal_id = prepare_run(home)

    response = approve_patch_proposal(
        run_id=run["run_id"],
        proposal_id=proposal_id,
        request=PatchApprovalRequest(approved=True),
    )

    assert response.status == "applied"
    assert response.changed_files[0]["path"] == "src/app.py"
    target = home / "workspaces" / run["run_id"] / "repo" / "src" / "app.py"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert target.stat().st_mode & 0o222 == 0

    trace = home / "traces" / run["session_id"] / "turn_001" / "harness.trace.jsonl"
    events = [json.loads(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
    assert "patch_approval_granted" in events
    assert "patch_file_written" in events
    assert "patch_apply_completed" in events

    with pytest.raises(HTTPException) as duplicate:
        approve_patch_proposal(
            run_id=run["run_id"],
            proposal_id=proposal_id,
            request=PatchApprovalRequest(approved=True),
        )
    assert duplicate.value.status_code == 409
