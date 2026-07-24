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


def test_calendar_cli_create_list_show_cancel_rebuild_snapshot() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-calendar-"))
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(safeplane_home)

    try:
        created = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "create",
                "--title",
                "Planning block",
                "--start",
                "2026-07-12T09:00:00+02:00",
                "--end",
                "2026-07-12T10:00:00+02:00",
                "--description",
                "Focus time",
                "--json",
            ],
            env=env,
        )

        event = json.loads(created.stdout)
        event_id = event["id"]

        assert event_id.startswith("cal_evt_")
        assert event["status"] == "confirmed"

        day = run_command(
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

        day_events = json.loads(day.stdout)["events"]
        assert [item["id"] for item in day_events] == [event_id]

        week = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "list",
                "--week",
                "2026-07-07",
                "--json",
            ],
            env=env,
        )

        week_events = json.loads(week.stdout)["events"]
        assert [item["id"] for item in week_events] == [event_id]

        shown = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "show",
                event_id,
                "--json",
            ],
            env=env,
        )

        shown_event = json.loads(shown.stdout)
        assert shown_event["id"] == event_id
        assert shown_event["description"] == "Focus time"

        cancelled = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "cancel",
                event_id,
                "--json",
            ],
            env=env,
        )

        cancelled_event = json.loads(cancelled.stdout)
        assert cancelled_event["status"] == "cancelled"

        hidden = run_command(
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

        assert json.loads(hidden.stdout)["events"] == []

        included = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "list",
                "--day",
                "2026-07-12",
                "--include-cancelled",
                "--json",
            ],
            env=env,
        )

        assert [item["id"] for item in json.loads(included.stdout)["events"]] == [event_id]

        index_path = safeplane_home / "data" / "calendar" / "index.json"
        index_path.unlink()

        rebuilt = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "rebuild-index",
                "--json",
            ],
            env=env,
        )

        rebuilt_index = json.loads(rebuilt.stdout)
        assert event_id in rebuilt_index["events"]

        snapshot = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "snapshot",
                "--json",
            ],
            env=env,
        )

        snapshot_path = Path(json.loads(snapshot.stdout)["snapshot_path"])
        assert snapshot_path.exists()

        log_path = safeplane_home / "data" / "calendar" / "events.jsonl"
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [row["op"] for row in rows] == [
            "calendar_event_created",
            "calendar_event_cancelled",
        ]

    finally:
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_calendar_cli_rejects_invalid_event() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-calendar-"))
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(safeplane_home)

    try:
        result = run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "create",
                "--title",
                "Bad event",
                "--start",
                "2026-07-12T11:00:00+02:00",
                "--end",
                "2026-07-12T10:00:00+02:00",
            ],
            env=env,
            check=False,
        )

        assert result.returncode != 0
        assert "start must be before end" in result.stderr

    finally:
        shutil.rmtree(safeplane_home, ignore_errors=True)
