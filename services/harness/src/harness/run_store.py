from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


RunStatus = Literal[
    "queued",
    "running",
    "waiting_for_approval",
    "waiting_for_tool",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
]

ACTIVE_RUN_STATUSES = {
    "queued",
    "running",
    "waiting_for_approval",
    "waiting_for_tool",
    "cancelling",
}

TERMINAL_RUN_STATUSES = {
    "completed",
    "failed",
    "cancelled",
}

RUN_READ_ATTEMPTS = 3
RUN_READ_RETRY_SECONDS = 0.01


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run_id() -> str:
    return f"run_{uuid.uuid4()}"


def runs_dir(safeplane_home: Path) -> Path:
    path = safeplane_home / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_path(safeplane_home: Path, run_id: str) -> Path:
    return runs_dir(safeplane_home) / f"{run_id}.json"


def save_run(safeplane_home: Path, run: dict[str, Any]) -> None:
    path = run_path(safeplane_home, run["run_id"])
    serialized = json.dumps(run, ensure_ascii=False, indent=2)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_run(safeplane_home: Path, run_id: str) -> dict[str, Any]:
    path = run_path(safeplane_home, run_id)
    last_error: FileNotFoundError | json.JSONDecodeError | None = None

    for attempt in range(1, RUN_READ_ATTEMPTS + 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < RUN_READ_ATTEMPTS:
                time.sleep(RUN_READ_RETRY_SECONDS)

    if isinstance(last_error, FileNotFoundError):
        raise FileNotFoundError(f"Run not found: {run_id}") from last_error
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Run could not be read: {run_id}")


def list_runs(safeplane_home: Path) -> list[dict[str, Any]]:
    runs = []

    for path in runs_dir(safeplane_home).glob("run_*.json"):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    return sorted(
        runs,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )


def create_run(
    *,
    safeplane_home: Path,
    session_id: str,
    session_display_id: str,
    turn: int,
    workflow_id: str,
    entrypoint: str,
    connector: str,
    trace_path: str,
    repository_profile: str | None = None,
    operator_message: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    run = {
        "run_id": create_run_id(),
        "session_id": session_id,
        "session_display_id": session_display_id,
        "turn": turn,
        "workflow_id": workflow_id,
        "entrypoint": entrypoint,
        "connector": connector,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "queued_at": now,
        "started_at": None,
        "completed_at": None,
        "failed_at": None,
        "trace_path": trace_path,
        "repository_profile": repository_profile,
        "operator_message": operator_message,
        "final_message": None,
        "error": None,
    }
    save_run(safeplane_home, run)
    return run


def update_run(
    safeplane_home: Path,
    run_id: str,
    **updates: Any,
) -> dict[str, Any]:
    run = load_run(safeplane_home, run_id)
    run.update(updates)
    run["updated_at"] = utc_now()
    save_run(safeplane_home, run)
    return run


def mark_running(safeplane_home: Path, run_id: str) -> dict[str, Any]:
    return update_run(
        safeplane_home,
        run_id,
        status="running",
        started_at=utc_now(),
    )


def mark_completed(
    safeplane_home: Path,
    run_id: str,
    *,
    final_message: str,
) -> dict[str, Any]:
    return update_run(
        safeplane_home,
        run_id,
        status="completed",
        completed_at=utc_now(),
        final_message=final_message,
        error=None,
    )


def mark_failed(
    safeplane_home: Path,
    run_id: str,
    *,
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    return update_run(
        safeplane_home,
        run_id,
        status="failed",
        failed_at=utc_now(),
        error={
            "type": error_type,
            "message": error_message,
        },
    )


def find_active_run_for_session(
    safeplane_home: Path,
    session_id: str,
) -> dict[str, Any] | None:
    for run in list_runs(safeplane_home):
        if run.get("session_id") != session_id:
            continue

        if run.get("status") in ACTIVE_RUN_STATUSES:
            return run

    return None
