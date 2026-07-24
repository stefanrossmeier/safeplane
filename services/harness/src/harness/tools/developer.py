from __future__ import annotations

import json
import shlex

from harness.tools.runtime import ToolCommandError, ToolExecutionResult, ToolInvocation


PREFIXES = {"developer", "dev"}


def parse_developer_command(message: str) -> ToolInvocation | None:
    try:
        parts = shlex.split(message)
    except ValueError as exc:
        raise ToolCommandError(str(exc)) from exc

    if not parts or parts[0].lower() not in PREFIXES:
        return None

    if len(parts) < 2:
        raise ToolCommandError(
            "developer command requires one of: list, find, grep, read, status, diff, log, show, tracked"
        )

    command = parts[1].lower()

    if command == "list":
        path = parts[2] if len(parts) >= 3 else "."
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_list",
            arguments={"path": path, "max_depth": 2, "max_entries": 200},
        )

    if command == "find":
        if len(parts) < 3:
            raise ToolCommandError("usage: developer find <pattern> [path]")
        pattern = parts[2]
        path = parts[3] if len(parts) >= 4 else "."
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_find",
            arguments={"pattern": pattern, "path": path, "max_results": 100},
        )

    if command == "grep":
        if len(parts) < 3:
            raise ToolCommandError('usage: developer grep "query" [path] [file-glob]')
        query = parts[2]
        path = parts[3] if len(parts) >= 4 else "."
        file_glob = parts[4] if len(parts) >= 5 else "*"
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_grep",
            arguments={
                "query": query,
                "path": path,
                "file_glob": file_glob,
                "case_sensitive": False,
                "max_results": 100,
            },
        )

    if command == "status":
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_git_status",
            arguments={"include_untracked": True},
        )

    if command == "diff":
        paths = parts[2:]
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_git_diff",
            arguments={"paths": paths, "staged": False, "context_lines": 3, "max_bytes": 262144},
        )

    if command == "log":
        max_commits = int(parts[2]) if len(parts) >= 3 else 20
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_git_log",
            arguments={"max_commits": max_commits, "path": None},
        )

    if command == "show":
        ref = parts[2] if len(parts) >= 3 else "HEAD"
        path = parts[3] if len(parts) >= 4 else None
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_git_show",
            arguments={"ref": ref, "path": path, "max_bytes": 262144},
        )

    if command == "tracked":
        path = parts[2] if len(parts) >= 3 else "."
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_git_tracked_files",
            arguments={"path": path, "max_results": 1000},
        )

    if command == "read":
        if len(parts) < 3:
            raise ToolCommandError("usage: developer read <path> [start-line] [max-lines]")
        path = parts[2]
        start_line = int(parts[3]) if len(parts) >= 4 else 1
        max_lines = int(parts[4]) if len(parts) >= 5 else 200
        return ToolInvocation(
            source="deterministic_command",
            adapter_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_read",
            arguments={
                "path": path,
                "start_line": start_line,
                "max_lines": max_lines,
                "max_bytes": 65536,
            },
        )

    raise ToolCommandError(f"unknown developer command: {command}")


def format_developer_result(result: ToolExecutionResult) -> str:
    return json.dumps(result.structured_content, ensure_ascii=False, indent=2, sort_keys=True)
