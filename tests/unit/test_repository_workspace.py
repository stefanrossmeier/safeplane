from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from harness import repository_workspace as repository_workspace_module
from harness.repository_workspace import (
    GitCredentialProfile,
    GitLocation,
    RepositoryProfile,
    RepositoryProfileError,
    authorize_external_source,
    clone_repository,
    git_auth_environment,
    parse_git_location,
    prepare_repository_workspace,
    validate_git_ref,
)
from harness.patch_approval_store import (
    prepare_patch_apply_workspace,
    publish_patch_apply_workspace,
)


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
    git("config", "user.email", "fixture@example.invalid", cwd=work)
    git("config", "user.name", "Fixture", cwd=work)
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
    contract["repository_workspace"]["external_sources"]["archdoc"][
        "repository_url"
    ] = url
    contract["repository_workspace"]["external_sources"]["archdoc"][
        "repository_url_env"
    ] = None
    return contract


def write_profiles(path: Path, target_url: str, *, enabled: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "credential_profiles": {},
                "repository_profiles": {
                    "fixture": {
                        "enabled": enabled,
                        "repository_url": target_url,
                        "ref": "main",
                        "allowed_hosts": [],
                        "allowed_repository": None,
                        "credential_profile": None,
                        "allow_file_url": True,
                        "remote_write_allowed": False,
                        "branch_prefix": "safeplane/",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_clone_repository_resolves_ref_before_detached_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "checkout"
    commit = "a" * 40
    location = GitLocation(
        sanitized_url="https://github.com/example/repository.git",
        scheme="https",
        host="github.com",
        repository_name="example/repository",
        local_path=None,
    )
    calls: list[list[str]] = []

    def fake_run_git(
        args: list[str],
        *,
        cwd: Path | None,
        env: dict[str, str],
        secrets: list[str],
    ) -> str:
        calls.append(args)
        if args[0] == "clone":
            destination.mkdir(parents=True)
            return ""
        if args == ["fetch", "--quiet", "--no-tags", "origin", "main"]:
            return ""
        if args == ["rev-parse", "--verify", "FETCH_HEAD^{commit}"]:
            return commit
        if args == ["switch", "--quiet", "--detach", commit]:
            return ""
        if args == ["rev-parse", "HEAD"]:
            return commit
        if args == ["remote", "get-url", "origin"]:
            return location.sanitized_url
        raise AssertionError(f"unexpected git invocation: {args}")

    monkeypatch.setattr(repository_workspace_module, "_run_git", fake_run_git)

    result = clone_repository(
        location=location,
        ref="main",
        destination=destination,
        run_tmp_dir=tmp_path / "tmp",
        credential=None,
    )

    assert result["commit"] == commit
    assert ["switch", "--quiet", "--detach", commit] in calls
    assert not any(args and args[0] == "checkout" for args in calls)


def test_prepare_git_multi_repository_workspace_records_commits_and_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_bare, target_commit = create_bare_repo(
        tmp_path,
        "target",
        {"README.md": "target\n", "src/app.py": "print('ok')\n"},
    )
    skill_bare, skill_commit = create_bare_repo(
        tmp_path,
        "skills",
        {"skills/archdoc/SKILL.md": "# Archdoc fixture\n"},
    )
    config_path = tmp_path / "profiles.yaml"
    write_profiles(config_path, target_bare.as_uri())
    monkeypatch.setenv("SAFEPLANE_REPOSITORY_CONFIG", str(config_path))
    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")

    home = tmp_path / "home"
    manifest = prepare_repository_workspace(
        contract=contract_with_archdoc_url(skill_bare.as_uri()),
        safeplane_home=home,
        run_id="run_fixture",
        repository_profile_id="fixture",
    )

    target = home / "workspaces/run_fixture/repo"
    skills = home / "workspaces/run_fixture/repos/skills/ai-craftkit"
    assert (target / ".git").is_dir()
    assert (skills / ".git").is_dir()
    assert (skills / "skills/archdoc/SKILL.md").is_file()
    assert manifest["workspace_kind"] == "git_multi_repository"
    assert manifest["target"]["resolved_commit"] == target_commit
    assert manifest["external_sources"]["archdoc"]["resolved_commit"] == skill_commit
    assert manifest["external_sources"]["archdoc"]["allowed_agents"] == ["documentation"]
    assert target.stat().st_mode & 0o222 == 0
    assert skills.stat().st_mode & 0o222 == 0

    authorized = authorize_external_source(
        manifest,
        source_id="archdoc",
        agent_id="documentation",
    )
    assert authorized["required_path"] == "skills/archdoc"
    with pytest.raises(RepositoryProfileError, match="not allowed"):
        authorize_external_source(manifest, source_id="archdoc", agent_id="analysis")

    persisted = json.loads(
        (home / "workspaces/run_fixture/workspace.json").read_text(encoding="utf-8")
    )
    assert persisted == {key: value for key, value in manifest.items() if key != "manifest_ref"}


def test_two_repository_runs_are_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_bare, _ = create_bare_repo(tmp_path, "target", {"README.md": "target\n"})
    skill_bare, _ = create_bare_repo(
        tmp_path, "skills", {"skills/archdoc/SKILL.md": "skill\n"}
    )
    config_path = tmp_path / "profiles.yaml"
    write_profiles(config_path, target_bare.as_uri())
    monkeypatch.setenv("SAFEPLANE_REPOSITORY_CONFIG", str(config_path))
    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")
    contract = contract_with_archdoc_url(skill_bare.as_uri())
    home = tmp_path / "home"

    first = prepare_repository_workspace(
        contract=contract,
        safeplane_home=home,
        run_id="run_one",
        repository_profile_id="fixture",
    )
    second = prepare_repository_workspace(
        contract=contract,
        safeplane_home=home,
        run_id="run_two",
        repository_profile_id="fixture",
    )

    assert first["repository_root"] != second["repository_root"]
    assert first["target"]["resolved_commit"] == second["target"]["resolved_commit"]


def test_repository_url_validation_rejects_credentials_and_wrong_repository() -> None:
    with pytest.raises(RepositoryProfileError, match="must not contain credentials"):
        parse_git_location(
            "https://token@github.com/example/repo.git",
            allowed_hosts=["github.com"],
            allowed_repository="example/repo",
            allow_file_url=False,
        )

    with pytest.raises(RepositoryProfileError, match="not allowed"):
        parse_git_location(
            "https://github.com/example/other.git",
            allowed_hosts=["github.com"],
            allowed_repository="example/repo",
            allow_file_url=False,
        )


def test_missing_archdoc_path_removes_incomplete_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_bare, _ = create_bare_repo(tmp_path, "target", {"README.md": "target\n"})
    skill_bare, _ = create_bare_repo(tmp_path, "skills", {"README.md": "no skill\n"})
    config_path = tmp_path / "profiles.yaml"
    write_profiles(config_path, target_bare.as_uri())
    monkeypatch.setenv("SAFEPLANE_REPOSITORY_CONFIG", str(config_path))
    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")
    home = tmp_path / "home"

    with pytest.raises(RepositoryProfileError, match="missing required path"):
        prepare_repository_workspace(
            contract=contract_with_archdoc_url(skill_bare.as_uri()),
            safeplane_home=home,
            run_id="run_missing",
            repository_profile_id="fixture",
        )
    assert not (home / "workspaces/run_missing").exists()


def test_local_fixture_clone_uses_exact_temporary_safe_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture.git"
    fixture.mkdir()
    destination = tmp_path / "checkout"
    commit = "b" * 40
    location = GitLocation(
        sanitized_url=fixture.as_uri(),
        scheme="file",
        host=None,
        repository_name=None,
        local_path=str(fixture),
    )
    observed_config: Path | None = None

    def fake_run_git(
        args: list[str],
        *,
        cwd: Path | None,
        env: dict[str, str],
        secrets: list[str],
    ) -> str:
        nonlocal observed_config
        observed_config = Path(env["GIT_CONFIG_GLOBAL"])
        configured = subprocess.check_output(
            [
                "git",
                "config",
                "--file",
                str(observed_config),
                "--get-all",
                "safe.directory",
            ],
            text=True,
        ).splitlines()
        assert configured == [str(fixture.resolve())]
        if args[0] == "clone":
            destination.mkdir(parents=True)
            return ""
        if args == ["fetch", "--quiet", "--no-tags", "origin", "main"]:
            return ""
        if args == ["rev-parse", "--verify", "FETCH_HEAD^{commit}"]:
            return commit
        if args == ["switch", "--quiet", "--detach", commit]:
            return ""
        if args == ["rev-parse", "HEAD"]:
            return commit
        if args == ["remote", "get-url", "origin"]:
            return location.sanitized_url
        raise AssertionError(f"unexpected git invocation: {args}")

    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")
    monkeypatch.setattr(repository_workspace_module, "_run_git", fake_run_git)

    result = clone_repository(
        location=location,
        ref="main",
        destination=destination,
        run_tmp_dir=tmp_path / "tmp",
        credential=None,
    )

    assert result["commit"] == commit
    assert observed_config is not None
    assert not observed_config.exists()


def test_local_fixture_trust_requires_explicit_fixture_mode(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.git"
    fixture.mkdir()

    with pytest.raises(RepositoryProfileError, match="explicit local fixtures"):
        with git_auth_environment(
            run_tmp_dir=tmp_path / "tmp",
            credential=None,
            trusted_local_repository=fixture,
        ):
            raise AssertionError("context must not open")


def test_git_credential_askpass_is_temporary_and_token_is_not_persisted(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "github_token"
    secret.write_text("super-secret-token\n", encoding="utf-8")
    credential = GitCredentialProfile(
        type="github_token_file",
        secret_path=str(secret),
        username="x-access-token",
    )
    with git_auth_environment(run_tmp_dir=tmp_path / "tmp", credential=credential) as (
        env,
        secrets,
    ):
        askpass = Path(env["GIT_ASKPASS"])
        assert askpass.is_file()
        assert env["SAFEPLANE_GIT_TOKEN"] == "super-secret-token"
        assert secrets == ["super-secret-token"]
        assert "super-secret-token" not in askpass.read_text(encoding="utf-8")
    assert not askpass.exists()


def test_https_profiles_require_host_and_repository_allowlists() -> None:
    with pytest.raises(RepositoryProfileError, match="must declare"):
        parse_git_location(
            "https://github.com/example/repo.git",
            allowed_hosts=[],
            allowed_repository=None,
            allow_file_url=False,
        )


def test_git_ref_and_credential_path_validation() -> None:
    with pytest.raises(RepositoryProfileError, match="invalid Git ref"):
        validate_git_ref("--upload-pack=evil")
    with pytest.raises(ValueError, match="secret_path must be absolute"):
        GitCredentialProfile(
            type="github_token_file",
            secret_path="relative/token",
        )


def test_repository_workspace_reuses_completed_manifest_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_bare, target_commit = create_bare_repo(
        tmp_path, "target", {"README.md": "target\n"}
    )
    skill_bare, skill_commit = create_bare_repo(
        tmp_path, "skills", {"skills/archdoc/SKILL.md": "skill\n"}
    )
    config_path = tmp_path / "profiles.yaml"
    write_profiles(config_path, target_bare.as_uri())
    monkeypatch.setenv("SAFEPLANE_REPOSITORY_CONFIG", str(config_path))
    monkeypatch.setenv("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "yes")
    contract = contract_with_archdoc_url(skill_bare.as_uri())
    home = tmp_path / "home"

    first = prepare_repository_workspace(
        contract=contract,
        safeplane_home=home,
        run_id="run_resume",
        repository_profile_id="fixture",
    )
    approval_id = "patch_approval_resume"
    staged = prepare_patch_apply_workspace(
        home,
        run_id="run_resume",
        approval_id=approval_id,
    )
    marker = staged / "resume-marker.txt"
    marker.write_text("preserve\n", encoding="utf-8")
    publish_patch_apply_workspace(
        home,
        run_id="run_resume",
        approval_id=approval_id,
    )
    published_marker = home / "workspaces/run_resume/repo/resume-marker.txt"

    second = prepare_repository_workspace(
        contract=contract,
        safeplane_home=home,
        run_id="run_resume",
        repository_profile_id="fixture",
    )

    assert second["resumed"] is True
    assert second["target"]["resolved_commit"] == target_commit
    assert second["external_sources"]["archdoc"]["resolved_commit"] == skill_commit
    assert published_marker.read_text(encoding="utf-8") == "preserve\n"
    assert published_marker.stat().st_mode & 0o222 == 0
    assert first["manifest_ref"] == second["manifest_ref"]


def test_remote_write_profile_requires_credential_and_pull_request_repository() -> None:
    with pytest.raises(Exception, match="credential_profile"):
        repository_workspace_module.RepositoryProfile(
            enabled=True,
            repository_url="https://github.com/example/repo.git",
            ref="main",
            allowed_hosts=["github.com"],
            allowed_repository="example/repo",
            credential_profile=None,
            remote_write_allowed=True,
        )

    profile = repository_workspace_module.RepositoryProfile(
        enabled=True,
        repository_url="https://github.com/example/repo.git",
        ref="main",
        allowed_hosts=["github.com"],
        allowed_repository="example/repo",
        credential_profile="github",
        remote_write_allowed=True,
        branch_prefix="safeplane/",
    )
    assert profile.remote_write_allowed is True
    assert profile.pull_request_repository is None
    assert profile.git_author_name == "Safeplane"


def test_remote_write_profile_rejects_non_github_and_cross_repository_targets() -> None:
    with pytest.raises(ValueError, match="github.com repositories only"):
        RepositoryProfile.model_validate(
            {
                "enabled": True,
                "repository_url": "https://gitlab.example/owner/repo.git",
                "ref": "main",
                "allowed_hosts": ["gitlab.example"],
                "allowed_repository": "owner/repo",
                "credential_profile": "github",
                "remote_write_allowed": True,
                "pull_request_repository": "owner/repo",
                "allow_file_url": True,
            }
        )

    with pytest.raises(ValueError, match="cross-repository"):
        RepositoryProfile.model_validate(
            {
                "enabled": True,
                "repository_url": "https://github.com/owner/repo.git",
                "ref": "main",
                "allowed_hosts": ["github.com"],
                "allowed_repository": "owner/repo",
                "credential_profile": "github",
                "remote_write_allowed": True,
                "pull_request_repository": "other/repo",
            }
        )


def test_repository_profile_allows_opt_in_automatic_draft_pr_creation() -> None:
    profile = RepositoryProfile(
        repository_url="https://github.com/example/repo.git",
        allowed_hosts=["github.com"],
        allowed_repository="example/repo",
        credential_profile="github",
        remote_write_allowed=True,
        draft_pr_creation="automatic",
    )

    assert profile.draft_pr_creation == "automatic"


def test_repository_profile_rejects_automatic_draft_pr_without_remote_write() -> None:
    with pytest.raises(ValueError, match="requires remote_write_allowed"):
        RepositoryProfile(
            repository_url="https://github.com/example/repo.git",
            allowed_hosts=["github.com"],
            allowed_repository="example/repo",
            draft_pr_creation="automatic",
        )
