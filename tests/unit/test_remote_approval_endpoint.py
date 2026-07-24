from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import harness.main as harness_main
from harness.main import RemoteApprovalRequestBody, approve_remote_write
from harness.remote_write import (
    RemoteWriteConflictError,
    RemoteWriteResult,
)
from harness.run_store import save_run


def prepare_run(home: Path) -> dict:
    run = {
        "run_id": "run_remote_endpoint",
        "session_id": "sess_remote_endpoint",
        "session_display_id": "remoteep",
        "turn": 1,
        "workflow_id": "developer",
        "entrypoint": "develop",
        "connector": "cli",
        "status": "completed",
        "trace_path": str(home / "traces/sess_remote_endpoint/turn_001"),
        "created_at": "2026-07-19T08:00:00Z",
        "updated_at": "2026-07-19T08:00:00Z",
        "developer_pipeline": {
            "current_state": "waiting_for_remote_approval",
            "check_summary": {"status": "passed"},
            "review_verdict": "LGTM",
        },
    }
    save_run(home, run)
    return run


def result(run_id: str) -> RemoteWriteResult:
    return RemoteWriteResult(
        approval_id="remote_approval_1234567890abcdef12345678",
        run_id=run_id,
        branch_name="safeplane/remote-endpoint",
        commit_sha="a" * 40,
        pull_request_number=4,
        pull_request_url="https://github.example/fixture/repo/pull/4",
        draft=True,
        branch_reused=False,
        pull_request_reused=False,
        approval_ref=f"workspaces/{run_id}/remote-approvals/approval.json",
        evidence_ref=f"workspaces/{run_id}/remote-approvals/evidence.json",
    )


def test_remote_approval_endpoint_records_safe_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    run = prepare_run(home)
    monkeypatch.setenv("SAFEPLANE_HOME", str(home))
    monkeypatch.setattr(harness_main, "_developer_contract", lambda: {"contract": True})
    calls: list[dict] = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return result(run["run_id"])

    monkeypatch.setattr(harness_main, "execute_remote_write", fake_execute)
    response = approve_remote_write(
        run_id=run["run_id"],
        request=RemoteApprovalRequestBody(approved=True, connector="telegram"),
    )

    assert response.pull_request_url.endswith("/pull/4")
    assert calls == [
        {
            "safeplane_home": home,
            "contract": {"contract": True},
            "run_id": run["run_id"],
            "connector": "telegram",
        }
    ]
    trace = home / "traces/sess_remote_endpoint/turn_001/harness.trace.jsonl"
    row = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
    assert row["event"] == "remote_write_completed"
    assert row["output"]["pull_request_url"].endswith("/pull/4")
    assert "token" not in json.dumps(row).lower()


def test_remote_approval_endpoint_maps_conflict_to_http_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    run = prepare_run(home)
    monkeypatch.setenv("SAFEPLANE_HOME", str(home))
    monkeypatch.setattr(harness_main, "_developer_contract", lambda: {})

    def blocked(**_kwargs):
        raise RemoteWriteConflictError("workspace changed")

    monkeypatch.setattr(harness_main, "execute_remote_write", blocked)
    with pytest.raises(HTTPException) as exc:
        approve_remote_write(
            run_id=run["run_id"],
            request=RemoteApprovalRequestBody(approved=True, connector="cli"),
        )
    assert exc.value.status_code == 409
    assert "workspace changed" in str(exc.value.detail)
