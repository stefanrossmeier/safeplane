from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess

import pytest
import yaml

from harness.patch_approval_store import (
    prepare_patch_apply_workspace,
    publish_patch_apply_workspace,
)
from harness.remote_write import (
    RemoteApprovalRequest,
    RemoteWriteConflictError,
    RemoteWriteError,
    RemoteWritePolicyError,
    build_remote_approval_request,
    execute_remote_write,
    GitHubPullRequestClient,
    load_remote_approval,
    remote_approval_id,
    save_remote_approval_request,
)
from harness.repository_workspace import prepare_repository_workspace
from harness.run_store import save_run


REPO_ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def create_bare_repo(root: Path, name: str, files: dict[str, str]) -> tuple[Path, str]:
    work = root / f"{name}-work"
    bare = root / f"{name}.git"
    work.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=work)
    git("config", "user.name", "Fixture", cwd=work)
    git("config", "user.email", "fixture@example.invalid", cwd=work)
    for relative, content in files.items():
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", ".", cwd=work)
    git("commit", "-qm", "fixture", cwd=work)
    commit = git("rev-parse", "HEAD", cwd=work)
    git("clone", "-q", "--bare", str(work), str(bare))
    return bare, commit


def contract_with_archdoc_url(url: str) -> dict:
    contract = yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )
    source = contract["repository_workspace"]["external_sources"]["archdoc"]
    source["repository_url"] = url
    source["repository_url_env"] = None
    return contract


def prepare_remote_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str = "run_remote_fixture",
) -> tuple[Path, dict, Path, str, dict, dict]:
    target_bare, base_commit = create_bare_repo(
        tmp_path,
        "target",
        {
            "README.md": "# Fixture\n",
            "src/value.txt": "before\n",
        },
    )
    skill_bare, _ = create_bare_repo(
        tmp_path,
        "skills",
        {"skills/archdoc/SKILL.md": "# Skill\n"},
    )
    token = "github_pat_fixture_token_not_real"
    secret = tmp_path / "github_token"
    secret.write_text(token + "\n", encoding="utf-8")
    profiles = tmp_path / "repositories.yaml"
    profiles.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "credential_profiles": {
                    "github": {
                        "type": "github_token_file",
                        "secret_path": str(secret),
                        "username": "x-access-token",
                    }
                },
                "repository_profiles": {
                    "fixture": {
                        "enabled": True,
                        "repository_url": target_bare.as_uri(),
                        "ref": "main",
                        "allowed_hosts": [],
                        "allowed_repository": None,
                        "credential_profile": "github",
                        "allow_file_url": True,
                        "remote_write_allowed": True,
                        "branch_prefix": "safeplane/",
                        "pull_request_repository": "fixture/target",
                        "git_author_name": "Safeplane Test",
                        "git_author_email": "safeplane-test@example.invalid",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFEPLANE_REPOSITORY_CONFIG", str(profiles))
    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")
    monkeypatch.setenv("SAFEPLANE_GITHUB_API_URL", "http://localhost:9999")
    home = tmp_path / "home"
    contract = contract_with_archdoc_url(skill_bare.as_uri())
    manifest = prepare_repository_workspace(
        contract=contract,
        safeplane_home=home,
        run_id=run_id,
        repository_profile_id="fixture",
    )

    staged = prepare_patch_apply_workspace(
        home,
        run_id=run_id,
        approval_id="patch_approval_remote_fixture",
    )
    (staged / "src/value.txt").write_text("after\n", encoding="utf-8")
    publish_patch_apply_workspace(
        home,
        run_id=run_id,
        approval_id="patch_approval_remote_fixture",
    )

    plan = {
        "plan_markdown": "Change fixture value.",
        "files_to_modify": ["src/value.txt"],
        "files_to_create": [],
        "files_to_delete": [],
        "file_change_policy": {
            "src/value.txt": {
                "operation": "modified",
                "expected_change": "Update value.",
                "max_changed_lines": 4,
                "max_hunks": 1,
            }
        },
        "test_commands": [["python3", "checks/check.py"]],
        "documentation_impact": "none",
        "risks": [],
        "assumptions": [],
        "commit_message": "Update fixture value",
    }
    pr = {
        "title": "Update fixture value",
        "body_markdown": "## Summary\n\nUpdates the fixture.\n\nHuman review required.",
        "draft": True,
    }
    checks = {
        "mode": "controlled",
        "status": "passed",
        "command_results": [],
        "summary": "Controlled checks passed.",
    }
    review = {
        "verdict": "LGTM",
        "plan_alignment": "ALIGNED",
        "summary": "The bounded change is ready for human review.",
        "requested_changes": [],
        "docs_update_needed": False,
        "risk_notes": [],
    }
    pipeline_dir = home / "workspaces" / run_id / "pipeline"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "planning.json").write_text(json.dumps(plan), encoding="utf-8")
    (pipeline_dir / "checks.json").write_text(json.dumps(checks), encoding="utf-8")
    (pipeline_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")
    (pipeline_dir / "pr.json").write_text(json.dumps(pr), encoding="utf-8")
    request = build_remote_approval_request(
        safeplane_home=home,
        run_id=run_id,
        workspace_manifest=manifest,
        pr_proposal=pr,
        implementation_plan=plan,
        check_result=checks,
        review_result=review,
        created_at="2026-07-19T08:00:00Z",
    )
    request_ref = save_remote_approval_request(home, request)
    pipeline_state = {
        "version": "v1",
        "run_id": run_id,
        "workflow_id": "developer",
        "entrypoint": "develop",
        "current_state": "waiting_for_remote_approval",
        "fake_scenario": "default",
        "completed_stages": [
            "repositories",
            "baseline_documentation",
            "analysis",
            "planning",
            "implementation",
            "checks",
            "final_documentation",
            "review",
            "pr",
            "remote_approval",
        ],
        "artifacts": {
            "planning.json": f"workspaces/{run_id}/pipeline/planning.json",
            "checks.json": f"workspaces/{run_id}/pipeline/checks.json",
            "review.json": f"workspaces/{run_id}/pipeline/review.json",
            "pr.json": f"workspaces/{run_id}/pipeline/pr.json",
            "remote-approval-request.json": request_ref,
        },
        "agent_runs": [],
        "created_at": request.created_at,
        "updated_at": request.created_at,
    }
    (pipeline_dir / "pipeline.json").write_text(json.dumps(pipeline_state), encoding="utf-8")
    save_run(
        home,
        {
            "run_id": run_id,
            "session_id": "sess_remote",
            "session_display_id": "remote01",
            "turn": 1,
            "workflow_id": "developer",
            "entrypoint": "develop",
            "connector": "cli",
            "status": "completed",
            "created_at": request.created_at,
            "updated_at": request.created_at,
            "repository_profile": "fixture",
            "final_message": "waiting",
            "developer_pipeline": {
                "current_state": "waiting_for_remote_approval",
                "completed_stages": pipeline_state["completed_stages"],
                "artifacts": pipeline_state["artifacts"],
                "check_summary": {"status": "passed"},
                "review_verdict": "LGTM",
                "remote_approval_possible": True,
                "remote_approval_binding": {
                    "workspace_tree_sha256": request.workspace_tree_sha256,
                    "branch_name": request.branch_name,
                    "request_ref": request_ref,
                },
            },
        },
    )
    return home, contract, target_bare, base_commit, plan, pr


class FakeGitHubClient:
    created: list[dict] = []
    existing: dict | None = None

    def __init__(self, *, token: str, repository: str) -> None:
        assert token == "github_pat_fixture_token_not_real"
        assert repository == "fixture/target"

    def find_open_pull_request(self, *, branch_name: str, base_ref: str) -> dict | None:
        assert branch_name.startswith("safeplane/")
        assert base_ref == "main"
        return self.existing

    def create_draft_pull_request(self, **kwargs) -> dict:
        self.created.append(kwargs)
        return {
            "number": 7,
            "html_url": "http://github-mock/fixture/target/pull/7",
            "draft": True,
        }


def test_remote_approval_pushes_once_creates_draft_pr_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, base_commit, _, _ = prepare_remote_run(
        tmp_path, monkeypatch
    )
    FakeGitHubClient.created = []
    FakeGitHubClient.existing = None
    monkeypatch.setattr("harness.remote_write.GitHubPullRequestClient", FakeGitHubClient)

    first = execute_remote_write(
        safeplane_home=home,
        contract=contract,
        run_id="run_remote_fixture",
        connector="cli",
    )
    second = execute_remote_write(
        safeplane_home=home,
        contract=contract,
        run_id="run_remote_fixture",
        connector="telegram",
    )

    assert first == second
    assert first.draft is True
    assert first.branch_reused is False
    assert first.pull_request_reused is False
    assert len(FakeGitHubClient.created) == 1
    created_body = FakeGitHubClient.created[0]["body"]
    assert "## Safeplane evidence" in created_body
    assert "Review verdict: `LGTM`" in created_body
    assert "Controlled checks: `passed`" in created_body
    assert "Human inspection is required" in created_body
    assert "does not merge" in created_body
    remote_commit = git(
        "--git-dir", str(target_bare), "rev-parse", f"refs/heads/{first.branch_name}"
    )
    assert remote_commit == first.commit_sha
    assert remote_commit != base_commit
    assert (
        git("--git-dir", str(target_bare), "show", f"{remote_commit}:src/value.txt")
        == "after"
    )
    run = json.loads((home / "runs/run_remote_fixture.json").read_text())
    assert run["developer_pipeline"]["current_state"] == "completed"
    assert run["developer_pipeline"]["remote_approval_possible"] is False
    assert run["remote_write"]["pull_request_url"].endswith("/pull/7")
    assert "did not merge" in run["final_message"]

    approval = load_remote_approval(
        home,
        run_id="run_remote_fixture",
        approval_id=first.approval_id,
    )
    serialized = json.dumps(approval)
    assert "github_pat_fixture_token_not_real" not in serialized
    assert "github_pat_fixture_token_not_real" not in (
        home / first.evidence_ref
    ).read_text(encoding="utf-8")
    checkout_config = (
        home / "workspaces/run_remote_fixture/repo/.git/config"
    ).read_text(encoding="utf-8")
    assert "github_pat_fixture_token_not_real" not in checkout_config


def test_remote_approval_rejects_workspace_changed_after_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    staged = prepare_patch_apply_workspace(
        home,
        run_id="run_remote_fixture",
        approval_id="patch_approval_mutation",
    )
    (staged / "src/value.txt").write_text("mutated\n", encoding="utf-8")
    publish_patch_apply_workspace(
        home,
        run_id="run_remote_fixture",
        approval_id="patch_approval_mutation",
    )
    before_refs = git("--git-dir", str(target_bare), "for-each-ref", "--format=%(refname)")
    with pytest.raises(RemoteWriteConflictError, match="workspace changed"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )
    after_refs = git("--git-dir", str(target_bare), "for-each-ref", "--format=%(refname)")
    assert after_refs == before_refs


def test_remote_approval_rejects_moved_base_without_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    mover = tmp_path / "mover"
    git("clone", "-q", str(target_bare), str(mover))
    git("config", "user.name", "Mover", cwd=mover)
    git("config", "user.email", "mover@example.invalid", cwd=mover)
    (mover / "remote-change.txt").write_text("moved\n", encoding="utf-8")
    git("add", ".", cwd=mover)
    git("commit", "-qm", "move base", cwd=mover)
    git("push", "-q", "origin", "main", cwd=mover)

    monkeypatch.setattr("harness.remote_write.GitHubPullRequestClient", FakeGitHubClient)
    with pytest.raises(RemoteWriteConflictError, match="remote base branch moved"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )
    refs = git("--git-dir", str(target_bare), "for-each-ref", "--format=%(refname)")
    assert "refs/heads/safeplane/" not in refs


@pytest.mark.parametrize(
    ("pipeline_updates", "message"),
    [
        ({"check_summary": {"status": "failed"}}, "passing controlled checks"),
        ({"review_verdict": "REQUEST_CHANGES"}, "LGTM review verdict"),
        ({"current_state": "review_changes_requested"}, "not waiting for remote approval"),
    ],
)
def test_remote_approval_rejects_ineligible_pipeline_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_updates: dict,
    message: str,
) -> None:
    home, contract, _, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    run_path = home / "runs/run_remote_fixture.json"
    run = json.loads(run_path.read_text())
    run["developer_pipeline"].update(pipeline_updates)
    run_path.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises((RemoteWritePolicyError, RemoteWriteConflictError), match=message):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )


def test_remote_approval_refuses_existing_different_branch_without_force_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    request = json.loads(
        (home / "workspaces/run_remote_fixture/pipeline/remote-approval-request.json").read_text()
    )
    collision = tmp_path / "collision"
    git("clone", "-q", str(target_bare), str(collision))
    git("config", "user.name", "Collision", cwd=collision)
    git("config", "user.email", "collision@example.invalid", cwd=collision)
    git("switch", "-qc", request["branch_name"], cwd=collision)
    (collision / "collision.txt").write_text("collision\n", encoding="utf-8")
    git("add", ".", cwd=collision)
    git("commit", "-qm", "collision", cwd=collision)
    git("push", "-q", "origin", f"HEAD:refs/heads/{request['branch_name']}", cwd=collision)

    monkeypatch.setattr("harness.remote_write.GitHubPullRequestClient", FakeGitHubClient)
    with pytest.raises(RemoteWriteConflictError, match="no force push allowed"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )
    collision_commit = git(
        "--git-dir", str(target_bare), "rev-parse", f"refs/heads/{request['branch_name']}"
    )
    assert git("--git-dir", str(target_bare), "show", f"{collision_commit}:collision.txt") == "collision"


def test_remote_approval_rejects_changed_check_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    checks_path = home / "workspaces/run_remote_fixture/pipeline/checks.json"
    checks = json.loads(checks_path.read_text(encoding="utf-8"))
    checks["summary"] = "changed after approval request"
    checks_path.write_text(json.dumps(checks), encoding="utf-8")

    with pytest.raises(RemoteWriteConflictError, match="check evidence changed"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )
    refs = git("--git-dir", str(target_bare), "for-each-ref", "--format=%(refname)")
    assert "refs/heads/safeplane/" not in refs


def test_remote_approval_rejects_changed_git_author_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    config_path = Path(os.environ["SAFEPLANE_REPOSITORY_CONFIG"])
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["repository_profiles"]["fixture"]["git_author_name"] = "Changed Author"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(RemoteWriteConflictError, match="Git author name changed"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )
    refs = git("--git-dir", str(target_bare), "for-each-ref", "--format=%(refname)")
    assert "refs/heads/safeplane/" not in refs


def test_github_api_url_rejects_arbitrary_https_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFEPLANE_GITHUB_API_URL", "https://example.invalid")
    with pytest.raises(RemoteWritePolicyError, match="api.github.com"):
        GitHubPullRequestClient(
            token="github_pat_fixture_token_not_real",
            repository="fixture/target",
        )


class FlakyAfterCreateGitHubClient:
    existing: dict | None = None
    create_calls = 0

    def __init__(self, *, token: str, repository: str) -> None:
        assert token == "github_pat_fixture_token_not_real"
        assert repository == "fixture/target"

    def find_open_pull_request(self, *, branch_name: str, base_ref: str) -> dict | None:
        return self.existing

    def create_draft_pull_request(self, **_kwargs) -> dict:
        type(self).create_calls += 1
        type(self).existing = {
            "number": 8,
            "html_url": "http://github-mock/fixture/target/pull/8",
            "draft": True,
        }
        raise RemoteWriteError("ambiguous API failure after remote creation")


def test_remote_approval_retry_reuses_branch_and_pr_after_partial_remote_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    FlakyAfterCreateGitHubClient.existing = None
    FlakyAfterCreateGitHubClient.create_calls = 0
    monkeypatch.setattr(
        "harness.remote_write.GitHubPullRequestClient", FlakyAfterCreateGitHubClient
    )

    with pytest.raises(RemoteWriteError, match="ambiguous API failure"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )

    retry = execute_remote_write(
        safeplane_home=home,
        contract=contract,
        run_id="run_remote_fixture",
        connector="cli",
    )
    assert retry.branch_reused is True
    assert retry.pull_request_reused is True
    assert retry.pull_request_number == 8
    assert FlakyAfterCreateGitHubClient.create_calls == 1
    assert git(
        "--git-dir", str(target_bare), "rev-parse", f"refs/heads/{retry.branch_name}"
    ) == retry.commit_sha


def test_remote_approval_reports_missing_harness_credential_as_policy_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, _, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    Path(os.environ["SAFEPLANE_REPOSITORY_CONFIG"]).parent.joinpath("github_token").unlink()

    with pytest.raises(RemoteWritePolicyError, match="secret file is missing"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )


def test_remote_approval_retry_repairs_local_state_after_remote_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, contract, target_bare, _, _, _ = prepare_remote_run(tmp_path, monkeypatch)
    FakeGitHubClient.created = []
    FakeGitHubClient.existing = None
    monkeypatch.setattr("harness.remote_write.GitHubPullRequestClient", FakeGitHubClient)

    from harness import remote_write as remote_write_module

    real_mark = remote_write_module._mark_pipeline_remote_write_completed
    failures = 0

    def fail_once(*args, **kwargs):
        nonlocal failures
        failures += 1
        if failures == 1:
            raise RuntimeError("local finalization interrupted")
        return real_mark(*args, **kwargs)

    monkeypatch.setattr(
        remote_write_module,
        "_mark_pipeline_remote_write_completed",
        fail_once,
    )
    with pytest.raises(RuntimeError, match="local finalization interrupted"):
        execute_remote_write(
            safeplane_home=home,
            contract=contract,
            run_id="run_remote_fixture",
            connector="cli",
        )

    request = json.loads(
        (home / "workspaces/run_remote_fixture/pipeline/remote-approval-request.json").read_text()
    )
    completed_approval = load_remote_approval(
        home,
        run_id="run_remote_fixture",
        approval_id=remote_approval_id(RemoteApprovalRequest.model_validate(request)),
    )
    assert completed_approval["status"] == "completed"

    retry = execute_remote_write(
        safeplane_home=home,
        contract=contract,
        run_id="run_remote_fixture",
        connector="cli",
    )
    assert failures == 2
    assert len(FakeGitHubClient.created) == 1
    assert git(
        "--git-dir", str(target_bare), "rev-parse", f"refs/heads/{retry.branch_name}"
    ) == retry.commit_sha
    run = json.loads((home / "runs/run_remote_fixture.json").read_text())
    assert run["developer_pipeline"]["current_state"] == "completed"
    assert run["remote_write"]["pull_request_url"] == retry.pull_request_url
