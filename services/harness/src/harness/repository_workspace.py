from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RepositoryWorkspaceError(RuntimeError):
    pass


class RepositoryProfileError(RepositoryWorkspaceError):
    pass


class RepositoryCloneError(RepositoryWorkspaceError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitCredentialProfile(StrictModel):
    type: Literal["github_token_file"]
    secret_path: str = Field(min_length=1)
    username: str = Field(default="x-access-token", min_length=1)

    @model_validator(mode="after")
    def validate_secret_path(self) -> "GitCredentialProfile":
        if not Path(self.secret_path).is_absolute():
            raise ValueError("Git credential secret_path must be absolute inside the harness")
        return self


class RepositoryProfile(StrictModel):
    enabled: bool = True
    repository_url: str = Field(min_length=1)
    ref: str = Field(default="main", min_length=1)
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_repository: str | None = None
    credential_profile: str | None = None
    allow_file_url: bool = False
    remote_write_allowed: bool = False
    draft_pr_creation: Literal["approval_required", "automatic"] = "approval_required"
    branch_prefix: str = "safeplane/"
    pull_request_repository: str | None = None
    git_author_name: str = Field(default="Safeplane", min_length=1, max_length=100)
    git_author_email: str = Field(
        default="safeplane@example.invalid", min_length=3, max_length=254
    )

    @model_validator(mode="after")
    def validate_remote_write(self) -> "RepositoryProfile":
        if not self.branch_prefix.endswith("/"):
            raise ValueError("branch_prefix must end with '/'")
        if (
            self.branch_prefix.startswith("/")
            or self.branch_prefix.startswith("-")
            or ".." in self.branch_prefix
            or "//" in self.branch_prefix
            or "@{" in self.branch_prefix
            or any(char.isspace() or ord(char) < 32 for char in self.branch_prefix)
            or any(char in self.branch_prefix for char in "~^:?*[\\")
        ):
            raise ValueError("branch_prefix is not a safe Git ref prefix")
        pr_repository = self.pull_request_repository or self.allowed_repository
        if self.draft_pr_creation == "automatic" and not self.remote_write_allowed:
            raise ValueError("automatic draft PR creation requires remote_write_allowed")
        if self.remote_write_allowed:
            if not self.credential_profile:
                raise ValueError("remote-write profiles require credential_profile")
            if not pr_repository:
                raise ValueError(
                    "remote-write profiles require pull_request_repository or allowed_repository"
                )
            parsed = urlsplit(self.repository_url)
            if parsed.scheme == "https":
                if parsed.hostname != "github.com":
                    raise ValueError(
                        "remote-write profiles support github.com repositories only"
                    )
                if self.allowed_repository and pr_repository != self.allowed_repository:
                    raise ValueError(
                        "cross-repository pull requests are outside the remote-write policy"
                    )
            elif parsed.scheme == "file":
                if not self.allow_file_url:
                    raise ValueError(
                        "file remote-write profiles require explicit local fixture mode"
                    )
            else:
                raise ValueError(
                    "remote-write profiles support github.com repositories only"
                )
        if pr_repository and not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", pr_repository
        ):
            raise ValueError("pull_request_repository must be owner/repository")
        if "@" not in self.git_author_email or any(
            char.isspace() or ord(char) < 32 for char in self.git_author_email
        ):
            raise ValueError("git_author_email must be a valid non-secret email address")
        return self


class RepositoryProfilesConfig(StrictModel):
    version: Literal[1]
    credential_profiles: dict[str, GitCredentialProfile] = Field(default_factory=dict)
    repository_profiles: dict[str, RepositoryProfile]


class ExternalSourceProfile(StrictModel):
    repository_url: str = Field(min_length=1)
    repository_url_env: str | None = None
    ref: str = Field(default="main", min_length=1)
    checkout_name: str = Field(min_length=1)
    required_path: str = Field(min_length=1)
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_repository: str | None = None
    allowed_agents: list[str] = Field(min_length=1)
    read_only: Literal[True] = True
    allow_file_url_for_tests: bool = False

    @model_validator(mode="after")
    def validate_agents(self) -> "ExternalSourceProfile":
        if len(set(self.allowed_agents)) != len(self.allowed_agents):
            raise ValueError("external source allowed_agents must not contain duplicates")
        return self


class GitLocation(StrictModel):
    sanitized_url: str
    scheme: Literal["https", "file"]
    host: str | None
    repository_name: str | None
    local_path: str | None


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise RepositoryProfileError(f"invalid {label}: {value!r}")
    return value


def _normalize_repository_name(path: str) -> str:
    normalized = path.strip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized



def validate_git_ref(ref: str) -> str:
    if not ref or ref.startswith("-") or any(char.isspace() or ord(char) < 32 for char in ref):
        raise RepositoryProfileError(f"invalid Git ref: {ref!r}")
    return ref

def _local_fixture_urls_enabled() -> bool:
    return os.environ.get("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "no").lower() in {
        "1",
        "true",
        "yes",
    }


def parse_git_location(
    raw_url: str,
    *,
    allowed_hosts: list[str],
    allowed_repository: str | None,
    allow_file_url: bool,
) -> GitLocation:
    if not raw_url or any(char in raw_url for char in "\r\n\x00"):
        raise RepositoryProfileError("repository URL is empty or malformed")

    parsed = urlsplit(raw_url)
    scheme = parsed.scheme.lower()

    if scheme == "https":
        if not allowed_hosts or not allowed_repository:
            raise RepositoryProfileError(
                "HTTPS repository profiles must declare allowed_hosts and allowed_repository"
            )
        if parsed.username is not None or parsed.password is not None:
            raise RepositoryProfileError("repository URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise RepositoryProfileError("repository URL must not contain query or fragment data")
        host = (parsed.hostname or "").lower()
        if not host:
            raise RepositoryProfileError("repository URL is missing a host")
        normalized_hosts = {item.lower() for item in allowed_hosts}
        if normalized_hosts and host not in normalized_hosts:
            raise RepositoryProfileError(f"repository host is not allowed: {host}")
        repository_name = _normalize_repository_name(unquote(parsed.path))
        if not repository_name or "/" not in repository_name:
            raise RepositoryProfileError("repository URL must contain owner/repository")
        if allowed_repository and repository_name.lower() != allowed_repository.lower().removesuffix(
            ".git"
        ):
            raise RepositoryProfileError(
                f"repository is not allowed: {repository_name}; expected {allowed_repository}"
            )
        clean_netloc = host
        if parsed.port and parsed.port != 443:
            raise RepositoryProfileError("non-standard HTTPS repository ports are not allowed")
        sanitized = urlunsplit(("https", clean_netloc, parsed.path, "", ""))
        return GitLocation(
            sanitized_url=sanitized,
            scheme="https",
            host=host,
            repository_name=repository_name,
            local_path=None,
        )

    if scheme == "file":
        if not allow_file_url or not _local_fixture_urls_enabled():
            raise RepositoryProfileError("file repository URLs are allowed only for explicit local fixtures")
        if parsed.netloc not in {"", "localhost"} or parsed.query or parsed.fragment:
            raise RepositoryProfileError("file repository URL is malformed")
        local = Path(unquote(parsed.path)).expanduser().resolve(strict=True)
        if not local.is_dir():
            raise RepositoryProfileError(f"local repository fixture is not a directory: {local}")
        return GitLocation(
            sanitized_url=local.as_uri(),
            scheme="file",
            host=None,
            repository_name=None,
            local_path=str(local),
        )

    raise RepositoryProfileError("only https:// and explicitly enabled file:// repository URLs are supported")


def load_repository_profiles(path: Path) -> RepositoryProfilesConfig:
    if not path.exists():
        raise RepositoryProfileError(
            f"repository profile config not found: {path}; copy config/repositories.example.yaml "
            "to SAFEPLANE_HOME/config/repositories.yaml"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return RepositoryProfilesConfig.model_validate(raw)
    except Exception as exc:
        raise RepositoryProfileError(f"invalid repository profile config: {path}: {exc}") from exc


def repository_profiles_path(contract: dict[str, Any]) -> Path:
    config = contract.get("repository_workspace") or {}
    env_name = str(config.get("profiles_path_env", "SAFEPLANE_REPOSITORY_CONFIG"))
    default = str(config.get("profiles_path_default", "/data/safeplane/config/repositories.yaml"))
    return Path(os.environ.get(env_name, default)).expanduser()


def external_source_profiles(contract: dict[str, Any]) -> dict[str, ExternalSourceProfile]:
    config = contract.get("repository_workspace") or {}
    raw_profiles = config.get("external_sources") or {}
    if not isinstance(raw_profiles, dict):
        raise RepositoryProfileError("repository_workspace.external_sources must be a mapping")
    result: dict[str, ExternalSourceProfile] = {}
    for source_id, raw in raw_profiles.items():
        _safe_identifier(str(source_id), "external source id")
        try:
            profile = ExternalSourceProfile.model_validate(raw)
            _safe_identifier(profile.checkout_name, "external source checkout name")
            required_path = Path(profile.required_path)
            if required_path.is_absolute() or ".." in required_path.parts:
                raise ValueError("external source required_path must stay inside the checkout")
            result[str(source_id)] = profile
        except Exception as exc:
            raise RepositoryProfileError(f"invalid external source profile {source_id!r}: {exc}") from exc
    return result


def _make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o555)
        else:
            mode = path.stat().st_mode
            path.chmod(0o555 if mode & 0o111 else 0o444)
    root.chmod(0o555)


def _sanitize_text(text: str, secrets: list[str]) -> str:
    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


@contextmanager
def git_auth_environment(
    *,
    run_tmp_dir: Path,
    credential: GitCredentialProfile | None,
    trusted_local_repository: Path | None = None,
) -> Iterator[tuple[dict[str, str], list[str]]]:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    secrets: list[str] = []
    askpass_path: Path | None = None
    git_config_path: Path | None = None

    if trusted_local_repository is not None:
        if not _local_fixture_urls_enabled():
            raise RepositoryProfileError(
                "trusted local Git directories are allowed only for explicit local fixtures"
            )
        trusted_path = trusted_local_repository.resolve(strict=True)
        run_tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix="git-config-", dir=run_tmp_dir)
        os.close(fd)
        git_config_path = Path(raw_path)
        try:
            completed = subprocess.run(
                [
                    "git",
                    "config",
                    "--file",
                    str(git_config_path),
                    "--add",
                    "safe.directory",
                    str(trusted_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            git_config_path.unlink(missing_ok=True)
            raise RepositoryCloneError("git is not installed in the harness runtime") from exc
        except subprocess.TimeoutExpired as exc:
            git_config_path.unlink(missing_ok=True)
            raise RepositoryCloneError("timed out preparing local Git fixture trust") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            git_config_path.unlink(missing_ok=True)
            raise RepositoryCloneError(
                f"failed to prepare local Git fixture trust: {detail[:1000]}"
            )
        git_config_path.chmod(0o600)
        env["GIT_CONFIG_GLOBAL"] = str(git_config_path)

    if credential is not None:
        secret_path = Path(credential.secret_path)
        if not secret_path.is_file():
            raise RepositoryProfileError(f"Git credential secret file is missing: {secret_path}")
        token = secret_path.read_text(encoding="utf-8").strip()
        if not token:
            raise RepositoryProfileError(f"Git credential secret file is empty: {secret_path}")
        secrets.append(token)
        run_tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix="git-askpass-", dir=run_tmp_dir)
        os.close(fd)
        askpass_path = Path(raw_path)
        askpass_path.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *Username*) printf '%s\\n' \"$SAFEPLANE_GIT_USERNAME\" ;;\n"
            "  *) printf '%s\\n' \"$SAFEPLANE_GIT_TOKEN\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        askpass_path.chmod(0o700)
        env.update(
            {
                "GIT_ASKPASS": str(askpass_path),
                "SAFEPLANE_GIT_USERNAME": credential.username,
                "SAFEPLANE_GIT_TOKEN": token,
            }
        )

    try:
        yield env, secrets
    finally:
        env.pop("SAFEPLANE_GIT_TOKEN", None)
        if askpass_path is not None:
            askpass_path.unlink(missing_ok=True)
        if git_config_path is not None:
            git_config_path.unlink(missing_ok=True)


def _run_git(
    args: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    secrets: list[str],
) -> str:
    command = ["git", "-c", "credential.helper=", *args]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepositoryCloneError("git is not installed in the harness runtime") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryCloneError("git operation timed out") from exc

    if completed.returncode != 0:
        stderr = _sanitize_text(completed.stderr.strip(), secrets)
        stdout = _sanitize_text(completed.stdout.strip(), secrets)
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise RepositoryCloneError(f"git operation failed: {detail[:2000]}")
    return _sanitize_text(completed.stdout.strip(), secrets)


def clone_repository(
    *,
    location: GitLocation,
    ref: str,
    destination: Path,
    run_tmp_dir: Path,
    credential: GitCredentialProfile | None,
) -> dict[str, Any]:
    if destination.exists():
        raise RepositoryCloneError(f"repository destination already exists: {destination}")
    ref = validate_git_ref(ref)
    destination.parent.mkdir(parents=True, exist_ok=True)

    trusted_local_repository = (
        Path(location.local_path)
        if location.scheme == "file" and location.local_path is not None
        else None
    )
    with git_auth_environment(
        run_tmp_dir=run_tmp_dir,
        credential=credential,
        trusted_local_repository=trusted_local_repository,
    ) as (env, secrets):
        try:
            _run_git(
                [
                    "clone",
                    "--no-tags",
                    "--quiet",
                    "--no-checkout",
                    "--",
                    location.sanitized_url,
                    str(destination),
                ],
                cwd=None,
                env=env,
                secrets=secrets,
            )
            _run_git(
                ["fetch", "--quiet", "--no-tags", "origin", ref],
                cwd=destination,
                env=env,
                secrets=secrets,
            )
            commit = _run_git(
                ["rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                cwd=destination,
                env=env,
                secrets=secrets,
            )
            _run_git(
                ["switch", "--quiet", "--detach", commit],
                cwd=destination,
                env=env,
                secrets=secrets,
            )
            checked_out_commit = _run_git(
                ["rev-parse", "HEAD"],
                cwd=destination,
                env=env,
                secrets=secrets,
            )
            if checked_out_commit.lower() != commit.lower():
                raise RepositoryCloneError(
                    "checked-out commit does not match the resolved repository ref"
                )
            remote_url = _run_git(
                ["remote", "get-url", "origin"],
                cwd=destination,
                env=env,
                secrets=secrets,
            )
            if remote_url != location.sanitized_url:
                _run_git(
                    ["remote", "set-url", "origin", location.sanitized_url],
                    cwd=destination,
                    env=env,
                    secrets=secrets,
                )
                remote_url = location.sanitized_url
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        shutil.rmtree(destination, ignore_errors=True)
        raise RepositoryCloneError("git returned an invalid commit id")

    return {
        "commit": commit.lower(),
        "remote_url": remote_url,
    }


def _resolve_external_url(profile: ExternalSourceProfile) -> str:
    if profile.repository_url_env:
        override = os.environ.get(profile.repository_url_env)
        if override:
            return override
    return profile.repository_url


def authorize_external_source(
    workspace_manifest: dict[str, Any],
    *,
    source_id: str,
    agent_id: str,
) -> dict[str, Any]:
    sources = workspace_manifest.get("external_sources") or {}
    source = sources.get(source_id)
    if not isinstance(source, dict):
        raise RepositoryProfileError(f"external source is not prepared for this run: {source_id}")
    allowed_agents = set(source.get("allowed_agents") or [])
    if agent_id not in allowed_agents:
        raise RepositoryProfileError(
            f"agent {agent_id!r} is not allowed to access external source {source_id!r}"
        )
    return source


def prepare_repository_workspace(
    *,
    contract: dict[str, Any],
    safeplane_home: Path,
    run_id: str,
    repository_profile_id: str,
) -> dict[str, Any]:
    _safe_identifier(run_id, "run id")
    _safe_identifier(repository_profile_id, "repository profile id")

    profile_config_path = repository_profiles_path(contract)
    config = load_repository_profiles(profile_config_path)
    profile = config.repository_profiles.get(repository_profile_id)
    if profile is None:
        raise RepositoryProfileError(f"unknown repository profile: {repository_profile_id}")
    if not profile.enabled:
        raise RepositoryProfileError(f"repository profile is disabled: {repository_profile_id}")

    credential: GitCredentialProfile | None = None
    if profile.credential_profile:
        credential = config.credential_profiles.get(profile.credential_profile)
        if credential is None:
            raise RepositoryProfileError(
                f"repository profile references unknown credential profile: {profile.credential_profile}"
            )

    target_location = parse_git_location(
        profile.repository_url,
        allowed_hosts=profile.allowed_hosts,
        allowed_repository=profile.allowed_repository,
        allow_file_url=profile.allow_file_url,
    )

    run_dir = safeplane_home / "workspaces" / run_id
    target_dir = run_dir / "repo"
    skills_dir = run_dir / "repos" / "skills"
    tmp_dir = run_dir / "tmp"
    if run_dir.exists():
        manifest_path = run_dir / "workspace.json"
        if not manifest_path.is_file():
            raise RepositoryWorkspaceError(
                f"Developer workspace exists without a manifest for run: {run_id}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_profile = str((manifest.get("target") or {}).get("profile_id") or "")
        if existing_profile != repository_profile_id:
            raise RepositoryWorkspaceError(
                "Existing developer workspace repository profile does not match the run"
            )
        if manifest.get("workspace_kind") != "git_multi_repository":
            raise RepositoryWorkspaceError("Existing developer workspace has the wrong kind")
        return {
            **manifest,
            "manifest_ref": str(manifest_path.relative_to(safeplane_home)),
            "resumed": True,
        }
    run_dir.mkdir(parents=True, exist_ok=False)

    try:
        target_clone = clone_repository(
            location=target_location,
            ref=profile.ref,
            destination=target_dir,
            run_tmp_dir=tmp_dir,
            credential=credential,
        )

        prepared_sources: dict[str, dict[str, Any]] = {}
        for source_id, source_profile in external_source_profiles(contract).items():
            source_url = _resolve_external_url(source_profile)
            allow_local = source_profile.allow_file_url_for_tests and _local_fixture_urls_enabled()
            source_location = parse_git_location(
                source_url,
                allowed_hosts=source_profile.allowed_hosts,
                allowed_repository=source_profile.allowed_repository,
                allow_file_url=allow_local,
            )
            source_dir = skills_dir / source_profile.checkout_name
            source_clone = clone_repository(
                location=source_location,
                ref=source_profile.ref,
                destination=source_dir,
                run_tmp_dir=tmp_dir,
                credential=None,
            )
            required_path = (source_dir / source_profile.required_path).resolve(strict=False)
            source_root = source_dir.resolve(strict=True)
            try:
                required_path.relative_to(source_root)
            except ValueError as exc:
                raise RepositoryProfileError(
                    f"external source required path escapes checkout: {source_profile.required_path}"
                ) from exc
            if not required_path.exists():
                raise RepositoryProfileError(
                    f"external source {source_id!r} is missing required path: "
                    f"{source_profile.required_path}"
                )
            prepared_sources[source_id] = {
                "source_id": source_id,
                "repository_url": source_location.sanitized_url,
                "repository_root": str(source_dir),
                "checkout_name": source_profile.checkout_name,
                "required_path": source_profile.required_path,
                "required_path_root": str(required_path),
                "resolved_commit": source_clone["commit"],
                "requested_ref": source_profile.ref,
                "read_only": True,
                "allowed_agents": source_profile.allowed_agents,
            }
            _make_tree_read_only(source_dir)

        _make_tree_read_only(target_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        try:
            profile_config_ref = str(profile_config_path.resolve().relative_to(safeplane_home.resolve()))
        except ValueError:
            profile_config_ref = profile_config_path.name

        manifest = {
            "version": 2,
            "run_id": run_id,
            "created_at": utc_now(),
            "workspace_kind": "git_multi_repository",
            "repository_root": str(target_dir),
            "container_logical_root": "/workspace",
            "read_only": True,
            "target": {
                "profile_id": repository_profile_id,
                "repository_url": target_location.sanitized_url,
                "repository_host": target_location.host,
                "repository_name": target_location.repository_name,
                "repository_root": str(target_dir),
                "requested_ref": profile.ref,
                "resolved_commit": target_clone["commit"],
                "credential_profile": profile.credential_profile,
                "remote_write_allowed": profile.remote_write_allowed,
                "draft_pr_creation": profile.draft_pr_creation,
                "branch_prefix": profile.branch_prefix,
                "pull_request_repository": (
                    profile.pull_request_repository or profile.allowed_repository
                ),
                "git_author_name": profile.git_author_name,
                "git_author_email": profile.git_author_email,
            },
            "external_sources": prepared_sources,
            "profile_config_ref": profile_config_ref,
        }
        manifest_path = run_dir / "workspace.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            **manifest,
            "manifest_ref": str(manifest_path.relative_to(safeplane_home)),
        }
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
