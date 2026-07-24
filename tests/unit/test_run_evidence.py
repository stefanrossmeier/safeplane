from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "safeplane-evidence"


def test_evidence_latest_collects_run_pipeline_and_trace(tmp_path: Path) -> None:
    run_id = "run_example"
    trace = tmp_path / "traces" / "sess_example" / "turn_001"
    pipeline = tmp_path / "workspaces" / run_id / "pipeline"
    evidence = tmp_path / "workspaces" / run_id / "evidence"
    trace.mkdir(parents=True)
    pipeline.mkdir(parents=True)
    evidence.mkdir(parents=True)
    (trace / "agent-runtime.trace.jsonl").write_text("{}\n", encoding="utf-8")
    (pipeline / "pipeline.json").write_text(
        json.dumps({"current_state": "completed"}), encoding="utf-8"
    )
    (evidence / "tool-calls.jsonl").write_text("{}\n", encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "workflow_id": "developer",
                "entrypoint": "develop",
                "created_at": "2026-07-20T12:00:00+00:00",
                "trace_path": "/data/safeplane/traces/sess_example/turn_001",
                "developer_pipeline": {
                    "current_state": "completed",
                    "review_verdict": "LGTM",
                    "review_plan_alignment": "ALIGNED",
                    "check_summary": {"status": "passed"},
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "bundle"
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "latest", "--output", str(output), "--json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["run_id"] == run_id
    assert (output / "run.json").is_file()
    assert (output / "pipeline" / "pipeline.json").is_file()
    assert (output / "evidence" / "tool-calls.jsonl").is_file()
    assert (output / "trace" / "agent-runtime.trace.jsonl").is_file()
    assert (output / "SUMMARY.md").is_file()
    assert "Plan alignment: `ALIGNED`" in (output / "SUMMARY.md").read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert "run.json" in paths
    assert all("secrets" not in path for path in paths)
