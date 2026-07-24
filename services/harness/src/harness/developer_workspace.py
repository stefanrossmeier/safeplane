from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDES = [
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".safeplane",
]


class DeveloperWorkspaceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def developer_workspace_config(contract: dict[str, Any]) -> dict[str, Any] | None:
    raw = contract.get("workspace")
    if not isinstance(raw, dict):
        return None
    return raw


def workspace_run_dir(safeplane_home: Path, run_id: str) -> Path:
    return safeplane_home / "workspaces" / run_id


def workspace_repo_dir(safeplane_home: Path, run_id: str) -> Path:
    return workspace_run_dir(safeplane_home, run_id) / "repo"



def make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o555)
            continue
        mode = path.stat().st_mode
        path.chmod(0o555 if mode & 0o111 else 0o444)

    root.chmod(0o555)

def prepare_developer_workspace(
    *,
    contract: dict[str, Any],
    safeplane_home: Path,
    run_id: str,
    entrypoint_name: str = "developer",
    repository_profile: str | None = None,
) -> dict[str, Any] | None:
    config = developer_workspace_config(contract)
    if config is None:
        return None

    if entrypoint_name == "develop" and repository_profile:
        from harness.repository_workspace import prepare_repository_workspace

        return prepare_repository_workspace(
            contract=contract,
            safeplane_home=safeplane_home,
            run_id=run_id,
            repository_profile_id=repository_profile,
        )

    source_env = str(config.get("source_root_env", "SAFEPLANE_DEVELOPER_SOURCE_ROOT"))
    source_raw = os.environ.get(source_env)
    if not source_raw:
        raise DeveloperWorkspaceError(
            f"Developer workflow requires {source_env} to point to a read-only repository source"
        )

    source_root = Path(source_raw).expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise DeveloperWorkspaceError(f"Developer source root is not a directory: {source_root}")

    run_dir = workspace_run_dir(safeplane_home, run_id)
    repo_dir = workspace_repo_dir(safeplane_home, run_id)
    if run_dir.exists():
        raise DeveloperWorkspaceError(f"Developer workspace already exists for run: {run_id}")

    excludes = [str(item) for item in config.get("exclude", DEFAULT_EXCLUDES)]
    run_dir.mkdir(parents=True, exist_ok=False)

    try:
        shutil.copytree(
            source_root,
            repo_dir,
            symlinks=True,
            ignore=shutil.ignore_patterns(*excludes),
        )
        make_tree_read_only(repo_dir)
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise

    manifest = {
        "version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "source_root": str(source_root),
        "repository_root": str(repo_dir),
        "container_logical_root": "/workspace",
        "read_only": bool(config.get("read_only", True)),
        "excluded_names": excludes,
    }

    manifest_path = run_dir / "workspace.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        **manifest,
        "manifest_ref": str(manifest_path.relative_to(safeplane_home)),
    }
