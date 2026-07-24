from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "mcp-servers/dev-workspace/src"))

from dev_workspace_mcp.main import handle_mcp_payload, workspace_root_for_context  # noqa: E402


RUN_ID = "run_test-workspace"


def make_workspace(tmp_path: Path, monkeypatch) -> Path:
    base = tmp_path / "workspace"
    repo = base / RUN_ID / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("# Fixture\nSafeplane fixture repository\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    return repo


def call(tool_name: str, arguments: dict) -> dict:
    return handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "test",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                "context": {"run_id": RUN_ID},
            },
        }
    )


def test_read_only_inspection_tools(tmp_path: Path, monkeypatch) -> None:
    make_workspace(tmp_path, monkeypatch)

    listed = call(
        "dev_workspace_list",
        {"path": ".", "max_depth": 2, "max_entries": 20},
    )
    assert listed["result"]["isError"] is False
    paths = [item["path"] for item in listed["result"]["structuredContent"]["entries"]]
    assert "README.md" in paths
    assert "src/app.py" in paths
    assert listed["result"]["structuredContent"]["cwd"] == "/workspace"

    found = call(
        "dev_workspace_find",
        {"pattern": "*.py", "path": ".", "max_results": 20},
    )
    assert found["result"]["structuredContent"]["matches"] == ["src/app.py"]

    grepped = call(
        "dev_workspace_grep",
        {
            "query": "hello",
            "path": ".",
            "file_glob": "*.py",
            "case_sensitive": False,
            "max_results": 20,
        },
    )
    matches = grepped["result"]["structuredContent"]["matches"]
    assert matches[0]["path"] == "src/app.py"
    assert matches[0]["line_number"] == 2

    read = call(
        "dev_workspace_read",
        {"path": "src/app.py", "start_line": 1, "max_lines": 20, "max_bytes": 4096},
    )
    assert read["result"]["structuredContent"]["content"].startswith("def greet")


def test_path_escape_is_rejected(tmp_path: Path, monkeypatch) -> None:
    make_workspace(tmp_path, monkeypatch)

    result = call(
        "dev_workspace_read",
        {"path": "../../outside.txt", "start_line": 1, "max_lines": 10, "max_bytes": 1024},
    )

    assert result["result"]["isError"] is True
    assert "path escapes allowed root" in result["result"]["structuredContent"]["error"]


def test_patch_proposal_rejects_unsafe_paths(tmp_path: Path, monkeypatch) -> None:
    make_workspace(tmp_path, monkeypatch)

    result = call(
        "dev_workspace_propose_patch",
        {
            "summary": "unsafe",
            "patch": (
                "diff --git a/../../outside.txt b/../../outside.txt\n"
                "--- a/../../outside.txt\n"
                "+++ b/../../outside.txt\n"
                "@@ -0,0 +1 @@\n"
                "+bad\n"
            ),
        },
    )

    assert result["result"]["isError"] is True
    assert "path escapes allowed root" in result["result"]["structuredContent"]["error"]


def test_run_context_rejects_path_characters(tmp_path: Path, monkeypatch) -> None:
    make_workspace(tmp_path, monkeypatch)
    result = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "unsafe-run",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_list",
                "arguments": {"path": ".", "max_depth": 1, "max_entries": 10},
                "context": {"run_id": "run_../../outside"},
            },
        }
    )

    assert result["result"]["isError"] is True
    assert "invalid Safeplane run context" in result["result"]["structuredContent"]["error"]


def test_workspace_root_waits_for_bind_mount_visibility(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "workspace"
    base.mkdir()
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_VISIBILITY_TIMEOUT_SECONDS", "0.5")

    def create_snapshot() -> None:
        time.sleep(0.05)
        (base / RUN_ID / "repo").mkdir(parents=True)

    worker = threading.Thread(target=create_snapshot)
    worker.start()
    try:
        resolved = workspace_root_for_context({"run_id": RUN_ID})
    finally:
        worker.join()

    assert resolved == (base / RUN_ID / "repo").resolve()


def test_approved_patch_apply_changes_only_the_approval_workspace(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    base = tmp_path / "workspace"
    approval_id = "patch_approval_test"
    repo = base / RUN_ID / "apply" / approval_id / "repo"
    (repo / "src").mkdir(parents=True)
    target = repo / "src" / "app.py"
    target.write_text(
        "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "apply")

    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        "-    return f'Hello {name}'\n"
        "+    return f'Hello from Safeplane {name}'\n"
    )
    response = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "apply",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": {
                    "proposal_id": "patch_proposal_test",
                    "patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                },
                "context": {
                    "run_id": RUN_ID,
                    "approval_id": approval_id,
                },
            },
        }
    )

    assert response["result"]["isError"] is False, response
    content = response["result"]["structuredContent"]
    assert content["proposal_id"] == "patch_proposal_test"
    assert content["changed_files"] == [
        {
            "path": "src/app.py",
            "operation": "modified",
            "before_sha256": content["changed_files"][0]["before_sha256"],
            "after_sha256": content["changed_files"][0]["after_sha256"],
            "before_size_bytes": 56,
            "after_size_bytes": 71,
        }
    ]
    assert "Hello from Safeplane" in target.read_text(encoding="utf-8")


def test_patch_apply_is_disabled_on_read_only_service(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    make_workspace(tmp_path, monkeypatch)
    monkeypatch.delenv("SAFEPLANE_WORKSPACE_MODE", raising=False)
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        "-    return f'Hello {name}'\n"
        "+    return f'Hi {name}'\n"
    )
    response = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "disabled",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": {
                    "proposal_id": "patch_proposal_test",
                    "patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                },
                "context": {"run_id": RUN_ID},
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "disabled on the read-only MCP service" in response["result"]["structuredContent"]["error"]


def test_patch_apply_rejects_non_git_paths_that_do_not_match_strip_level(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    base = tmp_path / "workspace"
    approval_id = "patch_approval_strip"
    repo = base / RUN_ID / "apply" / approval_id / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "apply")

    patch = "--- src/app.py\n+++ src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    response = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "strip-mismatch",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": {
                    "proposal_id": "patch_proposal_strip",
                    "patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                },
                "context": {"run_id": RUN_ID, "approval_id": approval_id},
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "git-style" in response["result"]["structuredContent"]["error"]
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "old\n"


def test_read_pages_files_longer_than_single_call_limit(tmp_path: Path, monkeypatch) -> None:
    repo = make_workspace(tmp_path, monkeypatch)
    lines = [f"line-{index:04d}" for index in range(1, 2506)]
    (repo / "src" / "large.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    first = call(
        "dev_workspace_read",
        {"path": "src/large.py", "start_line": 1, "max_lines": 2000, "max_bytes": 1048576},
    )["result"]["structuredContent"]
    assert first["end_line"] == 2000
    assert first["next_start_line"] == 2001
    assert first["truncated"] is True

    second = call(
        "dev_workspace_read",
        {
            "path": "src/large.py",
            "start_line": first["next_start_line"],
            "max_lines": 2000,
            "max_bytes": 1048576,
        },
    )["result"]["structuredContent"]
    assert second["end_line"] == 2505
    assert second["next_start_line"] is None
    assert second["truncated"] is False
    assert second["content"].splitlines()[-1] == "line-2505"


def test_tracked_file_listing_uses_continuation_cursor(tmp_path: Path, monkeypatch) -> None:
    repo = make_workspace(tmp_path, monkeypatch)
    for index in range(5):
        (repo / "src" / f"module_{index}.py").write_text(
            f"VALUE = {index}\n",
            encoding="utf-8",
        )
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)

    first = call(
        "dev_git_tracked_files",
        {"path": "src", "max_results": 2},
    )["result"]["structuredContent"]
    assert first["files"] == ["src/app.py", "src/module_0.py"]
    assert first["next_start_after"] == "src/module_0.py"
    assert first["truncated"] is True

    second = call(
        "dev_git_tracked_files",
        {
            "path": "src",
            "start_after": first["next_start_after"],
            "max_results": 2,
        },
    )["result"]["structuredContent"]
    assert second["files"] == ["src/module_1.py", "src/module_2.py"]
    assert second["next_start_after"] == "src/module_2.py"
    assert second["truncated"] is True

    third = call(
        "dev_git_tracked_files",
        {
            "path": "src",
            "start_after": second["next_start_after"],
            "max_results": 10,
        },
    )["result"]["structuredContent"]
    assert third["files"] == ["src/module_3.py", "src/module_4.py"]
    assert third["next_start_after"] is None
    assert third["truncated"] is False
