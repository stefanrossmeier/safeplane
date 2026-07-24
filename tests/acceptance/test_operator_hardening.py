from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_operator_help_exposes_evidence_cleanup_and_draft_pr_tasks() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "safeplane"), "help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "safeplane evidence" in result.stdout
    assert "maintenance clean" in result.stdout
    assert "approve-pr" in result.stdout
    assert "docs/scripts.md" in result.stdout


def test_operator_can_collect_latest_evidence_and_cleanup_old_workspace(tmp_path: Path) -> None:
    run_id = "run_acceptance"
    runs = tmp_path / "runs"
    pipeline = tmp_path / "workspaces" / run_id / "pipeline"
    trace = tmp_path / "traces" / "sess_acceptance" / "turn_001"
    runs.mkdir(parents=True)
    pipeline.mkdir(parents=True)
    trace.mkdir(parents=True)
    (pipeline / "pipeline.json").write_text('{"current_state":"completed"}\n', encoding="utf-8")
    (trace / "agent-runtime.trace.jsonl").write_text("{}\n", encoding="utf-8")
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "workflow_id": "developer",
                "entrypoint": "develop",
                "created_at": "2026-07-20T12:00:00+00:00",
                "trace_path": "/data/safeplane/traces/sess_acceptance/turn_001",
                "developer_pipeline": {"current_state": "completed"},
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(tmp_path)
    bundle = tmp_path / "bundle"

    evidence = subprocess.run(
        [str(REPO_ROOT / "scripts" / "safeplane"), "evidence", "latest", "--output", str(bundle)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert evidence.returncode == 0, evidence.stderr
    assert (bundle / "SUMMARY.md").is_file()
    assert (bundle / "pipeline" / "pipeline.json").is_file()

    old = time.time() - 60 * 60 * 24 * 60
    for path in [tmp_path / "workspaces" / run_id, *list((tmp_path / "workspaces" / run_id).rglob("*"))]:
        os.utime(path, (old, old))

    cleanup = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "safeplane"),
            "maintenance",
            "clean",
            "--older-than",
            "30d",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cleanup.returncode == 0, cleanup.stderr
    assert not (tmp_path / "workspaces" / run_id).exists()
    assert (runs / f"{run_id}.json").is_file()
