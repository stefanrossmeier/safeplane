from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "mcp-servers/dev-workspace/src"))

from dev_workspace_mcp.main import (  # noqa: E402
    DevWorkspaceError,
    handle_mcp_payload,
    patch_paths,
    wait_for_expected_repository_files,
)
from harness.mcp_broker import McpPermissionError, McpToolBroker  # noqa: E402


RUN_ID = "run_developer_tools-tools"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def prepare_git_workspace(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    base = tmp_path / "workspaces"
    run_root = base / RUN_ID
    repo = run_root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Safeplane fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial fixture")
    commit = git(repo, "rev-parse", "HEAD")

    archdoc = run_root / "repos" / "skills" / "ai-craftkit" / "skills" / "archdoc"
    archdoc.mkdir(parents=True)
    (archdoc / "SKILL.md").write_text("# Archdoc fixture\nOnly documentation may read this.\n", encoding="utf-8")
    (run_root / "workspace.json").write_text(
        json.dumps(
            {
                "version": 2,
                "run_id": RUN_ID,
                "target": {"requested_ref": "main", "resolved_commit": commit},
                "external_sources": {
                    "archdoc": {
                        "checkout_name": "ai-craftkit",
                        "required_path": "skills/archdoc",
                        "resolved_commit": "a" * 40,
                        "allowed_agents": ["documentation"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    return repo, archdoc


def call(tool_name: str, arguments: dict, *, agent_id: str | None = None) -> dict:
    context = {"run_id": RUN_ID}
    if agent_id:
        context["agent_id"] = agent_id
    return handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": tool_name,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments, "context": context},
        }
    )


def content(response: dict) -> dict:
    assert response["result"]["isError"] is False, response
    return response["result"]["structuredContent"]


def test_narrow_git_metadata_tools(tmp_path: Path, monkeypatch) -> None:
    repo, _ = prepare_git_workspace(tmp_path, monkeypatch)
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "new.txt").write_text("untracked\n", encoding="utf-8")

    metadata = content(call("dev_git_metadata", {"include_remote": False}))
    assert metadata["head_commit"] == git(repo, "rev-parse", "HEAD")
    assert metadata["branch"] == "main"
    assert metadata["requested_ref"] == "main"

    status = content(call("dev_git_status", {"include_untracked": True}))
    assert status["clean"] is False
    assert {row["path"] for row in status["entries"]} == {"new.txt", "src/app.py"}

    diff = content(
        call(
            "dev_git_diff",
            {"paths": ["src/app.py"], "staged": False, "context_lines": 1, "max_bytes": 4096},
        )
    )
    assert "-VALUE = 1" in diff["diff"]
    assert "+VALUE = 2" in diff["diff"]

    history = content(call("dev_git_log", {"max_commits": 5, "path": None}))
    assert history["commits"][0]["subject"] == "initial fixture"

    shown = content(call("dev_git_show", {"ref": "HEAD", "path": "README.md", "max_bytes": 8192}))
    assert shown["resolved_commit"] == metadata["head_commit"]
    assert "# Fixture" in shown["content"]

    tracked = content(call("dev_git_tracked_files", {"path": ".", "max_results": 20}))
    assert tracked["files"] == ["README.md", "src/app.py"]

    denied = call("dev_git_show", {"ref": "main", "path": None, "max_bytes": 1024})
    assert denied["result"]["isError"] is True
    assert "allowed ref forms" in denied["result"]["structuredContent"]["error"]

    git_path = call(
        "dev_git_diff",
        {"paths": [".git/config"], "staged": False, "context_lines": 1, "max_bytes": 1024},
    )
    assert git_path["result"]["isError"] is True
    assert "direct .git paths" in git_path["result"]["structuredContent"]["error"]


def test_external_skill_is_documentation_agent_only(tmp_path: Path, monkeypatch) -> None:
    prepare_git_workspace(tmp_path, monkeypatch)

    listed = content(
        call(
            "dev_external_skill_list",
            {"source_id": "archdoc", "path": ".", "max_depth": 2, "max_entries": 20},
            agent_id="documentation",
        )
    )
    assert listed["source_commit"] == "a" * 40
    assert [entry["path"] for entry in listed["entries"]] == ["SKILL.md"]

    read = content(
        call(
            "dev_external_skill_read",
            {
                "source_id": "archdoc",
                "path": "SKILL.md",
                "start_line": 1,
                "max_lines": 20,
                "max_bytes": 4096,
            },
            agent_id="documentation",
        )
    )
    assert "Only documentation" in read["content"]

    denied = call(
        "dev_external_skill_read",
        {
            "source_id": "archdoc",
            "path": "SKILL.md",
            "start_line": 1,
            "max_lines": 20,
            "max_bytes": 4096,
        },
        agent_id="analysis",
    )
    assert denied["result"]["isError"] is True
    assert "not allowed" in denied["result"]["structuredContent"]["error"]


def test_declared_check_execution_pass_fail_timeout_and_env(tmp_path: Path, monkeypatch) -> None:
    repo, _ = prepare_git_workspace(tmp_path, monkeypatch)
    checks = repo / "checks"
    checks.mkdir()
    (checks / "pass.py").write_text(
        "import os\nprint('PASS')\nprint(','.join(sorted(k for k in os.environ if k.startswith(('SAFEPLANE_', 'GITHUB_')))))\n",
        encoding="utf-8",
    )
    (checks / "fail.py").write_text("import sys\nprint('FAIL', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
    (checks / "slow.py").write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    (checks / "write.py").write_text("from pathlib import Path\nPath('generated.txt').write_text('temporary')\n", encoding="utf-8")
    (checks / "noisy.py").write_text("print('x' * 100000)\n", encoding="utf-8")
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "execute")
    monkeypatch.setenv("SAFEPLANE_TEST_SECRET", "must-not-be-inherited")

    passed = content(call("dev_check_run", {"profile_id": "python_check", "arguments": ["checks/pass.py"]}))
    assert passed["status"] == "passed"
    assert passed["exit_code"] == 0
    assert passed["stdout"].splitlines() == ["PASS", ""]
    assert all(not key.startswith(("SAFEPLANE_", "GITHUB_")) for key in passed["environment_keys"])
    assert passed["network_policy"] == "disabled"

    failed = content(call("dev_check_run", {"profile_id": "python_check", "arguments": ["checks/fail.py"]}))
    assert failed["status"] == "failed"
    assert failed["exit_code"] == 7
    assert "FAIL" in failed["stderr"]

    timed_out = content(
        call(
            "dev_check_run",
            {"profile_id": "python_check", "arguments": ["checks/slow.py"], "timeout_seconds": 1},
        )
    )
    assert timed_out["status"] == "timed_out"
    assert timed_out["duration_ms"] < 5000

    wrote = content(call("dev_check_run", {"profile_id": "python_check", "arguments": ["checks/write.py"]}))
    assert wrote["status"] == "passed"
    assert not (repo / "generated.txt").exists()

    noisy = content(call("dev_check_run", {"profile_id": "python_check", "arguments": ["checks/noisy.py"]}))
    assert noisy["truncated"] is True
    assert len(noisy["stdout"].encode()) <= noisy["resource_limits"]["max_output_bytes"]

    unknown = call("dev_check_run", {"profile_id": "bash", "arguments": ["checks/pass.py"]})
    assert unknown["result"]["isError"] is True
    assert "undeclared command profile" in unknown["result"]["structuredContent"]["error"]

    shell = call(
        "dev_check_run",
        {"profile_id": "python_check", "arguments": ["checks/pass.py", "&&", "echo"]},
    )
    assert shell["result"]["isError"] is True
    assert "shell operators" in shell["result"]["structuredContent"]["error"]

    escape = call("dev_check_run", {"profile_id": "python_check", "arguments": ["../outside.py"]})
    assert escape["result"]["isError"] is True
    assert "inside the repository" in escape["result"]["structuredContent"]["error"]


def test_declared_check_can_run_against_temporary_candidate_patch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, _ = prepare_git_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "execute")

    candidate_patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 2\n"
        "diff --git a/tests/check_candidate.py b/tests/check_candidate.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/tests/check_candidate.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+from pathlib import Path\n"
        "+source = Path('src/app.py').read_text(encoding='utf-8')\n"
        "+assert 'VALUE = 2' in source\n"
    )

    checked = content(
        call(
            "dev_check_run",
            {
                "profile_id": "python_check",
                "arguments": ["tests/check_candidate.py"],
                "expected_files": {
                    "src/app.py": hashlib.sha256(
                        (repo / "src/app.py").read_bytes()
                    ).hexdigest(),
                    "tests/check_candidate.py": None,
                },
                "candidate_patch": candidate_patch,
            },
        )
    )

    assert checked["status"] == "passed"
    assert checked["candidate_patch_applied"] is True
    assert (repo / "src/app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (repo / "tests/check_candidate.py").exists()

    rejected = call(
        "dev_check_run",
        {
            "profile_id": "python_check",
            "arguments": ["tests/check_candidate.py"],
            "candidate_patch": "   ",
        },
    )
    assert rejected["result"]["isError"] is True
    assert "candidate_patch must be a non-empty" in rejected["result"]["structuredContent"]["error"]


def test_candidate_patch_paths_use_canonical_root_alias(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical-repo"
    canonical_root.mkdir()
    alias_root = tmp_path / "repo-alias"
    try:
        alias_root.symlink_to(canonical_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    candidate_patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 2\n"
    )

    assert patch_paths(candidate_patch, root=alias_root) == ["src/app.py"]


def test_patch_plan_budget_is_enforced_and_reported(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "workspaces"
    approval_id = "patch_approval_developer_tools"
    repo = base / RUN_ID / "apply" / approval_id / "repo"
    repo.mkdir(parents=True)
    target = repo / "README.md"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "apply")
    patch = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    arguments = {
        "proposal_id": "patch_proposal_developer_tools",
        "patch": patch,
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "authorization_source": "developer_pipeline_plan",
        "plan_budget": [
            {"path": "README.md", "operation": "modified", "max_changed_lines": 2, "max_hunks": 1}
        ],
    }
    response = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "budget",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": arguments,
                "context": {"run_id": RUN_ID, "approval_id": approval_id},
            },
        }
    )
    result = content(response)
    assert result["authorization_source"] == "developer_pipeline_plan"
    assert result["plan_budget_result"]["status"] == "passed"
    assert result["diff_size_bytes"] == len(patch.encode())
    assert result["changed_files"][0]["before_sha256"]
    assert result["changed_files"][0]["after_sha256"]

    target.write_text("old\n", encoding="utf-8")
    arguments["proposal_id"] = "patch_proposal_developer_tools_second"
    arguments["plan_budget"][0]["max_changed_lines"] = 1
    denied = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "budget-denied",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": arguments,
                "context": {"run_id": RUN_ID, "approval_id": approval_id},
            },
        }
    )
    assert denied["result"]["isError"] is True
    assert "changed-line budget exceeded" in denied["result"]["structuredContent"]["error"]


def test_broker_enforces_per_agent_tool_allowlists() -> None:
    broker = McpToolBroker(config_path=REPO_ROOT / "safeplane.yaml")
    assert broker.ensure_workflow_tool_allowed(
        workflow_id="developer",
        server_id="dev-workspace",
        tool_name="dev_external_skill_read",
        agent_id="documentation",
    ) == "allowed"
    with pytest.raises(McpPermissionError, match="Agent is not allowed"):
        broker.ensure_workflow_tool_allowed(
            workflow_id="developer",
            server_id="dev-workspace",
            tool_name="dev_external_skill_read",
            agent_id="analysis",
        )
    with pytest.raises(McpPermissionError, match="require an agent_id"):
        broker.ensure_workflow_tool_allowed(
            workflow_id="developer",
            server_id="dev-workspace",
            tool_name="dev_external_skill_read",
        )
    with pytest.raises(McpPermissionError, match="Agent is not allowed"):
        broker.ensure_workflow_tool_allowed(
            workflow_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_read",
            agent_id="pr",
        )


def test_broker_supports_unix_socket_mcp_transport() -> None:
    import http.server
    import socketserver
    import threading

    # macOS limits AF_UNIX paths to roughly 104 bytes. Pytest's nested
    # tmp_path can exceed that, so use a deliberately short system temp path.
    socket_directory = tempfile.TemporaryDirectory(prefix="sp-mcp-")
    socket_path = Path(socket_directory.name) / "mcp.sock"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            assert self.path == "/mcp"
            body = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = socketserver.UnixStreamServer(str(socket_path), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        broker = McpToolBroker(config_path=REPO_ROOT / "safeplane.yaml")
        result = broker._post_json(
            f"unix://{socket_path}",
            {"jsonrpc": "2.0", "id": "unix-test", "method": "tools/call", "params": {}},
        )
        assert result["id"] == "unix-test"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        socket_directory.cleanup()


def test_patch_apply_creates_parent_directories_for_planned_new_docs(
    tmp_path: Path, monkeypatch
) -> None:
    base = tmp_path / "workspaces"
    approval_id = "patch_approval_external_documentation_docs"
    repo = base / RUN_ID / "apply" / approval_id / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_MODE", "apply")
    patch = (
        "diff --git a/docs/REPO_MAP.md b/docs/REPO_MAP.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/REPO_MAP.md\n"
        "@@ -0,0 +1 @@\n"
        "+# Repository Map\n"
    )
    response = handle_mcp_payload(
        {
            "jsonrpc": "2.0",
            "id": "nested-doc",
            "method": "tools/call",
            "params": {
                "name": "dev_workspace_apply_patch",
                "arguments": {
                    "proposal_id": "patch_proposal_external_documentation_docs",
                    "patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "authorization_source": "developer_pipeline_plan",
                    "plan_budget": [
                        {
                            "path": "docs/REPO_MAP.md",
                            "operation": "created",
                            "max_changed_lines": 1,
                            "max_hunks": 1,
                        }
                    ],
                },
                "context": {"run_id": RUN_ID, "approval_id": approval_id},
            },
        }
    )
    result = content(response)
    assert result["changed_files"][0]["path"] == "docs/REPO_MAP.md"
    assert (repo / "docs" / "REPO_MAP.md").read_text() == "# Repository Map\n"


def test_workspace_ready_requires_complete_target_manifest_and_skill_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    base = tmp_path / "workspaces"
    run_root = base / RUN_ID
    repo = run_root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Safeplane fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "README.md").write_text("# Target\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "target")
    target_commit = git(repo, "rev-parse", "HEAD")

    skill_checkout = run_root / "repos" / "skills" / "ai-craftkit"
    archdoc = skill_checkout / "skills" / "archdoc"
    archdoc.mkdir(parents=True)
    git(skill_checkout, "init", "-q", "-b", "main")
    git(skill_checkout, "config", "user.name", "Safeplane fixture")
    git(skill_checkout, "config", "user.email", "fixture@example.invalid")
    (archdoc / "SKILL.md").write_text("# External archdoc\n", encoding="utf-8")
    git(skill_checkout, "add", ".")
    git(skill_checkout, "commit", "-qm", "skill")
    skill_commit = git(skill_checkout, "rev-parse", "HEAD")

    (run_root / "workspace.json").write_text(
        json.dumps(
            {
                "version": 2,
                "run_id": RUN_ID,
                "target": {"resolved_commit": target_commit},
                "external_sources": {
                    "archdoc": {
                        "checkout_name": "ai-craftkit",
                        "required_path": "skills/archdoc",
                        "resolved_commit": skill_commit,
                        "allowed_agents": ["documentation"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFEPLANE_WORKSPACE_ROOT", str(base))

    ready = content(call("dev_workspace_ready", {"timeout_seconds": 1}))
    assert ready["ready"] is True
    assert ready["target_commit"] == target_commit
    assert ready["external_source_commits"] == {"archdoc": skill_commit}

    (archdoc / "SKILL.md").unlink()
    archdoc.rmdir()
    denied = call("dev_workspace_ready", {"timeout_seconds": 1})
    assert denied["result"]["isError"] is True
    assert "did not become ready" in denied["result"]["structuredContent"]["error"]


def test_workspace_ready_is_harness_owned_not_agent_or_model_visible() -> None:
    broker = McpToolBroker(config_path=REPO_ROOT / "safeplane.yaml")
    assert broker.ensure_workflow_tool_allowed(
        workflow_id="developer",
        server_id="dev-workspace",
        tool_name="dev_workspace_ready",
    ) == "allowed"
    with pytest.raises(McpPermissionError, match="Agent is not allowed"):
        broker.ensure_workflow_tool_allowed(
            workflow_id="developer",
            server_id="dev-workspace",
            tool_name="dev_workspace_ready",
            agent_id="documentation",
        )
    contract = yaml.safe_load((REPO_ROOT / "workflows/developer/workflow.yaml").read_text())
    assert "dev_workspace_ready" not in contract["mcp"]["model_allowed_servers"]["dev-workspace"]["tools"]


def test_check_visibility_barrier_matches_expected_hashes_and_deletions(
    tmp_path: Path, monkeypatch
) -> None:
    repo, _ = prepare_git_workspace(tmp_path, monkeypatch)
    digest = hashlib.sha256((repo / "src/app.py").read_bytes()).hexdigest()

    wait_for_expected_repository_files(
        repo,
        {"src/app.py": digest, "deleted.txt": None},
        timeout_seconds=0.01,
    )

    with pytest.raises(DevWorkspaceError, match="expected file hash"):
        wait_for_expected_repository_files(
            repo,
            {"src/app.py": "0" * 64},
            timeout_seconds=0.01,
        )
