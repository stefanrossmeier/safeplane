from __future__ import annotations


class HarnessClientError(RuntimeError):
    """Base error for connector-to-harness communication."""


class HarnessUnavailableError(HarnessClientError):
    """The harness could not be reached within the configured timeout."""


class HarnessProtocolError(HarnessClientError):
    """The harness returned a response that violates the HTTP/JSON contract."""


class HarnessRejectedError(HarnessClientError):
    """The harness rejected a syntactically valid request."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Harness HTTP error {status_code}: {detail}")


class HarnessAuthorizationError(HarnessRejectedError):
    """The harness rejected a request for authentication/authorization reasons."""
