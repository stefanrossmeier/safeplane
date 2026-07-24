from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
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
    match = re.search(r"session:\s*([0-9a-f]{8})", stdout)
    assert match, stdout
    return match.group(1)


def run_id_from_stdout(stdout: str) -> str:
    match = re.search(r"run:\s*(run_[0-9a-f-]+)", stdout)
    assert match, stdout
    return match.group(1)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_run_manager_every_request_creates_run_record() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        result = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "Help me plan today",
            ],
            env=env,
        )

        assert "run: run_" in result.stdout
        assert "status: completed" in result.stdout

        run_id = run_id_from_stdout(result.stdout)

        run_file = safeplane_home / "runs" / f"{run_id}.json"
        assert run_file.exists()

        run_data = json.loads(run_file.read_text(encoding="utf-8"))
        assert run_data["run_id"] == run_id
        assert run_data["status"] == "completed"
        assert run_data["workflow_id"] == "assistant"
        assert run_data["final_message"] == "[fake assistant] Help me plan today"

        session_file = next((safeplane_home / "sessions").glob("sess_*.json"))
        session_data = json.loads(session_file.read_text(encoding="utf-8"))
        assert session_data["turns"][0]["runs"][0]["run_id"] == run_id
        assert session_data["turns"][0]["runs"][0]["status"] == "completed"

        run_api = get_json(f"http://localhost:18787/runs/{run_id}")
        assert run_api["run_id"] == run_id
        assert run_api["status"] == "completed"

        runs_api = get_json("http://localhost:18787/runs")
        assert any(run["run_id"] == run_id for run in runs_api["runs"])

        status = run_command(
            [
                "./scripts/safeplane",
                "status",
                run_id,
            ],
            env=env,
        )
        assert f"run: {run_id}" in status.stdout
        assert "status: completed" in status.stdout

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_run_manager_slow_workflow_does_not_block_other_session() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        slow = subprocess.Popen(
            [
                "./scripts/safeplane",
                "run",
                "slow",
                "5",
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)

        quick_start = time.time()
        assistant = run_command(
            [
                "./scripts/safeplane",
                "assistant",
                "Can you answer while slow is running?",
            ],
            env=env,
        )
        quick_duration = time.time() - quick_start

        assert assistant.returncode == 0
        assert "[fake assistant] Can you answer while slow is running?" in assistant.stdout
        assert quick_duration < 4

        slow_stdout, slow_stderr = slow.communicate(timeout=20)

        assert slow.returncode == 0, slow_stderr
        assert "[slow workflow] Slept for 5 seconds." in slow_stdout
        assert "status: completed" in slow_stdout

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_run_manager_same_session_active_run_is_rejected() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        first = run_command(
            [
                "./scripts/safeplane",
                "run",
                "slow",
                "5",
            ],
            env=env,
        )

        session_display_id = session_display_id_from_stdout(first.stdout)

        slow = subprocess.Popen(
            [
                "./scripts/safeplane",
                "run",
                "slow",
                "--session",
                session_display_id,
                "5",
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)

        rejected = run_command(
            [
                "./scripts/safeplane",
                "run",
                "slow",
                "--session",
                session_display_id,
                "5",
            ],
            env=env,
            check=False,
        )

        slow_stdout, slow_stderr = slow.communicate(timeout=20)

        assert slow.returncode == 0, slow_stderr
        assert "[slow workflow] Slept for 5 seconds." in slow_stdout

        assert rejected.returncode != 0
        assert "Session has an active run: run_" in rejected.stderr

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)
