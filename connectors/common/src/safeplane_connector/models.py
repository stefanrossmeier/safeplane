from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import HarnessProtocolError


def _required(mapping: Mapping[str, Any], key: str, expected: type) -> Any:
    if key not in mapping:
        raise HarnessProtocolError(f"Harness response is missing required field: {key}")
    value = mapping[key]
    if not isinstance(value, expected):
        raise HarnessProtocolError(
            f"Harness response field {key!r} must be {expected.__name__}"
        )
    return value


@dataclass(frozen=True)
class ConnectorMessage:
    message: str
    session_ref: str | None = None
    repository_profile: str | None = None
    connector: str = "cli"

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connector": self.connector,
            "message": self.message,
        }
        if self.session_ref:
            payload["session_ref"] = self.session_ref
        if self.repository_profile:
            payload["repository_profile"] = self.repository_profile
        return payload


@dataclass(frozen=True)
class ConnectorMessageResult:
    status: str
    session_id: str
    session_display_id: str
    turn: int
    run_id: str
    final_message: str | None
    trace_path: str
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConnectorMessageResult":
        raw = dict(value)
        status = _required(value, "status", str)
        session_id = _required(value, "session_id", str)
        session_display_id = _required(value, "session_display_id", str)
        turn = _required(value, "turn", int)
        run_id = _required(value, "run_id", str)
        trace_path = _required(value, "trace_path", str)
        final_message = value.get("final_message")
        if final_message is not None and not isinstance(final_message, str):
            raise HarnessProtocolError("Harness response field 'final_message' must be a string or null")
        return cls(
            status=status,
            session_id=session_id,
            session_display_id=session_display_id,
            turn=turn,
            run_id=run_id,
            final_message=final_message,
            trace_path=trace_path,
            raw=raw,
        )


@dataclass(frozen=True)
class WorkflowSummary:
    entrypoint: str
    workflow_id: str
    version: str
    description: str
    enabled: bool
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkflowSummary":
        enabled = value.get("enabled")
        if not isinstance(enabled, bool):
            raise HarnessProtocolError("Harness workflow field 'enabled' must be a boolean")
        return cls(
            entrypoint=_required(value, "entrypoint", str),
            workflow_id=_required(value, "workflow_id", str),
            version=_required(value, "version", str),
            description=_required(value, "description", str),
            enabled=enabled,
            raw=dict(value),
        )


@dataclass(frozen=True)
class WorkflowListResult:
    workflows: tuple[WorkflowSummary, ...]
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkflowListResult":
        items = value.get("workflows")
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise HarnessProtocolError(
                "Harness response field 'workflows' must be a list of objects"
            )
        return cls(
            workflows=tuple(WorkflowSummary.from_mapping(item) for item in items),
            raw=dict(value),
        )


@dataclass(frozen=True)
class RunListResult:
    runs: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RunListResult":
        items = value.get("runs")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise HarnessProtocolError("Harness response field 'runs' must be a list of objects")
        for item in items:
            for key, expected in (
                ("run_id", str),
                ("status", str),
                ("workflow_id", str),
                ("session_display_id", str),
                ("turn", int),
            ):
                _required(item, key, expected)
        return cls(runs=tuple(dict(item) for item in items), raw=dict(value))


@dataclass(frozen=True)
class PatchApprovalResult:
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PatchApprovalResult":
        for key, expected in (
            ("approval_id", str),
            ("proposal_id", str),
            ("run_id", str),
            ("status", str),
            ("workspace_ref", str),
        ):
            _required(value, key, expected)
        changed_files = value.get("changed_files")
        if not isinstance(changed_files, list) or not all(
            isinstance(item, Mapping) for item in changed_files
        ):
            raise HarnessProtocolError(
                "Harness response field 'changed_files' must be a list of objects"
            )
        for item in changed_files:
            _required(item, "operation", str)
            _required(item, "path", str)
        evidence_ref = value.get("evidence_ref")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            raise HarnessProtocolError(
                "Harness response field 'evidence_ref' must be a string or null"
            )
        return cls(raw=dict(value))


@dataclass(frozen=True)
class RemoteApprovalResult:
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteApprovalResult":
        for key, expected in (
            ("approval_id", str),
            ("run_id", str),
            ("status", str),
            ("branch_name", str),
            ("commit_sha", str),
            ("pull_request_url", str),
            ("branch_reused", bool),
            ("pull_request_reused", bool),
            ("evidence_ref", str),
        ):
            _required(value, key, expected)
        return cls(raw=dict(value))
