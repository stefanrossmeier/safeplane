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


def test_local_chat_loop() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        result = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "Say hello in one sentence",
            ],
            env=env,
        )

        assert result.stderr == ""
        assert "[fake chat] Say hello in one sentence" in result.stdout

        session_display_id = session_display_id_from_stdout(result.stdout)

        session_files = list((safeplane_home / "sessions").glob("sess_*.json"))
        assert len(session_files) == 1

        session_file = session_files[0]
        session_data = json.loads(session_file.read_text(encoding="utf-8"))

        assert session_data["session_display_id"] == session_display_id
        assert session_data["session_id"].startswith(f"sess_{session_display_id}")
        assert session_data["connector"] == "cli"
        assert session_data["workflow_id"] == "chat"
        assert session_data["status"] == "completed"
        assert len(session_data["turns"]) == 1

        turn = session_data["turns"][0]
        assert turn["turn"] == 1
        assert turn["operator_message"] == "Say hello in one sentence"
        assert turn["final_message"] == "[fake chat] Say hello in one sentence"

        session_id = session_data["session_id"]
        trace_dir = safeplane_home / "traces" / session_id / "turn_001"

        assert trace_dir.exists()

        harness_trace = trace_dir / "harness.trace.jsonl"
        workflow_trace = trace_dir / "agent-runtime.trace.jsonl"
        gateway_trace = trace_dir / "model-gateway.trace.jsonl"
        messages_artifact = trace_dir / "messages.full.json"
        output_artifact = trace_dir / "output.json"

        assert harness_trace.exists()
        assert workflow_trace.exists()
        assert gateway_trace.exists()
        assert messages_artifact.exists()
        assert output_artifact.exists()

        harness_events = harness_trace.read_text(encoding="utf-8")
        assert "connector_message_received" in harness_events
        assert "session_created" in harness_events
        assert "entrypoint_resolved" in harness_events
        assert "agent_runtime_call_started" in harness_events
        assert "agent_runtime_call_completed" in harness_events
        assert "session_updated" in harness_events
        assert "run_queued" in harness_events
        assert "run_started" in harness_events
        assert "run_completed" in harness_events

        workflow_events = workflow_trace.read_text(encoding="utf-8")
        assert "agent_runtime_started" in workflow_events
        assert "workflow_contract_loaded" in workflow_events
        assert "prompt_loaded" in workflow_events
        assert "model_messages_prepared" in workflow_events
        assert "model_gateway_call_started" in workflow_events
        assert "model_gateway_call_completed" in workflow_events
        assert "agent_runtime_completed" in workflow_events

        gateway_events = gateway_trace.read_text(encoding="utf-8")
        assert "model_request_received" in gateway_events
        assert "model_profile_resolved" in gateway_events
        assert "model_response_returned" in gateway_events
        assert "openrouter" in gateway_events
        assert "fake" in gateway_events

        messages_data = json.loads(messages_artifact.read_text(encoding="utf-8"))
        assert messages_data["session_id"] == session_id
        assert messages_data["turn"] == 1
        assert messages_data["messages"][0]["role"] == "system"
        assert "Safeplane chat workflow" in messages_data["messages"][0]["content"]
        assert messages_data["messages"][1] == {
            "role": "user",
            "content": "Say hello in one sentence",
        }

        output_data = json.loads(output_artifact.read_text(encoding="utf-8"))
        assert output_data["session_id"] == session_id
        assert output_data["session_display_id"] == session_display_id
        assert output_data["turn"] == 1
        assert output_data["final_message"] == "[fake chat] Say hello in one sentence"

        repo_runtime_dirs = [
            REPO_ROOT / "sessions",
            REPO_ROOT / "traces",
            REPO_ROOT / "runs",
            REPO_ROOT / ".safeplane",
        ]

        for path in repo_runtime_dirs:
            assert not path.exists(), f"Runtime data should not be written into repo: {path}"

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_chat_session_continuation() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        first = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "Say hello",
            ],
            env=env,
        )

        session_display_id = session_display_id_from_stdout(first.stdout)

        second = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "--session",
                session_display_id,
                "What did I just ask?",
            ],
            env=env,
        )

        assert second.stderr == ""
        assert "[fake chat] What did I just ask?" in second.stdout
        assert f"session: {session_display_id}" in second.stdout
        assert "turn: 2" in second.stdout

        session_files = list((safeplane_home / "sessions").glob("sess_*.json"))
        assert len(session_files) == 1

        session_data = json.loads(session_files[0].read_text(encoding="utf-8"))
        session_id = session_data["session_id"]

        assert session_data["session_display_id"] == session_display_id
        assert session_data["workflow_id"] == "chat"
        assert session_data["status"] == "completed"
        assert len(session_data["turns"]) == 2

        assert session_data["turns"][0]["turn"] == 1
        assert session_data["turns"][0]["operator_message"] == "Say hello"
        assert session_data["turns"][0]["final_message"] == "[fake chat] Say hello"

        assert session_data["turns"][1]["turn"] == 2
        assert session_data["turns"][1]["operator_message"] == "What did I just ask?"
        assert session_data["turns"][1]["final_message"] == "[fake chat] What did I just ask?"

        turn_001 = safeplane_home / "traces" / session_id / "turn_001"
        turn_002 = safeplane_home / "traces" / session_id / "turn_002"

        assert turn_001.exists()
        assert turn_002.exists()

        harness_events_turn_2 = (turn_002 / "harness.trace.jsonl").read_text(encoding="utf-8")
        assert "session_continued" in harness_events_turn_2
        assert "agent_runtime_call_started" in harness_events_turn_2
        assert '"message_count": 3' in harness_events_turn_2

        messages_data = json.loads((turn_002 / "messages.full.json").read_text(encoding="utf-8"))
        messages = messages_data["messages"]

        assert messages_data["session_id"] == session_id
        assert messages_data["turn"] == 2
        assert messages_data["workflow_id"] == "chat"
        assert messages_data["message_role_schema"] == "llm_chat_roles"

        assert messages[0]["role"] == "system"
        assert messages[1] == {
            "role": "user",
            "content": "Say hello",
        }
        assert messages[2] == {
            "role": "assistant",
            "content": "[fake chat] Say hello",
        }
        assert messages[3] == {
            "role": "user",
            "content": "What did I just ask?",
        }

        gateway_events_turn_2 = (turn_002 / "model-gateway.trace.jsonl").read_text(encoding="utf-8")
        assert '"message_count": 4' in gateway_events_turn_2

        second_full_id = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "--session",
                session_id,
                "Continue by full id",
            ],
            env=env,
        )

        assert "turn: 3" in second_full_id.stdout

        updated_session = json.loads(session_files[0].read_text(encoding="utf-8"))
        assert len(updated_session["turns"]) == 3
        assert updated_session["turns"][2]["operator_message"] == "Continue by full id"

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)

def test_invalid_session_reference_returns_clear_error() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        result = run_command(
            [
                "./scripts/safeplane",
                "chat",
                "--session",
                "deadbeef",
                "This should fail",
            ],
            env=env,
            check=False,
        )

        assert result.returncode != 0
        assert "Unknown session: deadbeef" in result.stderr
        assert result.stdout == ""

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)

