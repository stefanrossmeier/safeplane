from __future__ import annotations

import urllib.parse
from typing import Any

from .models import (
    ConnectorMessage,
    ConnectorMessageResult,
    PatchApprovalResult,
    RemoteApprovalResult,
    RunListResult,
    WorkflowListResult,
)
from .transport import HttpTransport


class ConnectorSurface:
    def __init__(self, transport: HttpTransport, *, connector_name: str) -> None:
        self.transport = transport
        self.connector_name = connector_name

    def list_workflows(self) -> WorkflowListResult:
        return WorkflowListResult.from_mapping(
            self.transport.request_json("GET", "/workflows", timeout_seconds=10)
        )

    def start_workflow(
        self,
        entrypoint: str,
        message: str,
        *,
        session_ref: str | None = None,
        repository_profile: str | None = None,
        start_async: bool = False,
    ) -> ConnectorMessageResult:
        quoted = urllib.parse.quote(entrypoint, safe="")
        suffix = "/start" if start_async else ""
        request = ConnectorMessage(
            connector=self.connector_name,
            message=message,
            session_ref=session_ref,
            repository_profile=repository_profile,
        )
        return ConnectorMessageResult.from_mapping(
            self.transport.request_json(
                "POST",
                f"/connector/{quoted}{suffix}",
                payload=request.as_payload(),
                timeout_seconds=30 if start_async else 600,
            )
        )


class ControlSurface:
    def __init__(self, transport: HttpTransport, *, connector_name: str) -> None:
        self.transport = transport
        self.connector_name = connector_name

    def list_runs(self) -> RunListResult:
        return RunListResult.from_mapping(
            self.transport.request_json("GET", "/runs", timeout_seconds=10)
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(run_id, safe="")
        return self.transport.request_json("GET", f"/runs/{quoted}", timeout_seconds=10)

    def approve_patch(self, run_id: str, proposal_id: str) -> PatchApprovalResult:
        run = urllib.parse.quote(run_id, safe="")
        proposal = urllib.parse.quote(proposal_id, safe="")
        return PatchApprovalResult.from_mapping(
            self.transport.request_json(
                "POST",
                f"/runs/{run}/patches/{proposal}/approve",
                payload={"approved": True},
                timeout_seconds=180,
            )
        )

    def approve_remote(self, run_id: str) -> RemoteApprovalResult:
        run = urllib.parse.quote(run_id, safe="")
        return RemoteApprovalResult.from_mapping(
            self.transport.request_json(
                "POST",
                f"/runs/{run}/remote/approve",
                payload={"approved": True, "connector": self.connector_name},
                timeout_seconds=180,
            )
        )


class HarnessClient:
    def __init__(
        self,
        base_url: str,
        *,
        connector_name: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        transport = HttpTransport(base_url, timeout_seconds=timeout_seconds)
        self.connector = ConnectorSurface(transport, connector_name=connector_name)
        self.control = ControlSurface(transport, connector_name=connector_name)
