from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_command(
    args: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if check and result.returncode != 0:
        raise AssertionError(
            "Command failed:\n"
            f"{' '.join(args)}\n\n"
            f"Exit code: {result.returncode}\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}"
        )

    return result


def compose_env(safeplane_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(safeplane_home)
    return env


def test_calendar_cleanup_and_reset_are_deterministic_cli_only() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-calendar-cleanup-"))
    env = compose_env(safeplane_home)

    try:
        created = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "create",
                "--title",
                "Cleanup target",
                "--start",
                "2026-07-12T09:00:00+02:00",
                "--end",
                "2026-07-12T10:00:00+02:00",
                "--json",
            ],
            env=env,
        )

        event = json.loads(created.stdout)
        assert event["id"].startswith("cal_evt_")

        cleanup_dry_run = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "cleanup",
                "--dry-run",
                "--json",
            ],
            env=env,
        )

        cleanup_dry_run_data = json.loads(cleanup_dry_run.stdout)
        assert cleanup_dry_run_data["dry_run"] is True
        assert cleanup_dry_run_data["event_count"] == 1

        cleanup = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "cleanup",
                "--json",
            ],
            env=env,
        )

        cleanup_data = json.loads(cleanup.stdout)
        assert cleanup_data["status"] == "completed"
        assert cleanup_data["event_count"] == 1
        assert Path(cleanup_data["snapshot_path"]).exists()

        reset_without_confirm = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "reset",
            ],
            env=env,
            check=False,
        )

        assert reset_without_confirm.returncode == 1
        assert "reset requires --confirm RESET_CALENDAR" in reset_without_confirm.stderr

        reset_dry_run = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "reset",
                "--dry-run",
                "--json",
            ],
            env=env,
        )

        reset_dry_run_data = json.loads(reset_dry_run.stdout)
        assert reset_dry_run_data["dry_run"] is True
        assert reset_dry_run_data["event_count"] == 1

        reset = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "reset",
                "--confirm",
                "RESET_CALENDAR",
                "--json",
            ],
            env=env,
        )

        reset_data = json.loads(reset.stdout)
        assert reset_data["status"] == "completed"
        assert reset_data["event_count"] == 0
        assert Path(reset_data["backup_path"]).exists()

        listed = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "list",
                "--day",
                "2026-07-12",
                "--json",
            ],
            env=env,
        )

        assert json.loads(listed.stdout)["events"] == []

    finally:
        shutil.rmtree(safeplane_home, ignore_errors=True)
