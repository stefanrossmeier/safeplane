from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from harness.agent_runtime import redact_external_skill_content_for_artifact
from harness.developer_pipeline import StageModelCallResult, run_developer_pipeline
from harness.documentation_agent import (
    DocumentationAgentError,
    DocumentationAgentResponse,
    build_documentation_patch_from_replacements,
    collect_documentation_evidence,
    expand_documentation_placeholders,
    normalize_documentation_patch,
    normalize_documentation_response_metadata,
    validate_documentation_patch,
    validate_documentation_patch_applicability,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_contract() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )


def test_documentation_response_requires_patch_only_for_changes() -> None:
    with pytest.raises(ValidationError, match="requires a Git-style unified_diff"):
        DocumentationAgentResponse.model_validate(
            {
                "stage": "baseline",
                "summary": "changed",
                "documentation_files": ["docs/REPO_MAP.md"],
                "changed": True,
                "unified_diff": None,
                "evidence_notes": [],
                "uncertainties": [],
            }
        )

    with pytest.raises(ValidationError, match="must not include unified_diff"):
        DocumentationAgentResponse.model_validate(
            {
                "stage": "final",
                "summary": "unchanged",
                "documentation_files": ["docs/REPO_MAP.md"],
                "changed": False,
                "unified_diff": "diff --git a/x b/x",
                "evidence_notes": [],
                "uncertainties": [],
            }
        )


def test_documentation_response_metadata_is_relocated_without_changing_replacement_text() -> None:
    raw = {
        "stage": "baseline",
        "summary": "updated",
        "documentation_files": ["docs/REPO_MAP.md"],
        "changed": True,
        "replacements": [
            {
                "path": "docs/REPO_MAP.md",
                "old_text": 'restart: "no"\n',
                "new_text": 'restart: "no"\nupdated\n',
                "evidence_notes": ["verified current file"],
                "uncertainties": ["runtime not executed"],
            }
        ],
    }

    normalized = normalize_documentation_response_metadata(raw)

    assert normalized["evidence_notes"] == ["verified current file"]
    assert normalized["uncertainties"] == ["runtime not executed"]
    assert normalized["replacements"] == [
        {
            "path": "docs/REPO_MAP.md",
            "old_text": 'restart: "no"\n',
            "new_text": 'restart: "no"\nupdated\n',
        }
    ]
    assert raw["replacements"][0]["evidence_notes"] == ["verified current file"]


def test_documentation_response_metadata_normalization_rejects_malformed_values() -> None:
    with pytest.raises(DocumentationAgentError, match="must be a list of strings"):
        normalize_documentation_response_metadata(
            {
                "replacements": [
                    {
                        "path": "docs/REPO_MAP.md",
                        "old_text": "old",
                        "new_text": "new",
                        "evidence_notes": "not-a-list",
                    }
                ]
            }
        )


def test_documentation_patch_rejects_scope_placeholders_and_secrets() -> None:
    commit = "a" * 40
    valid = (
        "diff --git a/docs/REPO_MAP.md b/docs/REPO_MAP.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/REPO_MAP.md\n"
        "@@ -0,0 +1,7 @@\n"
        "+# Repository Map\n"
        "+> Generated with `ai-craftkit` skill: `archdoc`\n"
        f"+> Source: `ai-craftkit` at commit `{commit}`\n"
        "+> Prompt: `developer.documentation.system@v1`\n"
        "+Doc Status: DRAFT\n"
        "+Source Basis: README.md\n"
        "+Evidence is explicitly bounded.\n"
    )
    files = validate_documentation_patch(
        valid,
        allowed_paths=["docs/REPO_MAP.md"],
        source_commit=commit,
    )
    assert files[0].operation == "created"

    with pytest.raises(DocumentationAgentError, match="disallowed paths"):
        validate_documentation_patch(
            valid.replace("docs/REPO_MAP.md", "src/main.py"),
            allowed_paths=["docs/REPO_MAP.md"],
            source_commit=commit,
        )

    with pytest.raises(DocumentationAgentError, match="placeholder"):
        validate_documentation_patch(
            valid.replace("Evidence is explicitly bounded.", "[Describe the repository]"),
            allowed_paths=["docs/REPO_MAP.md"],
            source_commit=commit,
        )

    with pytest.raises(DocumentationAgentError, match="secret"):
        validate_documentation_patch(
            valid.replace("Evidence is explicitly bounded.", "github_pat_abcdefghijklmnopqrstuvwxyz012345"),
            allowed_paths=["docs/REPO_MAP.md"],
            source_commit=commit,
        )


def test_documentation_patch_normalization_repairs_counts_and_drops_noop_hunks(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "ARCHITECTURE.md").write_text(
        "# Architecture\nLast Reviewed Scope: delta update\n\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    malformed_counts = (
        "diff --git a/docs/ARCHITECTURE.md b/docs/ARCHITECTURE.md\n"
        "--- a/docs/ARCHITECTURE.md\n"
        "+++ b/docs/ARCHITECTURE.md\n"
        "@@ -1,3 +1,10 @@\n"
        "+> Generated with `ai-craftkit` skill: `archdoc`\n"
        "+> Source: `ai-craftkit` at commit `abc`\n"
        "+> Skill bundle SHA-256: `def`\n"
        "+> Prompt: `developer.documentation.system@v1`\n"
        "+> Repository profile: `fixture`\n"
        "+\n"
        "+Doc Status: DRAFT\n"
        "+Source Basis: repository evidence\n"
        "+\n"
        " # Architecture\n"
        " Last Reviewed Scope: delta update\n"
        " \n"
        "@@ -1,3 +10,3 @@\n"
        "-# Architecture\n"
        "Last Reviewed Scope: delta update\n"
        "+# Architecture\n"
        "Last Reviewed Scope: delta update\n"
        " \n"
    )

    normalized = normalize_documentation_patch(malformed_counts)

    assert "@@ -1,3 +1,12 @@" in normalized
    assert "@@ -1,3 +10,3 @@" not in normalized
    assert "Last Reviewed Scope: delta update\n+# Architecture" not in normalized
    validate_documentation_patch_applicability(normalized, repository_root=repo)


def test_documentation_replacements_generate_harness_owned_git_patch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    target = repo / "docs" / "REPO_MAP.md"
    target.write_text(
        "# Repo Map\nLast Reviewed Scope: delta update\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    patch = build_documentation_patch_from_replacements(
        [
            {
                "path": "docs/REPO_MAP.md",
                "old_text": "# Repo Map\n",
                "new_text": (
                    "# Repo Map\n"
                    "> Generated with `ai-craftkit` skill: `archdoc`\n"
                    "> Source: `ai-craftkit` at commit `abc`\n"
                    "> Skill bundle SHA-256: `def`\n"
                    "> Prompt: `developer.documentation.system@v1`\n"
                    "> Repository profile: `fixture`\n\n"
                    "Doc Status: DRAFT\n"
                    "Source Basis: repository evidence\n\n"
                ),
            }
        ],
        repository_root=repo,
        allowed_paths=["docs/REPO_MAP.md"],
    )

    assert patch.startswith(
        "diff --git a/docs/REPO_MAP.md b/docs/REPO_MAP.md\n"
    )
    assert "@@" in patch
    validate_documentation_patch_applicability(patch, repository_root=repo)
    completed = subprocess.run(
        ["git", "apply", "-"],
        cwd=repo,
        input=patch,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "Doc Status: DRAFT" in target.read_text(encoding="utf-8")


def test_documentation_replacements_reject_ambiguous_or_disallowed_old_text(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "REPO_MAP.md").write_text(
        "same\nsame\n", encoding="utf-8"
    )

    with pytest.raises(DocumentationAgentError, match="matched 2 times"):
        build_documentation_patch_from_replacements(
            [
                {
                    "path": "docs/REPO_MAP.md",
                    "old_text": "same",
                    "new_text": "changed",
                }
            ],
            repository_root=repo,
            allowed_paths=["docs/REPO_MAP.md"],
        )

    with pytest.raises(DocumentationAgentError, match="disallowed path"):
        build_documentation_patch_from_replacements(
            [
                {
                    "path": "docs/OTHER.md",
                    "old_text": "",
                    "new_text": "# Other\n",
                }
            ],
            repository_root=repo,
            allowed_paths=["docs/REPO_MAP.md"],
        )

def test_documentation_patch_applicability_rejects_malformed_or_stale_diff(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "ARCHITECTURE.md").write_text(
        "# Old architecture\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    valid = (
        "diff --git a/docs/ARCHITECTURE.md b/docs/ARCHITECTURE.md\n"
        "--- a/docs/ARCHITECTURE.md\n"
        "+++ b/docs/ARCHITECTURE.md\n"
        "@@ -1 +1 @@\n"
        "-# Old architecture\n"
        "+# New architecture\n"
    )
    validate_documentation_patch_applicability(valid, repository_root=repo)

    malformed = valid.replace("@@ -1 +1 @@", "@@ -1 +1,2 @@")
    with pytest.raises(DocumentationAgentError, match="malformed or does not apply"):
        validate_documentation_patch_applicability(malformed, repository_root=repo)

    stale = valid.replace("# Old architecture", "# Missing context")
    with pytest.raises(DocumentationAgentError, match="does not apply"):
        validate_documentation_patch_applicability(stale, repository_root=repo)


def test_documentation_evidence_reads_live_skill_and_skips_sensitive_files() -> None:
    commit = "b" * 40
    calls: list[tuple[str, str]] = []

    def call(server: str, tool: str, arguments: dict) -> dict:
        calls.append((tool, str(arguments.get("path", ""))))
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [
                    {"path": "SKILL.md", "type": "file"},
                    {"path": "templates/REPO_MAP.template.md", "type": "file"},
                ],
                "evidence_ref": "evidence/skill-list",
            }
        if tool == "dev_external_skill_read":
            path = arguments["path"]
            return {
                "source_commit": commit,
                "path": path,
                "start_line": arguments["start_line"],
                "end_line": arguments["start_line"],
                "next_start_line": None,
                "content": "# Archdoc\n" if path == "SKILL.md" else "# Template\n",
                "truncated": False,
                "evidence_ref": f"evidence/{path}",
            }
        if tool == "dev_git_tracked_files":
            return {
                "files": [".env", "README.md", "credentials.json", "src/main.py"],
                "evidence_ref": "evidence/tracked",
            }
        if tool == "dev_workspace_read":
            path = arguments["path"]
            if path.startswith("docs/"):
                raise RuntimeError("file not found")
            return {
                "path": path,
                "start_line": arguments["start_line"],
                "end_line": arguments["start_line"],
                "next_start_line": None,
                "content": f"content:{path}",
                "truncated": False,
                "evidence_ref": f"evidence/{path}",
            }
        raise AssertionError((server, tool, arguments))

    evidence = collect_documentation_evidence(
        stage="baseline",
        expected_source_commit=commit,
        config=load_contract()["developer_pipeline"]["documentation_runtime"],
        call_tool=call,
    )

    assert evidence.source_commit == commit
    assert evidence.skill_files[0].path == "SKILL.md"
    assert {item.path for item in evidence.repository_files} == {"README.md", "src/main.py"}
    read_paths = {path for tool, path in calls if tool == "dev_workspace_read"}
    assert ".env" not in read_paths
    assert "credentials.json" not in read_paths


def test_external_skill_content_is_redacted_from_message_artifact() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "input_artifacts": {
                        "documentation_evidence": {
                            "skill_files": [{"path": "SKILL.md", "content": "live skill"}]
                        }
                    }
                }
            ),
        },
    ]
    redacted = redact_external_skill_content_for_artifact("baseline_documentation", messages)
    assert "live skill" not in redacted[1]["content"]
    assert "not persisted" in redacted[1]["content"]
    assert messages[1]["content"] != redacted[1]["content"]


def test_live_documentation_pipeline_applies_baseline_and_supplies_docs_to_later_agents(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    home = tmp_path / "home"
    run_id = "run_external_documentation_live"
    run_root = home / "workspaces" / run_id
    repo = run_root / "repo"
    skill_root = run_root / "repos" / "skills" / "ai-craftkit" / "skills" / "archdoc"
    repo.mkdir(parents=True)
    skill_root.mkdir(parents=True)
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n', encoding="utf-8"
    )
    (repo / "checks").mkdir()
    (repo / "checks" / "check_greeting.py").write_text(
        "print('controlled check passed')\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    base_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    skill_commit = "c" * 40
    (skill_root / "SKILL.md").write_text("# Archdoc live fixture\n", encoding="utf-8")
    (skill_root / "templates").mkdir()
    (skill_root / "templates" / "REPO_MAP.template.md").write_text("# Template\n", encoding="utf-8")
    (run_root / "workspace.json").write_text(
        json.dumps(
            {
                "workspace_kind": "git_multi_repository",
                "repository_root": str(repo),
                "target": {
                    "profile_id": "fixture",
                    "repository_url": "https://github.com/fixture/repository.git",
                    "requested_ref": "main",
                    "resolved_commit": base_commit,
                    "credential_profile": "github",
                    "remote_write_allowed": True,
                    "branch_prefix": "safeplane/",
                    "pull_request_repository": "fixture/repository",
                    "git_author_name": "Safeplane fixture",
                    "git_author_email": "safeplane-fixture@example.invalid",
                },
                "external_sources": {
                    "archdoc": {
                        "resolved_commit": skill_commit,
                        "checkout_name": "ai-craftkit",
                        "required_path": "skills/archdoc",
                        "allowed_agents": ["documentation"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (home / "runs").mkdir(parents=True)
    (home / "runs" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": "developer",
                "session_id": "sess_fixture",
                "turn": 1,
                "status": "running",
            }
        ),
        encoding="utf-8",
    )

    model_calls: list[dict] = []
    baseline_attempts = 0

    def model_caller(stage_id, response_key, model_profile, messages):
        nonlocal baseline_attempts
        model_calls.append({"stage_id": stage_id, "messages": messages})
        configured = contract["model_profiles"][model_profile]["fake_responses"][response_key]
        if isinstance(configured, list):
            assistant_turns = sum(
                1 for message in messages if message.get("role") == "assistant"
            )
            configured = configured[min(assistant_turns, len(configured) - 1)]
        path = REPO_ROOT / configured
        content = path.read_text(encoding="utf-8")
        if stage_id == "baseline_documentation":
            baseline_attempts += 1
            if baseline_attempts == 1:
                content = content.replace("+Doc Status: DRAFT\\n", "")
                content = content.replace(
                    "+Source Basis: repository files supplied through Safeplane MCP tools\\n",
                    "",
                )
            elif baseline_attempts == 2:
                content = content.replace(
                    "+# Repository Map\\n",
                    "+# Repository Map\\n stale-unprefixed-line\\n",
                    1,
                )
            elif baseline_attempts == 3:
                payload = json.loads(content)
                unified_diff = str(payload.pop("unified_diff"))
                replacements = []
                for section in unified_diff.split("diff --git ")[1:]:
                    lines = section.splitlines()
                    parts = lines[0].split()
                    path = parts[1][2:]
                    new_text = "\n".join(
                        line[1:]
                        for line in lines
                        if line.startswith("+") and not line.startswith("+++")
                    ) + "\n"
                    replacements.append(
                        {"path": path, "old_text": "", "new_text": new_text}
                    )
                payload["replacements"] = replacements
                payload["documentation_files"] = [
                    replacement["path"] for replacement in replacements
                ]
                content = json.dumps(payload)
        return StageModelCallResult(
            content=content,
            model={
                "mode": "fake",
                "actual_model": f"fake/{model_profile}",
                "actual_provider": "safeplane-fake",
            },
        )

    proposal_counter = 0

    def tool_caller(
        stage_id: str,
        agent_id: str | None,
        server_id: str,
        tool_name: str,
        arguments: dict,
        approval_id: str | None,
        approval_token: str | None,
    ) -> dict:
        nonlocal proposal_counter
        if tool_name in {"dev_workspace_apply_patch", "dev_check_run", "dev_workspace_ready"}:
            assert agent_id is None
        elif stage_id == "implementation":
            assert agent_id == "implementation"
        else:
            assert agent_id == "documentation"
        evidence_ref = f"workspaces/{run_id}/evidence/tool-calls.jsonl"
        if tool_name == "dev_external_skill_list":
            return {
                "source_commit": skill_commit,
                "entries": [
                    {"path": "SKILL.md", "type": "file"},
                    {"path": "templates", "type": "directory"},
                    {"path": "templates/REPO_MAP.template.md", "type": "file"},
                ],
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_external_skill_read":
            path = skill_root / arguments["path"]
            content = path.read_text(encoding="utf-8")[: arguments["max_bytes"]]
            return {
                "source_commit": skill_commit,
                "path": arguments["path"],
                "start_line": arguments["start_line"],
                "end_line": arguments["start_line"] + max(len(content.splitlines()) - 1, 0),
                "next_start_line": None,
                "content": content,
                "truncated": False,
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_git_tracked_files":
            files = subprocess.check_output(["git", "-c", "safe.directory=*", "ls-files"], cwd=repo, text=True).splitlines()
            return {"files": files, "evidence_ref": evidence_ref}
        if tool_name == "dev_workspace_read":
            path = repo / arguments["path"]
            if not path.is_file():
                raise RuntimeError("file not found")
            content = path.read_text(encoding="utf-8")[: arguments["max_bytes"]]
            return {
                "path": arguments["path"],
                "start_line": arguments["start_line"],
                "end_line": arguments["start_line"] + max(len(content.splitlines()) - 1, 0),
                "next_start_line": None,
                "content": content,
                "truncated": False,
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_workspace_propose_patch":
            proposal_counter += 1
            proposal_id = f"patch_proposal_fixture_{proposal_counter}"
            artifacts = run_root / "artifacts"
            artifacts.mkdir(exist_ok=True)
            patch_path = artifacts / f"{proposal_id}.patch"
            patch_path.write_text(arguments["patch"], encoding="utf-8")
            return {
                "proposal_id": proposal_id,
                "artifact_ref": str(patch_path.relative_to(home)),
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_workspace_apply_patch":
            assert approval_id and approval_token
            apply_repo = run_root / "apply" / approval_id / "repo"
            for budget in arguments["plan_budget"]:
                if budget["operation"] == "created":
                    (apply_repo / budget["path"]).parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                ["patch", "--batch", "--forward", "--no-backup-if-mismatch", "-p1"],
                cwd=apply_repo,
                input=arguments["patch"],
                text=True,
                capture_output=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr or completed.stdout
            changed = []
            for budget in arguments["plan_budget"]:
                path = apply_repo / budget["path"]
                changed.append(
                    {
                        "path": budget["path"],
                        "operation": budget["operation"],
                        "before_sha256": None,
                        "after_sha256": "d" * 64,
                        "before_size_bytes": None,
                        "after_size_bytes": path.stat().st_size,
                    }
                )
            return {
                "proposal_id": arguments["proposal_id"],
                "patch_sha256": arguments["patch_sha256"],
                "authorization_source": "developer_pipeline_plan",
                "changed_files": changed,
                "diff_size_bytes": len(arguments["patch"].encode()),
                "plan_budget_result": {
                    "status": "passed",
                    "checked_paths": sorted(item["path"] for item in arguments["plan_budget"]),
                    "violations": [],
                },
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_workspace_ready":
            return {
                "ready": True,
                "workspace_version": 2,
                "target_commit": base_commit,
                "external_source_commits": {"archdoc": skill_commit},
                "evidence_ref": evidence_ref,
            }
        if tool_name == "dev_check_run":
            return {
                "profile_id": arguments["profile_id"],
                "status": "passed",
                "exit_code": 0,
                "duration_ms": 1,
                "stdout_ref": f"workspaces/{run_id}/evidence/check.stdout.txt",
                "stderr_ref": f"workspaces/{run_id}/evidence/check.stderr.txt",
                "evidence_ref": evidence_ref,
                "network_policy": "disabled",
            }
        raise AssertionError((stage_id, server_id, tool_name, arguments))

    result = run_developer_pipeline(
        contract=contract,
        config_path=REPO_ROOT / "safeplane.yaml",
        safeplane_home=home,
        run_id=run_id,
        operator_message="Document the fixture",
        workspace_manifest={
            "workspace_kind": "git_multi_repository",
            "repository_root": str(repo),
            "target": {
                "profile_id": "fixture",
                "repository_url": "https://github.com/fixture/repository.git",
                "requested_ref": "main",
                "resolved_commit": base_commit,
                "credential_profile": "github",
                "remote_write_allowed": True,
                "branch_prefix": "safeplane/",
                "pull_request_repository": "fixture/repository",
                "git_author_name": "Safeplane fixture",
                "git_author_email": "safeplane-fixture@example.invalid",
            },
            "external_sources": {"archdoc": {"resolved_commit": skill_commit}},
        },
        call_stage_model=model_caller,
        trace=lambda *args: None,
        call_stage_tool=tool_caller,
    )

    assert result.current_state == "waiting_for_remote_approval"
    run_record = json.loads((home / "runs" / f"{run_id}.json").read_text())
    summary = run_record["developer_pipeline"]
    assert summary["current_state"] == "waiting_for_remote_approval"
    assert summary["check_summary"]["status"] == "passed"
    assert summary["review_verdict"] == "LGTM"
    assert summary["review_plan_alignment"] == "ALIGNED"
    assert summary["remote_approval_possible"] is True
    binding = summary["remote_approval_binding"]
    assert binding["repository_name"] == "fixture/repository"
    assert binding["credential_profile"] == "github"
    request = json.loads(
        (run_root / "pipeline" / "remote-approval-request.json").read_text(
            encoding="utf-8"
        )
    )
    assert request["base_commit"] == base_commit
    assert request["checks_sha256"] == binding["checks_sha256"]
    assert request["review_sha256"] == binding["review_sha256"]
    for name in ("REPO_MAP.md", "ARCHITECTURE.md", "API_SURFACE.md", "OPERATIONS.md"):
        content = (repo / "docs" / name).read_text(encoding="utf-8")
        assert skill_commit in content
        assert "[Describe" not in content
    baseline = json.loads((run_root / "pipeline" / "baseline_documentation.json").read_text())
    final = json.loads((run_root / "pipeline" / "final_documentation.json").read_text())
    assert baseline["skill_source_commit"] == skill_commit
    assert final["skill_source_commit"] == skill_commit
    assert baseline["changed"] is True
    assert final["changed"] is False
    baseline_calls = [
        call for call in model_calls if call["stage_id"] == "baseline_documentation"
    ]
    assert len(baseline_calls) == 3
    assert len(baseline_calls[0]["messages"]) == 2
    assert len(baseline_calls[1]["messages"]) == 3
    assert len(baseline_calls[2]["messages"]) == 3
    status_repair_message = baseline_calls[1]["messages"][2]["content"]
    assert "missing required literal status fields" in status_repair_message
    assert "Doc Status: DRAFT" in status_repair_message
    assert (
        "Source Basis: repository files supplied through Safeplane MCP tools and "
        "the external archdoc skill"
    ) in status_repair_message
    assert "${ARCHDOC_COMMIT}" in status_repair_message
    assert "${ARCHDOC_SKILL_SHA256}" in status_repair_message
    assert "complete corrected JSON object" in status_repair_message
    patch_repair_message = baseline_calls[2]["messages"][2]["content"]
    assert "malformed or does not apply cleanly" in patch_repair_message
    assert "exact text replacements" in patch_repair_message
    assert "must match exactly once" in patch_repair_message
    assert "do not write any `@@` hunk headers" in patch_repair_message
    assert "Do not add `notes`" in patch_repair_message
    analysis_message = next(
        call["messages"][1]["content"]
        for call in model_calls
        if call["stage_id"] == "analysis"
    )
    assert "docs/ARCHITECTURE.md" in analysis_message
    assert skill_commit in analysis_message


def test_documentation_evidence_pages_long_files_and_reads_more_than_forty_tracked_files() -> None:
    commit = "e" * 40
    repository_content = {
        "src/large.py": "\n".join(f"line-{index:04d}" for index in range(1, 2506)),
        "scripts/release": "#!/usr/bin/env python3\nprint('release')\n",
        **{f"src/module_{index:02d}.py": f"VALUE = {index}\n" for index in range(45)},
    }
    all_tracked = sorted([*repository_content, "assets/logo.png"])
    read_calls: list[dict] = []
    tracked_calls: list[dict] = []

    def page(path: str, content: str, arguments: dict, *, source_commit: str | None = None) -> dict:
        lines = content.splitlines()
        start = int(arguments["start_line"])
        max_lines = int(arguments["max_lines"])
        assert max_lines <= 2000
        selected = lines[start - 1 : start - 1 + max_lines]
        next_line = start + len(selected) if start - 1 + len(selected) < len(lines) else None
        result = {
            "path": path,
            "start_line": start,
            "end_line": start + max(len(selected) - 1, 0),
            "next_start_line": next_line,
            "content": "\n".join(selected),
            "truncated": next_line is not None,
            "evidence_ref": f"evidence/{path}/{start}",
        }
        if source_commit is not None:
            result["source_commit"] = source_commit
        return result

    def call(server: str, tool: str, arguments: dict) -> dict:
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [{"path": "SKILL.md", "type": "file"}],
                "evidence_ref": "evidence/skill-list",
            }
        if tool == "dev_external_skill_read":
            return page("SKILL.md", "# Archdoc\nRead repository evidence.", arguments, source_commit=commit)
        if tool == "dev_git_tracked_files":
            tracked_calls.append(dict(arguments))
            start_after = arguments.get("start_after")
            available = [path for path in all_tracked if start_after is None or path > start_after]
            page_paths = available[: int(arguments["max_results"])]
            truncated = len(available) > len(page_paths)
            return {
                "files": page_paths,
                "next_start_after": page_paths[-1] if truncated else None,
                "truncated": truncated,
                "evidence_ref": f"evidence/tracked/{start_after or 'start'}",
            }
        if tool == "dev_workspace_read":
            path = str(arguments["path"])
            read_calls.append(dict(arguments))
            if path.startswith("docs/"):
                raise RuntimeError("file not found")
            return page(path, repository_content[path], arguments)
        raise AssertionError((server, tool, arguments))

    config = dict(load_contract()["developer_pipeline"]["documentation_runtime"])
    config["tracked_file_page_size"] = 10
    evidence = collect_documentation_evidence(
        stage="baseline",
        expected_source_commit=commit,
        config=config,
        call_tool=call,
    )

    assert evidence.repository_complete is True
    assert len(evidence.repository_tracked_paths) == 47
    assert len(evidence.repository_files) == 47
    assert evidence.repository_skipped_paths == ["assets/logo.png"]
    assert any(item.path == "scripts/release" for item in evidence.repository_files)
    assert len(tracked_calls) == 5
    assert tracked_calls[0].get("start_after") is None
    assert tracked_calls[-1].get("start_after") is not None
    large = next(item for item in evidence.repository_files if item.path == "src/large.py")
    assert large.chunk_count == 2
    assert large.truncated is False
    assert large.content.splitlines()[-1] == "line-2505"
    assert [call["start_line"] for call in read_calls if call["path"] == "src/large.py"] == [1, 2001]


def test_documentation_evidence_skips_low_priority_data_with_an_oversized_single_line() -> None:
    commit = "9" * 40
    oversized_path = "twitter_data/twitter_fetch_snapshot.json"

    def call(server: str, tool: str, arguments: dict) -> dict:
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [{"path": "SKILL.md", "type": "file"}],
            }
        if tool == "dev_external_skill_read":
            return {
                "source_commit": commit,
                "path": "SKILL.md",
                "start_line": 1,
                "end_line": 1,
                "next_start_line": None,
                "content": "# Archdoc",
                "truncated": False,
            }
        if tool == "dev_git_tracked_files":
            return {
                "files": ["src/app.py", oversized_path],
                "next_start_after": None,
                "truncated": False,
            }
        if tool == "dev_workspace_read":
            path = str(arguments["path"])
            if path.startswith("docs/"):
                raise RuntimeError(f"file not found: {path}")
            if path == oversized_path:
                raise RuntimeError(
                    '{"structuredContent": {"error": "line 80 exceeds the per-read byte limit '
                    'for twitter_fetch_snapshot.json"}, "isError": true}'
                )
            return {
                "path": path,
                "start_line": 1,
                "end_line": 1,
                "next_start_line": None,
                "content": "def main(): pass",
                "truncated": False,
            }
        raise AssertionError((server, tool, arguments))

    evidence = collect_documentation_evidence(
        stage="baseline",
        expected_source_commit=commit,
        config=dict(load_contract()["developer_pipeline"]["documentation_runtime"]),
        call_tool=call,
    )

    assert evidence.repository_complete is True
    assert evidence.repository_tracked_paths == ["src/app.py"]
    assert evidence.repository_skipped_paths == [oversized_path]
    assert [item.path for item in evidence.repository_files] == ["src/app.py"]


def test_documentation_evidence_still_fails_for_oversized_source_file() -> None:
    commit = "8" * 40

    def call(server: str, tool: str, arguments: dict) -> dict:
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [{"path": "SKILL.md", "type": "file"}],
            }
        if tool == "dev_external_skill_read":
            return {
                "source_commit": commit,
                "path": "SKILL.md",
                "start_line": 1,
                "end_line": 1,
                "next_start_line": None,
                "content": "# Archdoc",
                "truncated": False,
            }
        if tool == "dev_git_tracked_files":
            return {"files": ["src/app.py"], "next_start_after": None, "truncated": False}
        if tool == "dev_workspace_read":
            path = str(arguments["path"])
            if path.startswith("docs/"):
                raise RuntimeError(f"file not found: {path}")
            raise RuntimeError(
                '{"structuredContent": {"error": "line 1 exceeds the per-read byte limit '
                'for app.py"}, "isError": true}'
            )
        raise AssertionError((server, tool, arguments))

    with pytest.raises(DocumentationAgentError, match="failed to read tracked repository evidence"):
        collect_documentation_evidence(
            stage="baseline",
            expected_source_commit=commit,
            config=dict(load_contract()["developer_pipeline"]["documentation_runtime"]),
            call_tool=call,
        )


def test_documentation_evidence_fails_instead_of_silently_omitting_repository_files() -> None:
    commit = "f" * 40

    def call(server: str, tool: str, arguments: dict) -> dict:
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [{"path": "SKILL.md", "type": "file"}],
            }
        if tool == "dev_external_skill_read":
            return {
                "source_commit": commit,
                "path": "SKILL.md",
                "start_line": 1,
                "end_line": 1,
                "next_start_line": None,
                "content": "# Archdoc",
                "truncated": False,
            }
        if tool == "dev_git_tracked_files":
            return {"files": ["src/a.py", "src/b.py"]}
        if tool == "dev_workspace_read":
            if str(arguments["path"]).startswith("docs/"):
                raise RuntimeError("file not found")
            return {
                "path": arguments["path"],
                "start_line": 1,
                "end_line": 1,
                "next_start_line": None,
                "content": "x = 1",
                "truncated": False,
            }
        raise AssertionError((server, tool, arguments))

    config = dict(load_contract()["developer_pipeline"]["documentation_runtime"])
    config["max_repository_files"] = 1
    with pytest.raises(DocumentationAgentError, match="file budget was exhausted"):
        collect_documentation_evidence(
            stage="baseline",
            expected_source_commit=commit,
            config=config,
            call_tool=call,
        )


def test_missing_optional_document_is_ignored_but_rejected_read_is_not() -> None:
    commit = "1" * 40

    def call(server: str, tool: str, arguments: dict) -> dict:
        if tool == "dev_external_skill_list":
            return {
                "source_commit": commit,
                "entries": [{"path": "SKILL.md", "type": "file"}],
            }
        if tool == "dev_external_skill_read":
            return {
                "source_commit": commit,
                "path": "SKILL.md",
                "start_line": arguments["start_line"],
                "end_line": 1,
                "next_start_line": None,
                "content": "# Archdoc",
                "truncated": False,
            }
        if tool == "dev_git_tracked_files":
            return {"files": ["README.md"], "next_start_after": None, "truncated": False}
        if tool == "dev_workspace_read":
            path = str(arguments["path"])
            if path == "docs/API_SURFACE.md":
                raise RuntimeError("schema_validation_failed: max_lines exceeds 2000")
            if path.startswith("docs/"):
                raise RuntimeError(f"file not found: {path}")
            return {
                "path": path,
                "start_line": arguments["start_line"],
                "end_line": 1,
                "next_start_line": None,
                "content": "# Repository",
                "truncated": False,
            }
        raise AssertionError((server, tool, arguments))

    with pytest.raises(DocumentationAgentError, match="schema_validation_failed"):
        collect_documentation_evidence(
            stage="baseline",
            expected_source_commit=commit,
            config=dict(load_contract()["developer_pipeline"]["documentation_runtime"]),
            call_tool=call,
        )
