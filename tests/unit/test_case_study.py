from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def write_completed_run(home: Path, run_id: str = "run_case_study") -> None:
    (home / "runs").mkdir(parents=True)
    run = {
        "run_id": run_id,
        "workflow_id": "developer",
        "repository_profile": "example-target",
        "repository_workspace": {
            "target_commit": "a" * 40,
            "external_source_commits": {"archdoc": "b" * 40},
        },
        "developer_pipeline": {
            "current_state": "completed",
            "completed_stages": [
                "repositories",
                "baseline_documentation",
                "analysis",
                "planning",
                "implementation",
                "checks",
                "final_documentation",
                "review",
                "pr",
                "remote_approval",
                "remote_write",
            ],
            "review_verdict": "LGTM",
            "review_plan_alignment": "ALIGNED",
            "remote_approval_binding": {
                "repository_name": "PrivateOrg/PrivateTarget",
            },
            "check_summary": {
                "status": "passed",
                "commands": [
                    {
                        "profile_id": "python_check",
                        "status": "passed",
                        "exit_code": 0,
                        "duration_ms": 12,
                        "network_policy": "disabled",
                    }
                ],
            },
            "agent_runs": [
                {
                    "stage_id": "analysis",
                    "model_profile": "developer_analysis",
                    "configured_model": "openrouter/example/analysis",
                    "actual_provider": "provider-a",
                    "actual_model": "example/analysis",
                    "retry_count": 1,
                    "duration_ms": 123,
                    "total_tokens": 456,
                    "cost": 0.01,
                }
            ],
            "artifacts": {
                "analysis.json": "private/path/analysis.json",
                "review.json": "private/path/review.json",
            },
            "remote_write": {
                "status": "completed",
                "draft": True,
                "pull_request_number": 7,
                "pull_request_url": "https://github.com/PrivateOrg/PrivateTarget/pull/7",
            },
        },
        "remote_write": {
            "status": "completed",
            "draft": True,
            "pull_request_number": 7,
            "pull_request_url": "https://github.com/PrivateOrg/PrivateTarget/pull/7",
        },
    }
    (home / "runs" / f"{run_id}.json").write_text(
        json.dumps(run), encoding="utf-8"
    )


def test_case_study_generator_uses_only_sanitized_metadata(tmp_path: Path) -> None:
    home = tmp_path / "safeplane-home"
    write_completed_run(home)
    output = tmp_path / "case-study.md"
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(home)

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "safeplane-case-study"),
            "run_case_study",
            "--output",
            str(output),
            "--task-summary",
            "Add a bounded dashboard behavior.",
            "--operator-findings",
            "The pull request was reviewable and focused.",
            "--defects-found",
            "No security-boundary defect was found.",
            "--fixes-made",
            "No Safeplane hardening change was required.",
            "--known-limitations",
            "This is one real repository task, not a benchmark.",
            "--telegram-proof",
            "Progress and the final PR URL were observed through Telegram.",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    text = output.read_text(encoding="utf-8")
    assert "Wrote sanitized case study" in completed.stdout
    assert "External Repository Case Study" in text
    assert "`#7`" in text
    assert "Plan alignment: `ALIGNED`" in text
    assert "openrouter/example/analysis" in text
    assert "provider-a" in text
    assert "tokens" in text.lower()
    assert "PrivateOrg/PrivateTarget" not in text
    assert "https://github.com" not in text
    assert str(home) not in text
    assert "private/path" not in text
    assert "analysis.json" in text


def test_case_study_generator_rejects_non_completed_run(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_completed_run(home)
    path = home / "runs" / "run_case_study.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    run["developer_pipeline"]["current_state"] = "waiting_for_remote_approval"
    path.write_text(json.dumps(run), encoding="utf-8")
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(home)

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "safeplane-case-study"),
            "run_case_study",
            "--output",
            str(tmp_path / "case.md"),
            "--task-summary",
            "summary",
            "--operator-findings",
            "findings",
            "--defects-found",
            "defects",
            "--fixes-made",
            "fixes",
            "--known-limitations",
            "limitations",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "completed remote-write run" in completed.stderr
