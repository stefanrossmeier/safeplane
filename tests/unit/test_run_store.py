from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

import harness.run_store as run_store_module
from harness.run_store import (
    find_active_run_for_session,
    create_run,
    list_runs,
    load_run,
    mark_completed,
    save_run,
)


def test_run_store_creates_and_lists_runs(tmp_path: Path) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_abc",
        session_display_id="abc12345",
        turn=1,
        workflow_id="assistant",
        entrypoint="assistant",
        connector="cli",
        trace_path="/tmp/trace",
    )

    assert run["run_id"].startswith("run_")
    assert run["status"] == "queued"

    runs = list_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0]["run_id"] == run["run_id"]


def test_run_store_publishes_operator_readable_records(tmp_path: Path) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_permissions",
        session_display_id="perm0001",
        turn=1,
        workflow_id="developer",
        entrypoint="develop",
        connector="cli",
        trace_path="/tmp/trace",
    )

    path = run_store_module.run_path(tmp_path, run["run_id"])

    assert path.stat().st_mode & 0o777 == 0o644


def test_run_store_finds_active_run_for_session(tmp_path: Path) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_abc",
        session_display_id="abc12345",
        turn=1,
        workflow_id="assistant",
        entrypoint="assistant",
        connector="cli",
        trace_path="/tmp/trace",
    )

    active = find_active_run_for_session(tmp_path, "sess_abc")

    assert active is not None
    assert active["run_id"] == run["run_id"]

    mark_completed(
        tmp_path,
        run["run_id"],
        final_message="done",
    )

    assert find_active_run_for_session(tmp_path, "sess_abc") is None


def test_run_store_keeps_previous_record_when_atomic_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_atomic",
        session_display_id="atomic01",
        turn=1,
        workflow_id="developer",
        entrypoint="develop",
        connector="cli",
        trace_path="/tmp/trace",
    )
    original = load_run(tmp_path, run["run_id"])
    updated = dict(original, status="running", large_payload="x" * 200_000)

    def fail_replace(source: object, target: object) -> None:
        del source, target
        raise OSError("simulated interrupted atomic publication")

    monkeypatch.setattr(run_store_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="interrupted atomic publication"):
        save_run(tmp_path, updated)

    assert load_run(tmp_path, run["run_id"]) == original
    assert list((tmp_path / "runs").glob(f".{run['run_id']}.json.*.tmp")) == []


def test_load_run_retries_transient_invalid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run(
        safeplane_home=tmp_path,
        session_id="sess_retry",
        session_display_id="retry001",
        turn=1,
        workflow_id="developer",
        entrypoint="develop",
        connector="cli",
        trace_path="/tmp/trace",
    )
    path = run_store_module.run_path(tmp_path, run["run_id"])
    original_read_text = Path.read_text
    calls = 0

    def flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal calls
        if self == path:
            calls += 1
            if calls == 1:
                return ""
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(run_store_module.time, "sleep", lambda _seconds: None)

    assert load_run(tmp_path, run["run_id"]) == run
    assert calls == 2
