from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def prepare_acceptance_runtime_layout(runtime_root: Path) -> None:
    # Docker must not auto-create these bind sources as root: the runtime
    # containers deliberately run as UID/GID 10001 and need writable state.
    runtime_root.chmod(0o700)
    writable = (
        "sessions",
        "runs",
        "traces",
        "workspaces",
        "data/calendar",
        "data/notifications",
        "logs/mcp",
        "logs/scheduler",
    )
    for relative in writable:
        path = runtime_root / relative
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o777)

    config = runtime_root / "config"
    config.mkdir(parents=True, exist_ok=True)
    config.chmod(0o755)


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
    prepare_acceptance_runtime_layout(safeplane_home)
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = "safeplane_acceptance"
    env["SAFEPLANE_HOME"] = str(safeplane_home)
    env["MODEL_GATEWAY_MODE"] = "fake"
    env["SAFEPLANE_HARNESS_URL"] = "http://localhost:18787"
    return env


def wait_for_harness(env: dict[str, str], timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        result = run_command(
            [
                "python3",
                "-c",
                (
                    "import urllib.request; "
                    "print(urllib.request.urlopen('http://localhost:18787/health', timeout=2).read().decode())"
                ),
            ],
            env=env,
            check=False,
        )

        if result.returncode == 0 and '"status":"ok"' in result.stdout.replace(" ", ""):
            return

        time.sleep(1)

    logs = run_command(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.test.yml",
            "logs",
        ],
        env=env,
        check=False,
    )

    raise AssertionError(
        "Harness did not become healthy.\n\n"
        f"STDOUT:\n{logs.stdout}\n\n"
        f"STDERR:\n{logs.stderr}"
    )


def start_stack(env: dict[str, str]) -> None:
    run_command(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.test.yml",
            "up",
            "-d",
            "--build",
            "model-gateway",
            "calendar-task-mcp",
            "harness",
        ],
        env=env,
    )
    wait_for_harness(env)


def stop_stack(env: dict[str, str]) -> None:
    run_command(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.test.yml",
            "down",
            "--remove-orphans",
        ],
        env=env,
        check=False,
    )


def event_id_from_stdout(stdout: str) -> str:
    match = re.search(r"(cal_evt_[0-9a-f-]+)", stdout)
    assert match, stdout
    return match.group(1)


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_assistant_calendar_tools_go_through_harness_mcp() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        created = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "calendar create Planning block 2026-07-12T09:00:00+02:00 2026-07-12T10:00:00+02:00",
            ],
            env=env,
        )

        assert "Created calendar event cal_evt_" in created.stdout
        event_id = event_id_from_stdout(created.stdout)

        listed = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "calendar list day 2026-07-12",
            ],
            env=env,
        )

        assert f"- {event_id} Planning block:" in listed.stdout

        cancelled = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                f"calendar cancel {event_id}",
            ],
            env=env,
        )

        assert f"Cancelled calendar event {event_id}" in cancelled.stdout

        listed_after_cancel = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "calendar list day 2026-07-12",
            ],
            env=env,
        )

        assert "No calendar events found for day 2026-07-12." in listed_after_cancel.stdout

        access_log = safeplane_home / "logs" / "mcp" / "tool-access.jsonl"
        server_log = safeplane_home / "logs" / "mcp" / "calendar-task-mcp.jsonl"
        calendar_log = safeplane_home / "data" / "calendar" / "events.jsonl"

        assert access_log.exists()
        assert server_log.exists()
        assert calendar_log.exists()

        access_rows = read_jsonl(access_log)
        assert [row["decision"] for row in access_rows] == [
            "allowed",
            "allowed",
            "allowed",
            "allowed",
        ]

        assert [row["tool_name"] for row in access_rows] == [
            "calendar_create",
            "calendar_list",
            "calendar_cancel",
            "calendar_list",
        ]

        assert all(row["workflow_id"] == "assistant" for row in access_rows)

        server_rows = read_jsonl(server_log)
        assert [row["tool_name"] for row in server_rows] == [
            "calendar_create",
            "calendar_list",
            "calendar_cancel",
            "calendar_list",
        ]

        calendar_rows = read_jsonl(calendar_log)
        assert [row["op"] for row in calendar_rows] == [
            "calendar_event_created",
            "calendar_event_cancelled",
        ]

        trace_files = list((safeplane_home / "traces").glob("sess_*/turn_001/agent-runtime.trace.jsonl"))
        assert trace_files

        trace_text = "\n".join(path.read_text(encoding="utf-8") for path in trace_files)
        assert "deterministic_tool_invocation_detected" in trace_text
        assert "tool_invocation_started" in trace_text
        assert "tool_invocation_completed" in trace_text

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_chat_does_not_get_calendar_tool_behavior() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        result = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "calendar list day 2026-07-12",
            ],
            env=env,
        )

        assert "[fake chat] calendar list day 2026-07-12" in result.stdout
        assert not (safeplane_home / "logs" / "mcp" / "tool-access.jsonl").exists()

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)
