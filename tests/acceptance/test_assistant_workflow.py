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


def session_display_id_from_stdout(stdout: str) -> str:
    session_match = re.search(r"session:\s*([0-9a-f]{8})", stdout)
    assert session_match, stdout
    return session_match.group(1)


def test_assistant_workflow_is_separate_and_continuable() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        first = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "Help me plan today",
            ],
            env=env,
        )

        assert first.stderr == ""
        assert "[fake assistant] Help me plan today" in first.stdout

        session_display_id = session_display_id_from_stdout(first.stdout)

        second = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "--session",
                session_display_id,
                "Continue the plan",
            ],
            env=env,
        )

        assert second.stderr == ""
        assert "[fake assistant] Continue the plan" in second.stdout
        assert f"session: {session_display_id}" in second.stdout
        assert "turn: 2" in second.stdout

        session_files = list((safeplane_home / "sessions").glob("sess_*.json"))
        assert len(session_files) == 1

        session_data = json.loads(session_files[0].read_text(encoding="utf-8"))
        session_id = session_data["session_id"]

        assert session_data["workflow_id"] == "assistant"
        assert session_data["status"] == "completed"
        assert len(session_data["turns"]) == 2

        turn_002 = safeplane_home / "traces" / session_id / "turn_002"
        messages_data = json.loads((turn_002 / "messages.full.json").read_text(encoding="utf-8"))

        assert messages_data["workflow_id"] == "assistant"
        assert messages_data["message_role_schema"] == "llm_chat_roles"
        assert messages_data["messages"][0]["role"] == "system"
        assert "Safeplane assistant workflow" in messages_data["messages"][0]["content"]

        assert messages_data["messages"][1] == {
            "role": "user",
            "content": "Help me plan today",
        }
        assert messages_data["messages"][2] == {
            "role": "assistant",
            "content": "[fake assistant] Help me plan today",
        }
        assert messages_data["messages"][3] == {
            "role": "user",
            "content": "Continue the plan",
        }

        assistant_trace = (turn_002 / "agent-runtime.trace.jsonl").read_text(encoding="utf-8")
        assert "agent_runtime_started" in assistant_trace
        assert "model_messages_prepared" in assistant_trace

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_assistant_workflow_session_mismatch_is_rejected() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        chat = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "Say hello",
            ],
            env=env,
        )

        chat_session_display_id = session_display_id_from_stdout(chat.stdout)

        mismatch = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "--session",
                chat_session_display_id,
                "Continue this as assistant",
            ],
            env=env,
            check=False,
        )

        assert mismatch.returncode != 0
        assert "cannot continue with 'assistant'" in mismatch.stderr

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)
