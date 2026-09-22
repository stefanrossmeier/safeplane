from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
PYTHONPATH = os.pathsep.join(
    [
        str(ROOT / "connectors/common/src"),
        str(ROOT / "connectors/cli/src"),
    ]
)


@contextmanager
def fake_harness() -> Iterator[tuple[str, list[dict]]]:
    captured: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def send_json(self, status: int, value: object) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def record(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length)) if length else None
            item = {"method": self.command, "path": self.path, "payload": payload}
            captured.append(item)
            return item

        def do_GET(self) -> None:  # noqa: N802
            item = self.record()
            if item["path"] == "/workflows":
                self.send_json(
                    200,
                    {
                        "workflows": [
                            {
                                "entrypoint": "assistant",
                                "workflow_id": "assistant",
                                "version": "0.1.0",
                                "description": "Assistant workflow",
                                "enabled": True,
                            }
                        ]
                    },
                )
            elif item["path"] == "/runs":
                self.send_json(
                    200,
                    {
                        "runs": [
                            {
                                "run_id": "run_1",
                                "status": "completed",
                                "workflow_id": "assistant",
                                "session_display_id": "abc12345",
                                "turn": 1,
                            }
                        ]
                    },
                )
            elif item["path"] == "/runs/run_1":
                self.send_json(
                    200,
                    {
                        "run_id": "run_1",
                        "status": "completed",
                        "session_display_id": "abc12345",
                        "turn": 1,
                        "workflow_id": "assistant",
                        "entrypoint": "assistant",
                        "trace_path": "/trace",
                        "final_message": "done",
                    },
                )
            else:
                self.send_json(404, {"detail": "missing"})

        def do_POST(self) -> None:  # noqa: N802
            item = self.record()
            if item["path"] == "/connector/missing":
                self.send_json(404, {"detail": "missing"})
            elif item["path"].startswith("/connector/"):
                self.send_json(
                    200,
                    {
                        "status": "completed",
                        "session_id": "sess_abc",
                        "session_display_id": "abc12345",
                        "turn": 1,
                        "run_id": "run_1",
                        "final_message": f"reply: {item['payload']['message']}",
                        "trace_path": "/trace",
                    },
                )
            elif item["path"] == "/runs/run_1/patches/proposal_1/approve":
                self.send_json(
                    200,
                    {
                        "approval_id": "approval_1",
                        "proposal_id": "proposal_1",
                        "run_id": "run_1",
                        "status": "applied",
                        "workspace_ref": "workspaces/run_1/apply",
                        "evidence_ref": "evidence.json",
                        "changed_files": [{"operation": "modify", "path": "README.md"}],
                    },
                )
            elif item["path"] == "/runs/run_1/remote/approve":
                self.send_json(
                    200,
                    {
                        "approval_id": "remote_1",
                        "run_id": "run_1",
                        "status": "completed",
                        "branch_name": "safeplane/run-1",
                        "commit_sha": "a" * 40,
                        "pull_request_url": "https://example.invalid/pr/1",
                        "branch_reused": False,
                        "pull_request_reused": False,
                        "evidence_ref": "remote-evidence.json",
                    },
                )
            else:
                self.send_json(404, {"detail": "missing"})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", captured
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


def cli(*args: str, harness_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    env["SAFEPLANE_HARNESS_URL"] = harness_url
    return subprocess.run(
        [sys.executable, "-m", "safeplane_cli.main", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_workflow_request_preserves_message_session_and_repository_profile() -> None:
    with fake_harness() as (url, captured):
        result = cli(
            "develop",
            "--repo",
            "target",
            "--session",
            "abc12345",
            "Implement",
            "one bounded change",
            harness_url=url,
        )
    assert result.returncode == 0, result.stderr
    assert "reply: Implement one bounded change" in result.stdout
    assert "session: abc12345" in result.stdout
    assert captured == [
        {
            "method": "POST",
            "path": "/connector/develop",
            "payload": {
                "connector": "cli",
                "message": "Implement one bounded change",
                "session_ref": "abc12345",
                "repository_profile": "target",
            },
        }
    ]


def test_cli_auto_routes_without_requiring_an_explicit_workflow() -> None:
    with fake_harness() as (url, captured):
        result = cli(
            "auto",
            "Remind",
            "me",
            "tomorrow",
            "to",
            "call",
            "the",
            "dentist",
            harness_url=url,
        )
    assert result.returncode == 0, result.stderr
    assert captured == [
        {
            "method": "POST",
            "path": "/connector/auto",
            "payload": {
                "connector": "cli",
                "message": "Remind me tomorrow to call the dentist",
            },
        }
    ]


def test_cli_auto_accepts_repository_context_for_developer_routing() -> None:
    with fake_harness() as (url, captured):
        result = cli(
            "auto",
            "--repo",
            "target",
            "Fix",
            "the",
            "bug",
            "in",
            "this",
            "repository",
            harness_url=url,
        )
    assert result.returncode == 0, result.stderr
    assert captured[0]["path"] == "/connector/auto"
    assert captured[0]["payload"]["repository_profile"] == "target"


def test_cli_json_output_is_machine_readable_and_stdout_only() -> None:
    with fake_harness() as (url, _):
        result = cli("workflows", "--output", "json", harness_url=url)
    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["workflows"][0]["entrypoint"] == "assistant"
    assert "\x1b" not in result.stdout


def test_cli_control_commands_map_to_expected_paths_and_payloads() -> None:
    with fake_harness() as (url, captured):
        runs = cli("runs", harness_url=url)
        status = cli("status", "run_1", harness_url=url)
        patch = cli("approve-patch", "run_1", "proposal_1", harness_url=url)
        remote = cli("approve-pr", "run_1", harness_url=url)
    assert all(item.returncode == 0 for item in (runs, status, patch, remote))
    assert "run_1 completed assistant" in runs.stdout
    assert "run: run_1" in status.stdout
    assert "approval: approval_1" in patch.stdout
    assert "draft PR: https://example.invalid/pr/1" in remote.stdout
    assert [item["path"] for item in captured] == [
        "/runs",
        "/runs/run_1",
        "/runs/run_1/patches/proposal_1/approve",
        "/runs/run_1/remote/approve",
    ]
    assert captured[-2]["payload"] == {"approved": True}
    assert captured[-1]["payload"] == {"approved": True, "connector": "cli"}


def test_cli_rejects_repo_for_non_develop_before_network_access() -> None:
    with fake_harness() as (url, captured):
        result = cli("run", "assistant", "--repo", "target", "message", harness_url=url)
    assert result.returncode == 2
    assert "--repo is only valid for the develop or auto entrypoint" in result.stderr
    assert captured == []


def test_cli_accepts_message_beginning_with_dash() -> None:
    with fake_harness() as (url, captured):
        result = cli("chat", "--", "-literal", harness_url=url)
    assert result.returncode == 0, result.stderr
    assert captured[0]["payload"]["message"] == "-literal"


def test_cli_treats_output_tokens_after_double_dash_as_message_data() -> None:
    with fake_harness() as (url, captured):
        result = cli("chat", "--", "--output", "json", harness_url=url)
    assert result.returncode == 0, result.stderr
    assert captured[0]["payload"]["message"] == "--output json"
    assert result.stdout.startswith("reply: --output json")


def test_cli_maps_harness_rejection_to_stable_exit_code() -> None:
    with fake_harness() as (url, _):
        result = cli("run", "missing", "message", harness_url=url)
    assert result.returncode == 5
    assert "Error: missing" in result.stderr


def test_cli_unavailable_harness_has_stable_exit_code() -> None:
    result = cli("chat", "message", harness_url="http://127.0.0.1:9")
    assert result.returncode == 3
    assert "Harness connection failed" in result.stderr


def test_cli_help_documents_full_network_command_surface() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    result = subprocess.run(
        [sys.executable, "-m", "safeplane_cli.main", "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    for command in (
        "workflows",
        "runs",
        "status",
        "approve-patch",
        "approve-pr",
        "run",
        "auto",
        "chat",
        "assistant",
        "developer",
        "develop",
    ):
        assert command in result.stdout


def test_run_renderer_rejects_malformed_nested_pipeline_shape() -> None:
    from safeplane_cli.rendering import render_run
    from safeplane_connector.errors import HarnessProtocolError

    run = {
        "run_id": "run_1",
        "status": "completed",
        "session_display_id": "abc12345",
        "turn": 1,
        "workflow_id": "develop",
        "entrypoint": "develop",
        "trace_path": "/trace",
        "developer_pipeline": {"agent_runs": ["not-an-object"]},
    }
    with pytest.raises(HarnessProtocolError, match="agent_runs"):
        render_run(run)
