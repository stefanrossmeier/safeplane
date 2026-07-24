from __future__ import annotations

from pathlib import Path

import harness.main as harness_main
from harness.run_store import create_run, load_run


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def submit(self, function, **kwargs):
        self.calls.append((function, kwargs))
        return object()


def test_startup_recovery_resubmits_incomplete_developer_run(
    tmp_path: Path, monkeypatch
) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_recovery",
        session_display_id="recovery",
        turn=2,
        workflow_id="developer",
        entrypoint="develop",
        connector="cli",
        trace_path=str(tmp_path / "traces" / "sess_recovery" / "turn_002"),
        repository_profile="fixture",
        operator_message="Complete the bounded fixture task",
    )
    executor = RecordingExecutor()
    registry_entry = object()

    monkeypatch.setattr(harness_main, "safeplane_home", lambda: tmp_path)
    monkeypatch.setattr(
        harness_main,
        "load_safeplane_config",
        lambda: {"model_gateway": {"endpoint": "http://model-gateway.test/chat"}},
    )
    monkeypatch.setattr(
        harness_main,
        "resolve_entrypoint",
        lambda _config, _entrypoint: {"registry_entry": registry_entry},
    )
    monkeypatch.setattr(
        harness_main,
        "load_session",
        lambda _session_id: {"session_id": "sess_recovery", "turns": []},
    )
    monkeypatch.setattr(harness_main, "session_history_messages", lambda _session: [])
    monkeypatch.setattr(harness_main, "RUN_EXECUTOR", executor)

    harness_main.recover_incomplete_developer_runs()

    assert len(executor.calls) == 1
    function, kwargs = executor.calls[0]
    assert function is harness_main.execute_run
    assert kwargs["run_id"] == run["run_id"]
    assert kwargs["operator_message"] == "Complete the bounded fixture task"
    assert kwargs["repository_profile"] == "fixture"
    assert kwargs["workflow_entry"] is registry_entry
    assert kwargs["model_gateway_url"] == "http://model-gateway.test/chat"

    recovered = load_run(tmp_path, run["run_id"])
    assert recovered["recovery_count"] == 1
    assert recovered["recovery_started_at"]


def test_startup_recovery_fails_developer_run_without_persisted_message(
    tmp_path: Path, monkeypatch
) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_missing_message",
        session_display_id="missing",
        turn=1,
        workflow_id="developer",
        entrypoint="develop",
        connector="cli",
        trace_path=str(tmp_path / "trace"),
        repository_profile="fixture",
    )
    executor = RecordingExecutor()

    monkeypatch.setattr(harness_main, "safeplane_home", lambda: tmp_path)
    monkeypatch.setattr(harness_main, "load_safeplane_config", lambda: {})
    monkeypatch.setattr(
        harness_main,
        "resolve_entrypoint",
        lambda _config, _entrypoint: {"registry_entry": object()},
    )
    monkeypatch.setattr(harness_main, "RUN_EXECUTOR", executor)

    harness_main.recover_incomplete_developer_runs()

    assert executor.calls == []
    failed = load_run(tmp_path, run["run_id"])
    assert failed["status"] == "failed"
    assert failed["error"]["type"] == "RunRecoveryError"
