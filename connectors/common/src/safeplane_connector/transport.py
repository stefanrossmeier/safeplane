from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from .errors import (
    HarnessAuthorizationError,
    HarnessProtocolError,
    HarnessRejectedError,
    HarnessUnavailableError,
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class HttpTransport:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        value = base_url.strip().rstrip("/")
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Harness base URL must use http:// or https://")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Harness base URL must not contain credentials")
        self.base_url = value
        self.timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            raise ValueError("Harness request path must start with '/'")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "X-Request-ID": request_id or str(uuid.uuid4()),
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(
                request,
                timeout=timeout_seconds or self.timeout_seconds,
            ) as response:
                content_type = response.headers.get_content_type()
                body = response.read().decode("utf-8", errors="strict")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = self._error_detail(body)
            error_type = HarnessAuthorizationError if exc.code in {401, 403} else HarnessRejectedError
            raise error_type(exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise HarnessUnavailableError(f"Harness connection failed: {reason}") from exc
        except http.client.IncompleteRead as exc:
            raise HarnessProtocolError("Harness response was truncated") from exc
        except UnicodeDecodeError as exc:
            raise HarnessProtocolError("Harness response is not valid UTF-8") from exc

        if content_type != "application/json":
            raise HarnessProtocolError(
                f"Harness response content type must be application/json, got {content_type!r}"
            )
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HarnessProtocolError("Harness response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise HarnessProtocolError("Harness JSON response must be an object")
        return value

    @staticmethod
    def _error_detail(body: str) -> str:
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            return body.strip() or "request rejected"
        if isinstance(value, dict) and value.get("detail"):
            return str(value["detail"])
        return body.strip() or "request rejected"
