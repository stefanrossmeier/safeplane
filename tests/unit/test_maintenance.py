from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "safeplane-maintenance"


def run_maintenance(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(tmp_path)

    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_old(path: Path) -> None:
    old = time.time() - 60 * 60 * 24 * 60
    os.utime(path, (old, old))
    for item in path.rglob("*"):
        os.utime(item, (old, old))


def test_storage_json_creates_expected_directories(tmp_path: Path):
    result = run_maintenance(tmp_path, "storage", "--json")

    assert result.returncode == 0, result.stderr

    data = json.loads(result.stdout)
    names = {item["name"] for item in data["directories"]}

    assert "sessions" in names
    assert "runs" in names
    assert "traces" in names
    assert "artifacts" in names
    assert "workspaces" in names
    assert "checkouts" in names
    assert "data" in names
    assert "backups" in names
    assert "secrets" not in names
    assert "maintenance" in names
    assert not (tmp_path / "secrets").exists()

    protected = {
        item["name"]
        for item in data["directories"]
        if item["protected"]
    }

    assert {"data", "backups", "config"} <= protected


def test_storage_reports_existing_legacy_secrets_without_creating_them(tmp_path: Path):
    write_file(tmp_path / "secrets" / "legacy-token", "legacy-secret\n")

    result = run_maintenance(tmp_path, "storage", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    legacy = next(item for item in data["directories"] if item["name"] == "secrets")
    assert legacy["protected"] is True
    assert legacy["files"] == 1


def test_clean_dry_run_does_not_delete_old_trace(tmp_path: Path):
    trace_dir = tmp_path / "traces" / "sess_old"
    write_file(trace_dir / "turn_001" / "model-gateway.trace.jsonl")
    make_old(trace_dir)

    result = run_maintenance(tmp_path, "clean", "--dry-run", "--older-than", "30d")

    assert result.returncode == 0, result.stderr
    assert "Dry run. No files deleted." in result.stdout
    assert trace_dir.exists()


def test_clean_deletes_old_trace_but_keeps_sessions_and_legacy_secrets(tmp_path: Path):
    trace_dir = tmp_path / "traces" / "sess_old"
    session_file = tmp_path / "sessions" / "sess_old.json"
    secret_file = tmp_path / "secrets" / "openrouter_api_key"

    write_file(trace_dir / "turn_001" / "model-gateway.trace.jsonl")
    write_file(session_file, '{"session_id": "sess_old"}')
    write_file(secret_file, "legacy-secret\n")
    make_old(trace_dir)

    result = run_maintenance(tmp_path, "clean", "--older-than", "30d")

    assert result.returncode == 0, result.stderr
    assert not trace_dir.exists()
    assert session_file.exists()
    assert secret_file.exists()


def test_clean_skips_active_session_trace(tmp_path: Path):
    trace_dir = tmp_path / "traces" / "sess_active"
    session_file = tmp_path / "sessions" / "sess_active.json"

    write_file(trace_dir / "turn_001" / "model-gateway.trace.jsonl")
    write_file(session_file, '{"session_id": "sess_active", "status": "running"}')
    make_old(trace_dir)

    result = run_maintenance(tmp_path, "clean", "--older-than", "30d")

    assert result.returncode == 0, result.stderr
    assert trace_dir.exists()
    assert "active session" in result.stdout or "Skipped: 1" in result.stdout


def test_clean_all_requires_confirmation_in_non_interactive_mode(tmp_path: Path):
    write_file(tmp_path / "traces" / "sess_old" / "turn_001" / "x.jsonl")

    result = run_maintenance(tmp_path, "clean-all")

    assert result.returncode == 2
    assert "Refusing clean-all without --confirm DELETE" in result.stdout
    assert (tmp_path / "traces").exists()


def test_clean_all_deletes_runtime_state_but_keeps_protected_dirs(tmp_path: Path):
    write_file(tmp_path / "sessions" / "sess_old.json")
    write_file(tmp_path / "runs" / "run_old.json")
    write_file(tmp_path / "traces" / "sess_old" / "turn_001" / "x.jsonl")
    write_file(tmp_path / "artifacts" / "artifact.txt")
    write_file(tmp_path / "workspaces" / "workspace.txt")
    write_file(tmp_path / "checkouts" / "checkout.txt")

    write_file(tmp_path / "secrets" / "openrouter_api_key", "legacy-secret\n")
    write_file(tmp_path / "data" / "calendar" / "events.jsonl")
    write_file(tmp_path / "backups" / "backup.txt")
    write_file(tmp_path / "config" / "local.json")

    result = run_maintenance(tmp_path, "clean-all", "--confirm", "DELETE")

    assert result.returncode == 0, result.stderr

    assert not (tmp_path / "sessions" / "sess_old.json").exists()
    assert not (tmp_path / "runs" / "run_old.json").exists()
    assert not (tmp_path / "traces" / "sess_old").exists()
    assert not (tmp_path / "artifacts" / "artifact.txt").exists()
    assert not (tmp_path / "workspaces" / "workspace.txt").exists()
    assert not (tmp_path / "checkouts" / "checkout.txt").exists()

    assert (tmp_path / "secrets" / "openrouter_api_key").exists()
    assert (tmp_path / "data" / "calendar" / "events.jsonl").exists()
    assert (tmp_path / "backups" / "backup.txt").exists()
    assert (tmp_path / "config" / "local.json").exists()


def test_clean_deletes_old_completed_workspace(tmp_path: Path):
    workspace = tmp_path / "workspaces" / "run_old"
    run_file = tmp_path / "runs" / "run_old.json"
    write_file(workspace / "pipeline" / "pipeline.json", '{}')
    write_file(run_file, '{"run_id":"run_old","status":"completed"}')
    make_old(workspace)

    result = run_maintenance(tmp_path, "clean", "--older-than", "30d")

    assert result.returncode == 0, result.stderr
    assert not workspace.exists()
    assert run_file.exists()


def test_clean_keeps_old_workspace_waiting_for_remote_write(tmp_path: Path):
    workspace = tmp_path / "workspaces" / "run_waiting"
    run_file = tmp_path / "runs" / "run_waiting.json"
    write_file(workspace / "pipeline" / "pipeline.json", '{}')
    write_file(
        run_file,
        json.dumps(
            {
                "run_id": "run_waiting",
                "status": "completed",
                "developer_pipeline": {
                    "current_state": "waiting_for_remote_approval",
                    "remote_approval_possible": True,
                },
            }
        ),
    )
    make_old(workspace)

    result = run_maintenance(tmp_path, "clean", "--older-than", "30d")

    assert result.returncode == 0, result.stderr
    assert workspace.exists()
    assert "awaiting remote write" in result.stdout or "Skipped: 1" in result.stdout
