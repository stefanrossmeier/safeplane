from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
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


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_expect_error(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))

    raise AssertionError("Expected HTTP error")


def test_workflow_registry_lists_chat_and_assistant() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        data = get_json("http://localhost:18787/workflows")
        workflows = {item["entrypoint"]: item for item in data["workflows"]}

        assert sorted(workflows) == ["assistant", "chat", "slow"]

        assert workflows["chat"]["workflow_id"] == "chat"
        assert workflows["chat"]["version"] == "0.1.0"
        assert workflows["chat"]["enabled"] is True
        assert workflows["chat"]["tools"]["enabled"] is False
        assert workflows["chat"]["mcp"]["servers"] == []

        assert workflows["assistant"]["workflow_id"] == "assistant"
        assert workflows["assistant"]["version"] == "0.1.0"
        assert workflows["assistant"]["enabled"] is True
        assert workflows["assistant"]["tools"]["enabled"] is False
        assert workflows["assistant"]["mcp"]["servers"] == []

        assert workflows["slow"]["workflow_id"] == "slow"
        assert workflows["slow"]["version"] == "0.1.0"
        assert workflows["slow"]["enabled"] is True
        assert workflows["slow"]["tools"]["enabled"] is False
        assert workflows["slow"]["mcp"]["servers"] == []

        assistant = get_json("http://localhost:18787/workflows/assistant")
        assert assistant["workflow_id"] == "assistant"
        assert "Personal assistant foundation" in assistant["description"]

        cli = run_command(["./scripts/safeplane", "workflows"], env=env)
        assert "chat: chat 0.1.0 (enabled)" in cli.stdout
        assert "assistant: assistant 0.1.0 (enabled)" in cli.stdout

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)


def test_unknown_entrypoint_returns_clear_harness_error() -> None:
    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-acceptance-"))
    env = compose_env(safeplane_home)

    try:
        start_stack(env)

        status, body = post_json_expect_error(
            "http://localhost:18787/connector/missing",
            {
                "connector": "cli",
                "message": "This should fail",
            },
        )

        assert status == 404
        assert body["detail"] == "Unknown entrypoint: missing"

        cli = run_command(
            ["./scripts/safeplane", "run", "missing", "This should fail"],
            env=env,
            check=False,
        )
        assert cli.returncode != 0
        assert "Error: Unknown entrypoint: missing" in cli.stderr

    finally:
        stop_stack(env)
        shutil.rmtree(safeplane_home, ignore_errors=True)
