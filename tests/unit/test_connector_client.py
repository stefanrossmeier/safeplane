from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Iterator

import pytest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "connectors/common/src"))

from safeplane_connector import (  # noqa: E402
    HarnessAuthorizationError,
    HarnessClient,
    HarnessProtocolError,
    HarnessRejectedError,
)
from safeplane_connector.transport import HttpTransport  # noqa: E402


@contextmanager
def server(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def send_json(self, status: int, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_shared_client_preserves_connector_payload_and_paths() -> None:
    captured: list[dict] = []

    class Handler(QuietHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            captured.append(
                {
                    "path": self.path,
                    "payload": payload,
                    "request_id": self.headers.get("X-Request-ID"),
                    "accept": self.headers.get("Accept"),
                }
            )
            self.send_json(
                200,
                {
                    "status": "completed",
                    "session_id": "sess_abc",
                    "session_display_id": "abc12345",
                    "turn": 2,
                    "run_id": "run_1",
                    "final_message": "done",
                    "trace_path": "/trace",
                },
            )

    with server(Handler) as base_url:
        client = HarnessClient(base_url, connector_name="cli")
        result = client.connector.start_workflow(
            "develop",
            "do the thing",
            session_ref="abc12345",
            repository_profile="target",
        )

    assert result.status == "completed"
    assert captured == [
        {
            "path": "/connector/develop",
            "payload": {
                "connector": "cli",
                "message": "do the thing",
                "session_ref": "abc12345",
                "repository_profile": "target",
            },
            "request_id": captured[0]["request_id"],
            "accept": "application/json",
        }
    ]
    assert captured[0]["request_id"]


def test_transport_maps_http_errors_without_exposing_headers() -> None:
    class Handler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_json(403, {"detail": "denied"})

    with server(Handler) as base_url:
        with pytest.raises(HarnessAuthorizationError, match="denied") as caught:
            HttpTransport(base_url).request_json("GET", "/forbidden")
    assert caught.value.status_code == 403


def test_transport_maps_non_authorization_rejection() -> None:
    class Handler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_json(409, {"detail": "not eligible"})

    with server(Handler) as base_url:
        with pytest.raises(HarnessRejectedError, match="not eligible"):
            HttpTransport(base_url).request_json("GET", "/conflict")


def test_transport_rejects_wrong_content_type_and_invalid_json() -> None:
    class TextHandler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b"hello"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class JsonHandler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b"{broken"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with server(TextHandler) as base_url:
        with pytest.raises(HarnessProtocolError, match="content type"):
            HttpTransport(base_url).request_json("GET", "/bad")
    with server(JsonHandler) as base_url:
        with pytest.raises(HarnessProtocolError, match="valid JSON"):
            HttpTransport(base_url).request_json("GET", "/bad")


def test_transport_rejects_embedded_url_credentials_without_echoing_them() -> None:
    with pytest.raises(ValueError, match="must not contain credentials") as caught:
        HttpTransport("http://operator:super-secret@example.invalid")
    assert "super-secret" not in str(caught.value)


def test_transport_does_not_follow_redirects() -> None:
    followed = 0

    class Handler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal followed
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/target")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            followed += 1
            self.send_json(200, {"unexpected": True})

    with server(Handler) as base_url:
        with pytest.raises(HarnessRejectedError) as caught:
            HttpTransport(base_url).request_json("GET", "/redirect")
    assert caught.value.status_code == 302
    assert followed == 0


def test_transport_does_not_retry_state_changing_requests() -> None:
    requests = 0

    class Handler(QuietHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal requests
            requests += 1
            self.send_json(503, {"detail": "try later"})

    with server(Handler) as base_url:
        with pytest.raises(HarnessRejectedError, match="try later"):
            HttpTransport(base_url).request_json("POST", "/change", payload={"x": 1})
    assert requests == 1


def test_transport_maps_truncated_response_to_protocol_error() -> None:
    class Handler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"partial":'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + 10))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

    with server(Handler) as base_url:
        with pytest.raises(HarnessProtocolError, match="truncated"):
            HttpTransport(base_url).request_json("GET", "/truncated")


def test_workflow_and_patch_models_reject_malformed_nested_items() -> None:
    from safeplane_connector.models import PatchApprovalResult, WorkflowListResult

    with pytest.raises(HarnessProtocolError, match="list of objects"):
        WorkflowListResult.from_mapping({"workflows": ["not-an-object"]})

    with pytest.raises(HarnessProtocolError, match="changed_files"):
        PatchApprovalResult.from_mapping(
            {
                "approval_id": "a",
                "proposal_id": "p",
                "run_id": "r",
                "status": "applied",
                "workspace_ref": "w",
                "changed_files": ["README.md"],
            }
        )
