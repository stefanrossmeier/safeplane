from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from fastapi import FastAPI

from harness.dev_workspace_schemas import DEV_WORKSPACE_TOOL_SCHEMAS
from harness.developer_tool_profiles import (
    DeveloperCommandProfileError,
    resolve_command_profile,
)
from harness.mcp_schemas import model_to_dict, validate_tool_input, validate_tool_output
from harness.path_policy import SafePathPolicy, SafePathPolicyError


app = FastAPI(title="Safeplane Dev Workspace MCP")


class DevWorkspaceError(RuntimeError):
    pass


def workspace_base() -> Path:
    return Path(os.environ.get("SAFEPLANE_WORKSPACE_ROOT", "/workspace")).resolve(strict=False)


def validate_run_id(raw: Any) -> str:
    run_id = str(raw or "")
    if not re.fullmatch(r"run_[A-Za-z0-9._-]+", run_id):
        raise DevWorkspaceError("missing or invalid Safeplane run context")
    return run_id


def workspace_visibility_timeout_seconds() -> float:
    raw = os.environ.get("SAFEPLANE_WORKSPACE_VISIBILITY_TIMEOUT_SECONDS", "2")
    try:
        return max(0.0, min(float(raw), 10.0))
    except ValueError:
        return 2.0


def validate_approval_id(raw: Any) -> str:
    approval_id = str(raw or "")
    if not re.fullmatch(r"patch_approval_[A-Za-z0-9._-]+", approval_id):
        raise DevWorkspaceError("missing or invalid patch approval context")
    return approval_id


def workspace_root_for_context(context: dict[str, Any]) -> Path:
    run_id = validate_run_id(context.get("run_id"))
    mode = os.environ.get("SAFEPLANE_WORKSPACE_MODE", "read-only")
    if mode == "apply":
        approval_id = validate_approval_id(context.get("approval_id"))
        root = (workspace_base() / run_id / "apply" / approval_id / "repo").resolve(strict=False)
    else:
        root = (workspace_base() / run_id / "repo").resolve(strict=False)
    deadline = time.monotonic() + workspace_visibility_timeout_seconds()

    while True:
        try:
            if root.is_dir():
                return root
        except OSError:
            pass

        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)

    raise DevWorkspaceError(f"workspace snapshot not found for run: {run_id}")


def workspace_manifest_for_context(context: dict[str, Any]) -> dict[str, Any]:
    run_id = validate_run_id(context.get("run_id"))
    path = workspace_base() / run_id / "workspace.json"
    if not path.is_file():
        raise DevWorkspaceError(f"workspace manifest not found for run: {run_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DevWorkspaceError("workspace manifest must be an object")
    return data


def handle_workspace_ready(
    arguments: dict[str, Any], *, context: dict[str, Any]
) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_ready", arguments)
    data = model_to_dict(request)
    run_id = validate_run_id(context.get("run_id"))
    run_root = workspace_base() / run_id
    repository_root = run_root / "repo"
    manifest_path = run_root / "workspace.json"
    deadline = time.monotonic() + float(data["timeout_seconds"])
    last_reason = "workspace files are not visible"

    while True:
        try:
            if not repository_root.is_dir():
                last_reason = "target repository is not visible"
                raise FileNotFoundError(last_reason)
            if not manifest_path.is_file():
                last_reason = "workspace manifest is not visible"
                raise FileNotFoundError(last_reason)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise DevWorkspaceError("workspace manifest must be an object")
            if str(manifest.get("run_id") or "") != run_id:
                raise DevWorkspaceError("workspace manifest run id does not match")

            target = manifest.get("target") or {}
            if not isinstance(target, dict):
                raise DevWorkspaceError("workspace target metadata is missing")
            expected_target_commit = str(target.get("resolved_commit") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{40}", expected_target_commit):
                raise DevWorkspaceError("workspace target commit is invalid")
            observed_target_commit = run_git(
                repository_root, ["rev-parse", "HEAD"]
            ).stdout.strip().lower()
            if observed_target_commit != expected_target_commit:
                raise DevWorkspaceError(
                    "target checkout does not match workspace manifest"
                )

            source_commits: dict[str, str] = {}
            external_sources = manifest.get("external_sources") or {}
            if not isinstance(external_sources, dict):
                raise DevWorkspaceError(
                    "workspace external_sources must be an object"
                )
            for source_id, raw_source in external_sources.items():
                if not isinstance(raw_source, dict):
                    raise DevWorkspaceError(
                        f"external source metadata is invalid: {source_id}"
                    )
                checkout_name = str(raw_source.get("checkout_name") or "")
                required_path = Path(str(raw_source.get("required_path") or ""))
                expected_commit = str(
                    raw_source.get("resolved_commit") or ""
                ).lower()
                if not re.fullmatch(r"[A-Za-z0-9._-]+", checkout_name):
                    raise DevWorkspaceError(
                        f"external source checkout name is invalid: {source_id}"
                    )
                if required_path.is_absolute() or ".." in required_path.parts:
                    raise DevWorkspaceError(
                        f"external source required path is invalid: {source_id}"
                    )
                if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
                    raise DevWorkspaceError(
                        f"external source commit is invalid: {source_id}"
                    )

                checkout_root = run_root / "repos" / "skills" / checkout_name
                skill_root = checkout_root / required_path
                if not checkout_root.is_dir():
                    last_reason = (
                        f"external source checkout is not visible: {source_id}"
                    )
                    raise FileNotFoundError(last_reason)
                if not skill_root.is_dir():
                    last_reason = (
                        f"external source required path is not visible: {source_id}"
                    )
                    raise FileNotFoundError(last_reason)
                observed_commit = run_git(
                    checkout_root, ["rev-parse", "HEAD"]
                ).stdout.strip().lower()
                if observed_commit != expected_commit:
                    raise DevWorkspaceError(
                        "external source checkout does not match workspace "
                        f"manifest: {source_id}"
                    )
                source_commits[str(source_id)] = observed_commit

            remaining = max(deadline - time.monotonic(), 0.01)
            wait_for_expected_repository_files(
                repository_root,
                data.get("expected_files") or {},
                timeout_seconds=remaining,
            )

            return {
                **command_output(
                    root=repository_root, command=["workspace", "ready"]
                ),
                "ready": True,
                "workspace_version": int(manifest.get("version") or 0),
                "target_commit": observed_target_commit,
                "external_source_commits": source_commits,
            }
        except (OSError, json.JSONDecodeError, DevWorkspaceError) as exc:
            last_reason = str(exc) or last_reason

        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)

    raise DevWorkspaceError(
        f"workspace preparation did not become ready for run {run_id}: "
        f"{last_reason}"
    )


def external_skill_root_for_context(
    context: dict[str, Any], *, source_id: str
) -> tuple[Path, dict[str, Any]]:
    run_id = validate_run_id(context.get("run_id"))
    agent_id = str(context.get("agent_id") or "")
    if not agent_id:
        raise DevWorkspaceError("external skill tools require an agent_id")
    manifest = workspace_manifest_for_context(context)
    source = (manifest.get("external_sources") or {}).get(source_id)
    if not isinstance(source, dict):
        raise DevWorkspaceError(f"external source is not prepared for this run: {source_id}")
    allowed_agents = {str(item) for item in source.get("allowed_agents") or []}
    if agent_id not in allowed_agents:
        raise DevWorkspaceError(
            f"agent {agent_id!r} is not allowed to access external source {source_id!r}"
        )
    checkout_name = str(source.get("checkout_name") or Path(str(source.get("repository_root") or "")).name)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", checkout_name):
        raise DevWorkspaceError("external source checkout name is invalid")
    required_path = Path(str(source.get("required_path") or ""))
    if required_path.is_absolute() or ".." in required_path.parts:
        raise DevWorkspaceError("external source required path is invalid")
    root = (workspace_base() / run_id / "repos" / "skills" / checkout_name / required_path).resolve(
        strict=False
    )
    expected_checkout = (workspace_base() / run_id / "repos" / "skills" / checkout_name).resolve(
        strict=False
    )
    try:
        root.relative_to(expected_checkout)
    except ValueError as exc:
        raise DevWorkspaceError("external source path escapes checkout") from exc
    if not root.is_dir():
        raise DevWorkspaceError(f"external source path is missing: {source_id}")
    return root, source


def logical_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return "." if str(relative) == "." else relative.as_posix()


def command_output(*, root: Path, command: list[str], truncated: bool = False) -> dict[str, Any]:
    return {
        "command": command,
        "cwd": "/workspace",
        "workspace_root": "/workspace",
        "exit_code": 0,
        "truncated": truncated,
        "evidence_ref": None,
    }


def iter_tree(root: Path, start: Path, max_depth: int) -> Iterable[Path]:
    start_depth = len(start.relative_to(root).parts)
    for current, dirnames, filenames in os.walk(start, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts) - start_depth
        dirnames[:] = sorted(dirnames)
        filenames = sorted(filenames)

        if depth >= max_depth:
            dirnames[:] = []

        for name in dirnames:
            yield current_path / name
        for name in filenames:
            yield current_path / name


def ensure_regular_file(path: Path) -> None:
    if not path.exists():
        raise DevWorkspaceError(f"file not found: {path}")
    if not path.is_file():
        raise DevWorkspaceError(f"path is not a regular file: {path}")


def handle_list(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_list", arguments)
    data = model_to_dict(request)
    policy = SafePathPolicy(root)
    start = policy.resolve(data["path"])

    if not start.exists() or not start.is_dir():
        raise DevWorkspaceError(f"directory not found: {data['path']}")

    entries: list[dict[str, Any]] = []
    truncated = False
    for path in iter_tree(root, start, data["max_depth"]):
        if len(entries) >= data["max_entries"]:
            truncated = True
            break

        if path.is_symlink():
            entry_type = "symlink"
            size = None
        elif path.is_dir():
            entry_type = "directory"
            size = None
        else:
            entry_type = "file"
            try:
                size = path.stat().st_size
            except OSError:
                size = None

        entries.append(
            {
                "path": logical_path(root, path),
                "type": entry_type,
                "size_bytes": size,
            }
        )

    return {
        **command_output(
            root=root,
            command=["list", data["path"], f"--max-depth={data['max_depth']}"],
            truncated=truncated,
        ),
        "entries": entries,
    }


def handle_find(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_find", arguments)
    data = model_to_dict(request)
    policy = SafePathPolicy(root)
    start = policy.resolve(data["path"])

    if not start.exists() or not start.is_dir():
        raise DevWorkspaceError(f"directory not found: {data['path']}")

    matches: list[str] = []
    truncated = False
    for path in iter_tree(root, start, max_depth=32):
        relative = logical_path(root, path)
        if fnmatch.fnmatch(path.name, data["pattern"]) or fnmatch.fnmatch(relative, data["pattern"]):
            matches.append(relative)
            if len(matches) >= data["max_results"]:
                truncated = True
                break

    return {
        **command_output(
            root=root,
            command=["find", data["path"], "--pattern", data["pattern"]],
            truncated=truncated,
        ),
        "matches": matches,
    }


def text_files(root: Path, start: Path, file_glob: str) -> Iterable[Path]:
    for path in iter_tree(root, start, max_depth=32):
        if path.is_symlink() or not path.is_file():
            continue
        relative = logical_path(root, path)
        if fnmatch.fnmatch(path.name, file_glob) or fnmatch.fnmatch(relative, file_glob):
            yield path


def handle_grep(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_grep", arguments)
    data = model_to_dict(request)
    policy = SafePathPolicy(root)
    start = policy.resolve(data["path"])

    if not start.exists() or not start.is_dir():
        raise DevWorkspaceError(f"directory not found: {data['path']}")

    query = data["query"] if data["case_sensitive"] else data["query"].casefold()
    matches: list[dict[str, Any]] = []
    truncated = False

    for path in text_files(root, start, data["file_glob"]):
        try:
            if path.stat().st_size > 2_000_000:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            candidate = line if data["case_sensitive"] else line.casefold()
            if query not in candidate:
                continue
            matches.append(
                {
                    "path": logical_path(root, path),
                    "line_number": line_number,
                    "line": line[:2000],
                }
            )
            if len(matches) >= data["max_results"]:
                truncated = True
                break

        if truncated:
            break

    return {
        **command_output(
            root=root,
            command=["grep", data["query"], data["path"], "--glob", data["file_glob"]],
            truncated=truncated,
        ),
        "matches": matches,
    }


def read_text_page(
    path: Path,
    *,
    start_line: int,
    max_lines: int,
    max_bytes: int,
) -> tuple[str, int, int | None]:
    selected: list[str] = []
    selected_bytes = 0
    end_line = start_line - 1
    next_start_line: int | None = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if line_number < start_line:
                continue

            line = raw_line.rstrip("\r\n")
            encoded_size = len(line.encode("utf-8")) + (1 if selected else 0)
            if not selected and encoded_size > max_bytes:
                raise DevWorkspaceError(
                    f"line {line_number} exceeds the per-read byte limit for {path.name}"
                )
            if len(selected) >= max_lines or selected_bytes + encoded_size > max_bytes:
                next_start_line = line_number
                break

            selected.append(line)
            selected_bytes += encoded_size
            end_line = line_number

    return "\n".join(selected), end_line, next_start_line


def handle_read(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_read", arguments)
    data = model_to_dict(request)
    policy = SafePathPolicy(root)
    path = policy.resolve(data["path"])
    ensure_regular_file(path)

    content, end_line, next_start_line = read_text_page(
        path,
        start_line=data["start_line"],
        max_lines=data["max_lines"],
        max_bytes=data["max_bytes"],
    )

    return {
        **command_output(
            root=root,
            command=[
                "read",
                data["path"],
                f"--start-line={data['start_line']}",
                f"--max-lines={data['max_lines']}",
            ],
            truncated=next_start_line is not None,
        ),
        "path": logical_path(root, path),
        "start_line": data["start_line"],
        "end_line": end_line,
        "next_start_line": next_start_line,
        "content": content,
    }


def clean_git_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp/safeplane-git-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def run_git(root: Path, arguments: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["git", "-c", f"safe.directory={root}", *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            env=clean_git_env(),
        )
    except FileNotFoundError as exc:
        raise DevWorkspaceError("git is not installed in the developer MCP runtime") from exc
    except subprocess.TimeoutExpired as exc:
        raise DevWorkspaceError("git metadata command timed out") from exc
    if completed.returncode != 0 and not allow_failure:
        detail = (completed.stderr or completed.stdout or "git command failed").strip()
        raise DevWorkspaceError(f"git metadata command failed: {detail[:2000]}")
    return completed


def target_manifest(root: Path) -> dict[str, Any]:
    path = root.parent / "workspace.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def validate_git_path(root: Path, raw: str) -> str:
    resolved = SafePathPolicy(root).resolve(raw)
    relative = resolved.relative_to(root).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        raise DevWorkspaceError("direct .git paths are not allowed")
    return relative


def handle_git_metadata(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_metadata", arguments)
    data = model_to_dict(request)
    head = run_git(root, ["rev-parse", "HEAD"]).stdout.strip().lower()
    branch_result = run_git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], allow_failure=True)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    remote_url = None
    if data["include_remote"]:
        remote = run_git(root, ["remote", "get-url", "origin"], allow_failure=True)
        remote_url = remote.stdout.strip() if remote.returncode == 0 else None
    manifest = target_manifest(root)
    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    return {
        **command_output(root=root, command=["git", "metadata"]),
        "head_commit": head,
        "detached": branch is None,
        "branch": branch,
        "remote_url": remote_url,
        "requested_ref": target.get("requested_ref"),
        "resolved_base_commit": target.get("resolved_commit"),
    }


def handle_git_status(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_status", arguments)
    data = model_to_dict(request)
    command = ["status", "--porcelain=v1"]
    command.append("--untracked-files=all" if data["include_untracked"] else "--untracked-files=no")
    completed = run_git(root, command)
    entries = []
    for line in completed.stdout.splitlines():
        if len(line) < 3:
            continue
        entries.append({"path": line[3:], "index_status": line[0], "worktree_status": line[1]})
    return {
        **command_output(root=root, command=["git", *command]),
        "clean": not entries,
        "entries": entries,
    }


def handle_git_diff(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_diff", arguments)
    data = model_to_dict(request)
    paths = [validate_git_path(root, item) for item in data["paths"]]
    command = ["diff", "--no-ext-diff", "--no-color", f"--unified={data['context_lines']}"]
    if data["staged"]:
        command.append("--cached")
    if paths:
        command.extend(["--", *paths])
    completed = run_git(root, command)
    raw = completed.stdout.encode("utf-8")
    truncated = len(raw) > data["max_bytes"]
    content = raw[: data["max_bytes"]].decode("utf-8", errors="replace")
    return {
        **command_output(root=root, command=["git", *command], truncated=truncated),
        "diff": content,
        "paths": paths,
    }


def handle_git_log(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_log", arguments)
    data = model_to_dict(request)
    separator = "\x1f"
    record_separator = "\x1e"
    command = [
        "log",
        f"--max-count={data['max_commits']}",
        f"--format=%H{separator}%an{separator}%aI{separator}%s{record_separator}",
        "HEAD",
    ]
    if data["path"] is not None:
        command.extend(["--", validate_git_path(root, data["path"])])
    completed = run_git(root, command)
    commits = []
    for record in completed.stdout.split(record_separator):
        record = record.strip()
        if not record:
            continue
        fields = record.split(separator, 3)
        if len(fields) == 4:
            commits.append(
                {
                    "commit": fields[0],
                    "author_name": fields[1],
                    "authored_at": fields[2],
                    "subject": fields[3],
                }
            )
    return {**command_output(root=root, command=["git", *command]), "commits": commits}


def resolve_allowed_git_ref(root: Path, requested_ref: str) -> str:
    if requested_ref != "HEAD" and not re.fullmatch(r"HEAD~[0-9]{1,4}|[0-9a-fA-F]{40,64}", requested_ref):
        raise DevWorkspaceError("git show ref is not in the allowed ref forms")
    resolved = run_git(root, ["rev-parse", "--verify", f"{requested_ref}^{{commit}}"]).stdout.strip()
    ancestor = run_git(root, ["merge-base", "--is-ancestor", resolved, "HEAD"], allow_failure=True)
    if ancestor.returncode != 0:
        raise DevWorkspaceError("git show ref must resolve to HEAD or one of its ancestors")
    return resolved.lower()


def handle_git_show(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_show", arguments)
    data = model_to_dict(request)
    resolved = resolve_allowed_git_ref(root, data["ref"])
    command = ["show", "--no-ext-diff", "--no-color", "--no-renames", resolved]
    if data["path"] is not None:
        command.extend(["--", validate_git_path(root, data["path"])])
    completed = run_git(root, command)
    raw = completed.stdout.encode("utf-8")
    truncated = len(raw) > data["max_bytes"]
    content = raw[: data["max_bytes"]].decode("utf-8", errors="replace")
    return {
        **command_output(root=root, command=["git", *command], truncated=truncated),
        "requested_ref": data["ref"],
        "resolved_commit": resolved,
        "content": content,
    }


def handle_git_tracked_files(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_git_tracked_files", arguments)
    data = model_to_dict(request)
    path = validate_git_path(root, data["path"])
    command = ["ls-files", "-z", "--", path]
    completed = run_git(root, command)
    files = [item for item in completed.stdout.split("\x00") if item]
    start_after = data.get("start_after")
    if start_after is not None:
        files = [item for item in files if item > start_after]
    page = files[: data["max_results"]]
    truncated = len(files) > len(page)
    next_start_after = page[-1] if truncated and page else None
    return {
        **command_output(root=root, command=["git", *command], truncated=truncated),
        "files": page,
        "next_start_after": next_start_after,
    }


def handle_external_skill_list(
    arguments: dict[str, Any], *, root: Path, source: dict[str, Any]
) -> dict[str, Any]:
    request = validate_tool_input("dev_external_skill_list", arguments)
    data = model_to_dict(request)
    start = SafePathPolicy(root).resolve(data["path"])
    if not start.is_dir():
        raise DevWorkspaceError(f"external skill directory not found: {data['path']}")
    entries = []
    truncated = False
    for path in iter_tree(root, start, data["max_depth"]):
        if len(entries) >= data["max_entries"]:
            truncated = True
            break
        entries.append(
            {
                "path": logical_path(root, path),
                "type": "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file",
                "size_bytes": path.stat().st_size if path.is_file() and not path.is_symlink() else None,
            }
        )
    return {
        **command_output(root=root, command=["external-skill-list", data["source_id"], data["path"]], truncated=truncated),
        "source_id": data["source_id"],
        "source_commit": str(source.get("resolved_commit") or ""),
        "entries": entries,
    }


def handle_external_skill_read(
    arguments: dict[str, Any], *, root: Path, source: dict[str, Any]
) -> dict[str, Any]:
    request = validate_tool_input("dev_external_skill_read", arguments)
    data = model_to_dict(request)
    path = SafePathPolicy(root).resolve(data["path"])
    ensure_regular_file(path)
    if path.is_symlink():
        raise DevWorkspaceError("external skill reads do not follow symlinks")
    content, end_line, next_start_line = read_text_page(
        path,
        start_line=data["start_line"],
        max_lines=data["max_lines"],
        max_bytes=data["max_bytes"],
    )
    return {
        **command_output(
            root=root,
            command=["external-skill-read", data["source_id"], data["path"]],
            truncated=next_start_line is not None,
        ),
        "source_id": data["source_id"],
        "source_commit": str(source.get("resolved_commit") or ""),
        "path": logical_path(root, path),
        "start_line": data["start_line"],
        "end_line": end_line,
        "next_start_line": next_start_line,
        "content": content,
    }


def make_copy_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        except OSError:
            pass
    root.chmod(0o755)


def wait_for_expected_repository_files(
    root: Path,
    expected_files: dict[str, str | None],
    *,
    timeout_seconds: float = 15.0,
) -> None:
    if not expected_files:
        return
    policy = SafePathPolicy(root)
    deadline = time.monotonic() + timeout_seconds
    last_mismatch = "expected repository state is not visible"
    while True:
        all_match = True
        for logical, expected_hash in expected_files.items():
            path = policy.resolve(logical)
            if expected_hash is None:
                if path.exists():
                    all_match = False
                    last_mismatch = f"expected deleted path is still visible: {logical}"
                    break
                continue
            if not path.is_file() or path.is_symlink():
                all_match = False
                last_mismatch = f"expected file is not visible: {logical}"
                break
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_hash:
                all_match = False
                last_mismatch = f"expected file hash is not visible: {logical}"
                break
        if all_match:
            return
        if time.monotonic() >= deadline:
            raise DevWorkspaceError(last_mismatch)
        time.sleep(0.05)


def handle_check_run(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    if os.environ.get("SAFEPLANE_WORKSPACE_MODE") != "execute":
        raise DevWorkspaceError("declared check execution is disabled on this MCP service")
    request = validate_tool_input("dev_check_run", arguments)
    data = model_to_dict(request)
    wait_for_expected_repository_files(root, data.get("expected_files") or {})

    candidate_patch = data.get("candidate_patch")
    if candidate_patch is not None:
        validate_patch_paths(candidate_patch, root=root)

    temp_root = Path(tempfile.mkdtemp(prefix="safeplane-check-", dir="/tmp"))
    copied_repo = temp_root / "repo"
    started = time.monotonic()
    timed_out = False
    return_code: int | None = None
    stdout_path = temp_root / "stdout.txt"
    stderr_path = temp_root / "stderr.txt"
    try:
        shutil.copytree(
            root,
            copied_repo,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"),
        )
        make_copy_writable(copied_repo)

        if candidate_patch is not None:
            relative_paths = patch_paths(candidate_patch, root=copied_repo)
            stats = patch_diff_stats(candidate_patch)
            for relative, values in stats.items():
                if values.get("operation") == "created":
                    (copied_repo / relative).parent.mkdir(parents=True, exist_ok=True)
            checked = run_patch_command(root=copied_repo, patch=candidate_patch, dry_run=True)
            if checked.returncode != 0:
                detail = (checked.stderr or checked.stdout or "candidate patch validation failed").strip()
                raise DevWorkspaceError(
                    "candidate patch validation failed before check execution: " + detail[:4000]
                )
            applied = run_patch_command(root=copied_repo, patch=candidate_patch, dry_run=False)
            if applied.returncode != 0:
                detail = (applied.stderr or applied.stdout or "candidate patch application failed").strip()
                raise DevWorkspaceError(
                    "candidate patch application failed before check execution: " + detail[:4000]
                )
            if not relative_paths:
                raise DevWorkspaceError("candidate patch did not contain repository paths")

        try:
            argv, limits = resolve_command_profile(
                data["profile_id"],
                data["arguments"],
                repository_root=copied_repo,
                timeout_seconds=data["timeout_seconds"],
            )
        except DeveloperCommandProfileError as exc:
            raise DevWorkspaceError(str(exc)) from exc

        home = temp_root / "home"
        home.mkdir(mode=0o700)
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        def apply_limits() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))
            resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"], limits["memory_bytes"]))
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (limits["max_output_bytes"], limits["max_output_bytes"]),
            )

        # The production check runner is a Linux container, where these child
        # limits are supported. Direct host-side unit tests also invoke this
        # function; macOS rejects one or more of these limits in preexec_fn and
        # turns the useful error into an opaque SubprocessError. Container CPU,
        # memory, PID, and filesystem limits remain active in production.
        preexec_fn = apply_limits if sys.platform.startswith("linux") else None

        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                argv,
                cwd=copied_repo,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
                preexec_fn=preexec_fn,
            )
            try:
                return_code = process.wait(timeout=limits["timeout_seconds"])
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                return_code = process.returncode

        stdout_raw = stdout_path.read_bytes()[: limits["max_output_bytes"]]
        stderr_raw = stderr_path.read_bytes()[: limits["max_output_bytes"]]
        status = "timed_out" if timed_out else "passed" if return_code == 0 else "failed"
        return {
            **command_output(
                root=root,
                command=argv,
                truncated=(
                    stdout_path.stat().st_size >= limits["max_output_bytes"]
                    or stderr_path.stat().st_size >= limits["max_output_bytes"]
                ),
            ),
            "exit_code": return_code if return_code is not None else -1,
            "profile_id": data["profile_id"],
            "status": status,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout": stdout_raw.decode("utf-8", errors="replace"),
            "stderr": stderr_raw.decode("utf-8", errors="replace"),
            "stdout_ref": None,
            "stderr_ref": None,
            "environment_keys": sorted(environment),
            "network_policy": "disabled",
            "resource_limits": limits,
            "candidate_patch_applied": candidate_patch is not None,
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_patch_paths(patch: str, *, root: Path) -> None:
    policy = SafePathPolicy(root)
    for line in patch.splitlines():
        candidates: list[str] = []
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                candidates.extend(parts[2:4])
        elif line.startswith("--- ") or line.startswith("+++ "):
            candidates.append(line[4:].split("\t", 1)[0])

        for candidate in candidates:
            if candidate == "/dev/null":
                continue
            if candidate.startswith("a/") or candidate.startswith("b/"):
                candidate = candidate[2:]
            policy.resolve(candidate)


def handle_patch_proposal(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    request = validate_tool_input("dev_workspace_propose_patch", arguments)
    data = model_to_dict(request)
    validate_patch_paths(data["patch"], root=root)

    return {
        **command_output(root=root, command=["propose-patch"]),
        "summary": data["summary"],
        "patch": data["patch"],
        "proposal_id": None,
        "artifact_ref": None,
        "approval_command": None,
    }


def patch_paths(patch: str, *, root: Path) -> list[str]:
    policy = SafePathPolicy(root)
    results: list[str] = []
    saw_git_header = False

    for line in patch.splitlines():
        candidates: list[str] = []
        if line.startswith("diff --git "):
            saw_git_header = True
            try:
                parts = shlex.split(line)
            except ValueError as exc:
                raise DevWorkspaceError(f"invalid diff header: {line}") from exc
            if len(parts) < 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise DevWorkspaceError("patch must use git-style a/ and b/ paths")
            candidates.extend(parts[2:4])
        elif line.startswith("--- ") or line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0].strip()
            try:
                parsed = shlex.split(raw)
                candidate = parsed[0] if parsed else raw
            except ValueError:
                candidate = raw
            if candidate != "/dev/null" and not (
                candidate.startswith("a/") or candidate.startswith("b/")
            ):
                raise DevWorkspaceError("patch must use git-style a/ and b/ paths")
            candidates.append(candidate)

        for candidate in candidates:
            if candidate == "/dev/null":
                continue
            candidate = candidate[2:]
            resolved = policy.resolve(candidate)
            relative = resolved.relative_to(policy.root).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                raise DevWorkspaceError("patch may not modify .git metadata")
            if relative not in results:
                results.append(relative)

    if not saw_git_header:
        raise DevWorkspaceError("patch application requires a git-style unified diff")
    if not results:
        raise DevWorkspaceError("patch does not contain any file paths")
    return results


def file_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise DevWorkspaceError(f"patch may not modify symlinks: {path}")
    if not path.is_file():
        raise DevWorkspaceError(f"patch path is not a regular file: {path}")
    content = path.read_bytes()
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def run_patch_command(*, root: Path, patch: str, dry_run: bool) -> subprocess.CompletedProcess[str]:
    command = ["patch", "--batch", "--forward", "--no-backup-if-mismatch", "-p1"]
    if dry_run:
        command.insert(1, "--dry-run")
    try:
        return subprocess.run(
            command,
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise DevWorkspaceError("patch command timed out") from exc


def patch_diff_stats(patch: str) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = shlex.split(line)
            if len(parts) >= 4:
                current = parts[3][2:] if parts[3].startswith("b/") else None
                if current:
                    stats[current] = {"changed_lines": 0, "hunks": 0, "operation": "modified"}
            continue
        if current is None:
            continue
        if line.startswith("new file mode ") or line == "--- /dev/null":
            stats[current]["operation"] = "created"
        elif line.startswith("deleted file mode ") or line == "+++ /dev/null":
            stats[current]["operation"] = "deleted"
        elif line.startswith("@@"):
            stats[current]["hunks"] += 1
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            stats[current]["changed_lines"] += 1
    return stats


def validate_patch_budget(
    patch: str, budgets: list[dict[str, Any]]
) -> dict[str, Any]:
    if not budgets:
        return {"status": "not_provided", "checked_paths": [], "violations": []}
    stats = patch_diff_stats(patch)
    budget_by_path = {item["path"]: item for item in budgets}
    violations: list[str] = []
    for path, values in stats.items():
        budget = budget_by_path.get(path)
        if budget is None:
            violations.append(f"unplanned path: {path}")
            continue
        if values["operation"] != budget["operation"]:
            violations.append(
                f"operation mismatch for {path}: {values['operation']} != {budget['operation']}"
            )
        if values["changed_lines"] > budget["max_changed_lines"]:
            violations.append(
                f"changed-line budget exceeded for {path}: "
                f"{values['changed_lines']} > {budget['max_changed_lines']}"
            )
        if values["hunks"] > budget["max_hunks"]:
            violations.append(
                f"hunk budget exceeded for {path}: {values['hunks']} > {budget['max_hunks']}"
            )
    if violations:
        raise DevWorkspaceError("patch exceeds implementation plan: " + "; ".join(violations))
    return {"status": "passed", "checked_paths": sorted(stats), "violations": []}


def handle_patch_apply(arguments: dict[str, Any], *, root: Path) -> dict[str, Any]:
    if os.environ.get("SAFEPLANE_WORKSPACE_MODE") != "apply":
        raise DevWorkspaceError("patch application is disabled on the read-only MCP service")

    request = validate_tool_input("dev_workspace_apply_patch", arguments)
    data = model_to_dict(request)
    actual_sha256 = hashlib.sha256(data["patch"].encode("utf-8")).hexdigest()
    if actual_sha256 != data["patch_sha256"]:
        raise DevWorkspaceError("patch checksum does not match approval request")

    relative_paths = patch_paths(data["patch"], root=root)
    budget_result = validate_patch_budget(data["patch"], data["plan_budget"])
    before = {path: file_state(root / path) for path in relative_paths}
    stats = patch_diff_stats(data["patch"])
    for relative, values in stats.items():
        if values.get("operation") == "created":
            (root / relative).parent.mkdir(parents=True, exist_ok=True)

    checked = run_patch_command(root=root, patch=data["patch"], dry_run=True)
    if checked.returncode != 0:
        detail = (checked.stderr or checked.stdout or "patch validation failed").strip()
        raise DevWorkspaceError(f"patch validation failed: {detail[:4000]}")

    applied = run_patch_command(root=root, patch=data["patch"], dry_run=False)
    if applied.returncode != 0:
        detail = (applied.stderr or applied.stdout or "patch application failed").strip()
        raise DevWorkspaceError(f"patch application failed: {detail[:4000]}")

    changed_files: list[dict[str, Any]] = []
    for relative in relative_paths:
        prior = before[relative]
        after = file_state(root / relative)
        if prior is None and after is not None:
            operation = "created"
        elif prior is not None and after is None:
            operation = "deleted"
        elif prior != after:
            operation = "modified"
        else:
            continue
        changed_files.append(
            {
                "path": relative,
                "operation": operation,
                "before_sha256": prior["sha256"] if prior else None,
                "after_sha256": after["sha256"] if after else None,
                "before_size_bytes": prior["size_bytes"] if prior else None,
                "after_size_bytes": after["size_bytes"] if after else None,
            }
        )

    if not changed_files:
        raise DevWorkspaceError("patch command completed without changing files")

    return {
        **command_output(root=root, command=["patch", "--batch", "--forward", "-p1"]),
        "proposal_id": data["proposal_id"],
        "patch_sha256": data["patch_sha256"],
        "authorization_source": data["authorization_source"],
        "changed_files": changed_files,
        "diff_size_bytes": len(data["patch"].encode("utf-8")),
        "plan_budget_result": budget_result,
        "tool_evidence_path": None,
    }


HANDLERS = {
    "dev_workspace_list": handle_list,
    "dev_workspace_find": handle_find,
    "dev_workspace_grep": handle_grep,
    "dev_workspace_read": handle_read,
    "dev_git_metadata": handle_git_metadata,
    "dev_git_status": handle_git_status,
    "dev_git_diff": handle_git_diff,
    "dev_git_log": handle_git_log,
    "dev_git_show": handle_git_show,
    "dev_git_tracked_files": handle_git_tracked_files,
    "dev_check_run": handle_check_run,
    "dev_workspace_propose_patch": handle_patch_proposal,
    "dev_workspace_apply_patch": handle_patch_apply,
}

EXTERNAL_HANDLERS = {
    "dev_external_skill_list": handle_external_skill_list,
    "dev_external_skill_read": handle_external_skill_read,
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
def mcp_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_mcp_payload(payload)


def handle_mcp_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("method") != "tools/call":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Unsupported method"},
        }

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32602, "message": "params must be an object"},
        }

    tool_name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    context = params.get("context") or {}

    try:
        if tool_name not in DEV_WORKSPACE_TOOL_SCHEMAS or (
            tool_name != "dev_workspace_ready"
            and tool_name not in HANDLERS
            and tool_name not in EXTERNAL_HANDLERS
        ):
            raise DevWorkspaceError(f"Unsupported tool: {tool_name}")
        if not isinstance(arguments, dict) or not isinstance(context, dict):
            raise DevWorkspaceError("arguments and context must be objects")

        if tool_name == "dev_workspace_ready":
            structured_content = handle_workspace_ready(arguments, context=context)
        elif tool_name in EXTERNAL_HANDLERS:
            source_id = str(arguments.get("source_id") or "archdoc")
            root, source = external_skill_root_for_context(context, source_id=source_id)
            structured_content = EXTERNAL_HANDLERS[tool_name](arguments, root=root, source=source)
        else:
            root = workspace_root_for_context(context)
            structured_content = HANDLERS[tool_name](arguments, root=root)
        validated_output = validate_tool_output(tool_name, structured_content)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": model_to_dict(validated_output),
                "isError": False,
            },
        }
    except (DevWorkspaceError, SafePathPolicyError, ValueError, OSError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": {"error": str(exc)},
                "isError": True,
            },
        }
