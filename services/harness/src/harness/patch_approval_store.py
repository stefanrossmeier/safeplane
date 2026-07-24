from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.developer_workspace import make_tree_read_only


RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9._-]+")
PROPOSAL_ID_PATTERN = re.compile(r"patch_proposal_[A-Za-z0-9._-]+")
APPROVAL_ID_PATTERN = re.compile(r"patch_approval_[A-Za-z0-9._-]+")


class PatchApprovalError(RuntimeError):
    pass


class PatchApprovalConflictError(PatchApprovalError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_identifier(value: str, pattern: re.Pattern[str], field_name: str) -> str:
    if not pattern.fullmatch(value):
        raise PatchApprovalError(f"invalid {field_name}: {value}")
    return value


def proposal_metadata_path(safeplane_home: Path, run_id: str, proposal_id: str) -> Path:
    validate_identifier(run_id, RUN_ID_PATTERN, "run_id")
    validate_identifier(proposal_id, PROPOSAL_ID_PATTERN, "proposal_id")
    return safeplane_home / "workspaces" / run_id / "artifacts" / f"{proposal_id}.json"


def load_patch_proposal(
    safeplane_home: Path,
    *,
    run_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    metadata_path = proposal_metadata_path(safeplane_home, run_id, proposal_id)
    if not metadata_path.is_file():
        raise PatchApprovalError(
            f"patch proposal not found for run {run_id}: {proposal_id}"
        )

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PatchApprovalError(f"patch proposal metadata is invalid: {proposal_id}") from exc

    if metadata.get("run_id") != run_id or metadata.get("proposal_id") != proposal_id:
        raise PatchApprovalError("patch proposal ownership metadata does not match request")

    patch_ref = str(metadata.get("patch_ref") or "")
    expected_prefix = f"workspaces/{run_id}/artifacts/"
    if not patch_ref.startswith(expected_prefix):
        raise PatchApprovalError("patch proposal artifact reference escapes the run workspace")

    patch_path = safeplane_home / patch_ref
    try:
        resolved_patch = patch_path.resolve(strict=True)
        artifacts_root = (safeplane_home / "workspaces" / run_id / "artifacts").resolve(strict=True)
    except FileNotFoundError as exc:
        raise PatchApprovalError(f"patch proposal artifact is missing: {proposal_id}") from exc

    if resolved_patch.parent != artifacts_root:
        raise PatchApprovalError("patch proposal artifact path is outside the run artifacts directory")

    patch = resolved_patch.read_text(encoding="utf-8")
    actual_sha256 = sha256_text(patch)
    recorded_sha256 = str(metadata.get("patch_sha256") or actual_sha256)
    if recorded_sha256 != actual_sha256:
        raise PatchApprovalError("patch proposal checksum does not match the stored artifact")

    return {
        **metadata,
        "patch": patch,
        "patch_sha256": actual_sha256,
        "patch_path": str(resolved_patch),
    }


def approvals_dir(safeplane_home: Path, run_id: str) -> Path:
    validate_identifier(run_id, RUN_ID_PATTERN, "run_id")
    path = safeplane_home / "workspaces" / run_id / "approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def approval_path(safeplane_home: Path, run_id: str, approval_id: str) -> Path:
    validate_identifier(approval_id, APPROVAL_ID_PATTERN, "approval_id")
    return approvals_dir(safeplane_home, run_id) / f"{approval_id}.json"


def load_patch_approval(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> dict[str, Any]:
    path = approval_path(safeplane_home, run_id, approval_id)
    if not path.is_file():
        raise PatchApprovalError(f"patch approval not found: {approval_id}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PatchApprovalError(f"patch approval record is invalid: {approval_id}") from exc


def save_patch_approval(safeplane_home: Path, record: dict[str, Any]) -> None:
    path = approval_path(safeplane_home, str(record["run_id"]), str(record["approval_id"]))
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def find_existing_approval(
    safeplane_home: Path,
    *,
    run_id: str,
    proposal_id: str,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for path in approvals_dir(safeplane_home, run_id).glob("patch_approval_*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if record.get("proposal_id") == proposal_id:
            matches.append(record)

    blocking = [record for record in matches if record.get("status") != "failed"]
    if not blocking:
        return None
    return sorted(
        blocking,
        key=lambda item: str(item.get("updated_at") or item.get("approved_at") or ""),
        reverse=True,
    )[0]


def create_patch_approval(
    safeplane_home: Path,
    *,
    run: dict[str, Any],
    proposal: dict[str, Any],
    connector: str,
) -> tuple[dict[str, Any], str]:
    run_id = str(run["run_id"])
    proposal_id = str(proposal["proposal_id"])
    existing = find_existing_approval(
        safeplane_home,
        run_id=run_id,
        proposal_id=proposal_id,
    )
    if existing is not None:
        raise PatchApprovalConflictError(
            f"patch proposal already has approval {existing.get('approval_id')} "
            f"with status {existing.get('status')}"
        )

    approval_id = f"patch_approval_{secrets.token_hex(16)}"
    approval_token = secrets.token_urlsafe(32)
    now = utc_now()
    record = {
        "version": 1,
        "approval_id": approval_id,
        "proposal_id": proposal_id,
        "run_id": run_id,
        "workflow_id": run.get("workflow_id"),
        "session_id": run.get("session_id"),
        "turn": run.get("turn"),
        "status": "approved",
        "approved_at": now,
        "updated_at": now,
        "applied_at": None,
        "failed_at": None,
        "connector": connector,
        "patch_ref": proposal.get("patch_ref"),
        "patch_sha256": proposal.get("patch_sha256"),
        "approval_token_sha256": sha256_text(approval_token),
        "workspace_ref": f"workspaces/{run_id}/repo",
        "changed_files": [],
        "evidence_ref": None,
        "error": None,
    }
    save_patch_approval(safeplane_home, record)
    return record, approval_token


def update_patch_approval(
    safeplane_home: Path,
    record: dict[str, Any],
    **updates: Any,
) -> dict[str, Any]:
    updated = {**record, **updates, "updated_at": utc_now()}
    save_patch_approval(safeplane_home, updated)
    return updated


def validate_patch_approval_token(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
    approval_token: str,
    proposal_id: str,
    patch_sha256: str,
    workflow_id: str,
) -> dict[str, Any]:
    record = load_patch_approval(
        safeplane_home,
        run_id=run_id,
        approval_id=approval_id,
    )
    if record.get("status") != "approved":
        raise PatchApprovalError(
            f"patch approval is not usable in status {record.get('status')}: {approval_id}"
        )
    if record.get("proposal_id") != proposal_id:
        raise PatchApprovalError("patch approval proposal_id does not match")
    if record.get("patch_sha256") != patch_sha256:
        raise PatchApprovalError("patch approval checksum does not match")
    if record.get("workflow_id") != workflow_id:
        raise PatchApprovalError("patch approval workflow does not match")
    if record.get("approval_token_sha256") != sha256_text(approval_token):
        raise PatchApprovalError("patch approval token is invalid")
    return record


def make_tree_writable(root: Path, *, uid: int = 10001, gid: int = 10001) -> None:
    for path in [root, *sorted(root.rglob("*"), key=lambda item: len(item.parts))]:
        if path.is_symlink():
            continue
        try:
            if os.geteuid() == 0:
                os.chown(path, uid, gid)
        except OSError as exc:
            raise PatchApprovalError(f"could not assign writable workspace ownership: {path}") from exc

        if path.is_dir():
            path.chmod(0o755)
        else:
            mode = path.stat().st_mode
            path.chmod(0o755 if mode & 0o111 else 0o644)


def make_tree_removable(root: Path) -> None:
    """Temporarily restore owner write modes for atomic publish and cleanup."""
    for path in [root, *sorted(root.rglob("*"), key=lambda item: len(item.parts))]:
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        else:
            mode = path.stat().st_mode
            path.chmod(0o755 if mode & 0o111 else 0o644)


def apply_workspace_dir(safeplane_home: Path, run_id: str, approval_id: str) -> Path:
    validate_identifier(run_id, RUN_ID_PATTERN, "run_id")
    validate_identifier(approval_id, APPROVAL_ID_PATTERN, "approval_id")
    return safeplane_home / "workspaces" / run_id / "apply" / approval_id


def prepare_patch_apply_workspace(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> Path:
    source_repo = safeplane_home / "workspaces" / run_id / "repo"
    if not source_repo.is_dir():
        raise PatchApprovalError(f"developer workspace snapshot not found for run: {run_id}")

    apply_root = apply_workspace_dir(safeplane_home, run_id, approval_id)
    if apply_root.exists():
        raise PatchApprovalConflictError(
            f"patch apply workspace already exists: {approval_id}"
        )

    staged_repo = apply_root / "repo"
    apply_root.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(source_repo, staged_repo, symlinks=True)
        make_tree_writable(staged_repo)
    except Exception:
        shutil.rmtree(apply_root, ignore_errors=True)
        raise
    return staged_repo


def publish_patch_apply_workspace(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> Path:
    run_root = safeplane_home / "workspaces" / run_id
    current_repo = run_root / "repo"
    staged_repo = apply_workspace_dir(safeplane_home, run_id, approval_id) / "repo"
    backup_repo = run_root / f"repo.before-{approval_id}"

    if not current_repo.is_dir() or not staged_repo.is_dir():
        raise PatchApprovalError("patch apply workspace is incomplete")
    if backup_repo.exists():
        raise PatchApprovalConflictError(f"workspace backup already exists: {backup_repo.name}")

    # macOS may reject renaming or removing a directory whose owner-write bit
    # was cleared, even when its parent is writable. Temporarily restore modes
    # only for the deterministic publication operation.
    current_repo.chmod(0o755)
    current_repo.rename(backup_repo)
    try:
        staged_repo.rename(current_repo)
        make_tree_read_only(current_repo)
        make_tree_removable(backup_repo)
        shutil.rmtree(backup_repo)
        shutil.rmtree(apply_workspace_dir(safeplane_home, run_id, approval_id), ignore_errors=True)
    except Exception:
        if current_repo.exists():
            make_tree_removable(current_repo)
            shutil.rmtree(current_repo, ignore_errors=True)
        if backup_repo.exists():
            backup_repo.chmod(0o755)
            backup_repo.rename(current_repo)
            make_tree_read_only(current_repo)
        raise

    return current_repo


def cleanup_patch_apply_workspace(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> None:
    shutil.rmtree(apply_workspace_dir(safeplane_home, run_id, approval_id), ignore_errors=True)
