from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from harness.patch_approval_store import make_tree_removable, make_tree_writable
from harness.repository_workspace import (
    GitCredentialProfile,
    RepositoryProfile,
    RepositoryWorkspaceError,
    git_auth_environment,
    load_repository_profiles,
    parse_git_location,
    repository_profiles_path,
)
from harness.run_store import load_run, update_run


REMOTE_APPROVAL_ID_PATTERN = re.compile(r"remote_approval_[0-9a-f]{24}")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")


class RemoteWriteError(RuntimeError):
    pass


class RemoteWriteConflictError(RemoteWriteError):
    pass


class RemoteWritePolicyError(RemoteWriteError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteApprovalRequest(StrictModel):
    version: Literal[1] = 1
    run_id: str
    repository_profile: str
    repository_url: str
    repository_name: str
    credential_profile: str
    draft_pr_creation: Literal["approval_required", "automatic"] = "approval_required"
    git_author_name: str
    git_author_email: str
    base_ref: str
    base_commit: str
    workspace_tree_sha256: str
    workspace_file_count: int = Field(ge=0)
    pr_proposal_sha256: str
    implementation_plan_sha256: str
    checks_sha256: str
    review_sha256: str
    branch_name: str
    commit_message: str
    created_at: str


class RemoteWriteResult(StrictModel):
    approval_id: str
    run_id: str
    status: Literal["completed"] = "completed"
    branch_name: str
    commit_sha: str
    pull_request_number: int = Field(ge=1)
    pull_request_url: str
    draft: Literal[True] = True
    branch_reused: bool
    pull_request_reused: bool
    approval_ref: str
    evidence_ref: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"run_[A-Za-z0-9._-]+", run_id):
        raise RemoteWriteError(f"invalid run id: {run_id}")
    return run_id


def _validate_branch_name(branch_name: str) -> str:
    if (
        not branch_name
        or branch_name.startswith("-")
        or branch_name.startswith("/")
        or branch_name.endswith("/")
        or branch_name.endswith(".")
        or ".." in branch_name
        or "//" in branch_name
        or "@{" in branch_name
        or any(char.isspace() or ord(char) < 32 for char in branch_name)
        or any(char in branch_name for char in "~^:?*[\\")
    ):
        raise RemoteWritePolicyError(f"invalid remote branch name: {branch_name!r}")
    return branch_name


def deterministic_branch_name(branch_prefix: str, run_id: str) -> str:
    suffix = run_id.removeprefix("run_").replace("_", "-")
    branch = f"{branch_prefix}{suffix}"
    if len(branch) > 240:
        branch = f"{branch_prefix}{hashlib.sha256(run_id.encode()).hexdigest()[:24]}"
    return _validate_branch_name(branch)


def hash_workspace_tree(repository_root: Path) -> tuple[str, int]:
    try:
        root = repository_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RemoteWriteError(f"target repository is missing: {repository_root}") from exc
    if not root.is_dir():
        raise RemoteWriteError(f"target repository is not a directory: {repository_root}")

    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if path.is_symlink():
            raise RemoteWritePolicyError(
                f"remote approval does not support symlinks in the target tree: {relative.as_posix()}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise RemoteWritePolicyError(
                f"unsupported target tree entry: {relative.as_posix()}"
            )
        mode = path.stat().st_mode
        executable = bool(mode & stat.S_IXUSR)
        content_digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                content_digest.update(chunk)
        record = {
            "path": relative.as_posix(),
            "executable": executable,
            "size": size,
            "sha256": content_digest.hexdigest(),
        }
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        file_count += 1
    return digest.hexdigest(), file_count


def remote_approval_request_path(safeplane_home: Path, run_id: str) -> Path:
    _validate_run_id(run_id)
    return safeplane_home / "workspaces" / run_id / "pipeline" / "remote-approval-request.json"


def load_remote_approval_request(safeplane_home: Path, run_id: str) -> RemoteApprovalRequest:
    path = remote_approval_request_path(safeplane_home, run_id)
    if not path.is_file():
        raise RemoteWriteError(f"remote approval request is missing for run: {run_id}")
    try:
        return RemoteApprovalRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RemoteWriteError(f"remote approval request is invalid for run: {run_id}: {exc}") from exc


def build_remote_approval_request(
    *,
    safeplane_home: Path,
    run_id: str,
    workspace_manifest: dict[str, Any],
    pr_proposal: dict[str, Any],
    implementation_plan: dict[str, Any],
    check_result: dict[str, Any],
    review_result: dict[str, Any],
    created_at: str,
) -> RemoteApprovalRequest:
    target = workspace_manifest.get("target") or {}
    profile_id = str(target.get("profile_id") or "")
    repository_url = str(target.get("repository_url") or "")
    repository_name = str(target.get("pull_request_repository") or target.get("repository_name") or "")
    base_ref = str(target.get("requested_ref") or "")
    base_commit = str(target.get("resolved_commit") or "").lower()
    branch_prefix = str(target.get("branch_prefix") or "safeplane/")
    credential_profile = str(target.get("credential_profile") or "")
    draft_pr_creation = str(target.get("draft_pr_creation") or "approval_required")
    git_author_name = str(target.get("git_author_name") or "")
    git_author_email = str(target.get("git_author_email") or "")
    repository_root = Path(str(workspace_manifest.get("repository_root") or ""))

    if (
        not profile_id
        or not repository_url
        or not repository_name
        or not credential_profile
        or not git_author_name
        or not git_author_email
        or not base_ref
    ):
        raise RemoteWriteError("repository workspace is missing remote-approval metadata")
    if not GIT_COMMIT_PATTERN.fullmatch(base_commit):
        raise RemoteWriteError("repository workspace has an invalid base commit")

    workspace_sha256, file_count = hash_workspace_tree(repository_root)
    request = RemoteApprovalRequest(
        run_id=run_id,
        repository_profile=profile_id,
        repository_url=repository_url,
        repository_name=repository_name,
        credential_profile=credential_profile,
        draft_pr_creation=draft_pr_creation,
        git_author_name=git_author_name,
        git_author_email=git_author_email,
        base_ref=base_ref,
        base_commit=base_commit,
        workspace_tree_sha256=workspace_sha256,
        workspace_file_count=file_count,
        pr_proposal_sha256=canonical_json_sha256(pr_proposal),
        implementation_plan_sha256=canonical_json_sha256(implementation_plan),
        checks_sha256=canonical_json_sha256(check_result),
        review_sha256=canonical_json_sha256(review_result),
        branch_name=deterministic_branch_name(branch_prefix, run_id),
        commit_message=str(implementation_plan.get("commit_message") or "").strip(),
        created_at=created_at,
    )
    if not request.commit_message:
        raise RemoteWriteError("implementation plan is missing a commit message")
    return request


def save_remote_approval_request(safeplane_home: Path, request: RemoteApprovalRequest) -> str:
    path = remote_approval_request_path(safeplane_home, request.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = load_remote_approval_request(safeplane_home, request.run_id)
        if existing.model_dump(mode="json") != request.model_dump(mode="json"):
            raise RemoteWriteConflictError("remote approval request already exists with different contents")
    else:
        path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return str(path.relative_to(safeplane_home))


def _remote_approval_binding(request: RemoteApprovalRequest) -> str:
    return canonical_json_sha256(request.model_dump(mode="json"))


def remote_approval_id(request: RemoteApprovalRequest) -> str:
    return f"remote_approval_{_remote_approval_binding(request)[:24]}"


def remote_approvals_dir(safeplane_home: Path, run_id: str) -> Path:
    _validate_run_id(run_id)
    path = safeplane_home / "workspaces" / run_id / "remote-approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def remote_approval_path(safeplane_home: Path, run_id: str, approval_id: str) -> Path:
    if not REMOTE_APPROVAL_ID_PATTERN.fullmatch(approval_id):
        raise RemoteWriteError(f"invalid remote approval id: {approval_id}")
    return remote_approvals_dir(safeplane_home, run_id) / f"{approval_id}.json"


def _save_remote_approval(safeplane_home: Path, record: dict[str, Any]) -> None:
    path = remote_approval_path(
        safeplane_home,
        str(record["run_id"]),
        str(record["approval_id"]),
    )
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_remote_approval(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> dict[str, Any]:
    path = remote_approval_path(safeplane_home, run_id, approval_id)
    if not path.is_file():
        raise RemoteWriteError(f"remote approval record not found: {approval_id}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RemoteWriteError(f"remote approval record is invalid: {approval_id}") from exc


def create_or_load_remote_approval(
    safeplane_home: Path,
    *,
    request: RemoteApprovalRequest,
    connector: Literal["cli", "telegram"],
    authorization_source: Literal["operator_approval", "repository_policy"],
) -> dict[str, Any]:
    approval_id = remote_approval_id(request)
    path = remote_approval_path(safeplane_home, request.run_id, approval_id)
    binding = _remote_approval_binding(request)
    if path.exists():
        existing = load_remote_approval(
            safeplane_home,
            run_id=request.run_id,
            approval_id=approval_id,
        )
        if existing.get("binding_sha256") != binding:
            raise RemoteWriteConflictError("remote approval binding does not match the stored record")
        return existing

    now = utc_now()
    record = {
        "version": 1,
        "approval_id": approval_id,
        "run_id": request.run_id,
        "binding_sha256": binding,
        "request": request.model_dump(mode="json"),
        "connector": connector,
        "authorization_source": authorization_source,
        "status": "approved",
        "approved_at": now,
        "updated_at": now,
        "attempt_count": 0,
        "branch_name": request.branch_name,
        "commit_sha": None,
        "pull_request": None,
        "evidence_ref": None,
        "error": None,
    }
    _save_remote_approval(safeplane_home, record)
    return record


def update_remote_approval(
    safeplane_home: Path,
    record: dict[str, Any],
    **updates: Any,
) -> dict[str, Any]:
    updated = {**record, **updates, "updated_at": utc_now()}
    _save_remote_approval(safeplane_home, updated)
    return updated


def _sanitize_text(value: str, secrets: list[str]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    secrets: list[str],
    allow_exit_codes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-c", "credential.helper=", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    allowed = allow_exit_codes or {0}
    if completed.returncode not in allowed:
        detail = _sanitize_text(
            completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}",
            secrets,
        )
        raise RemoteWriteError(f"git remote-write operation failed: {detail[:2000]}")
    completed.stdout = _sanitize_text(completed.stdout, secrets)
    completed.stderr = _sanitize_text(completed.stderr, secrets)
    return completed


def _remote_ref_commit(
    *,
    repository: Path,
    ref: str,
    env: dict[str, str],
    secrets: list[str],
) -> str | None:
    completed = _run_git(
        ["ls-remote", "--exit-code", "origin", ref],
        cwd=repository,
        env=env,
        secrets=secrets,
        allow_exit_codes={0, 2},
    )
    if completed.returncode == 2 or not completed.stdout.strip():
        return None
    first = completed.stdout.strip().splitlines()[0].split()[0].lower()
    if not GIT_COMMIT_PATTERN.fullmatch(first):
        raise RemoteWriteError(f"remote returned an invalid commit for {ref}")
    return first


def _remote_write_dir(safeplane_home: Path, run_id: str, approval_id: str) -> Path:
    return safeplane_home / "workspaces" / run_id / "remote-write" / approval_id


def _prepare_remote_write_repository(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
) -> Path:
    source = safeplane_home / "workspaces" / run_id / "repo"
    root = _remote_write_dir(safeplane_home, run_id, approval_id)
    staged = root / "repo"
    if root.exists():
        make_tree_removable(root)
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(source, staged, symlinks=True)
        make_tree_writable(staged, uid=os.geteuid(), gid=os.getegid())
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return staged


def _cleanup_remote_write_repository(safeplane_home: Path, run_id: str, approval_id: str) -> None:
    root = _remote_write_dir(safeplane_home, run_id, approval_id)
    if root.exists():
        make_tree_removable(root)
        shutil.rmtree(root, ignore_errors=True)


def _load_profile_and_credential(
    *,
    contract: dict[str, Any],
    profile_id: str,
) -> tuple[RepositoryProfile, GitCredentialProfile]:
    try:
        config = load_repository_profiles(repository_profiles_path(contract))
    except RepositoryWorkspaceError as exc:
        raise RemoteWritePolicyError(str(exc)) from exc
    profile = config.repository_profiles.get(profile_id)
    if profile is None or not profile.enabled:
        raise RemoteWritePolicyError(f"repository profile is unavailable: {profile_id}")
    if not profile.remote_write_allowed:
        raise RemoteWritePolicyError(
            f"remote write is disabled for repository profile: {profile_id}"
        )
    if not profile.credential_profile:
        raise RemoteWritePolicyError(
            f"remote-write repository profile requires a credential profile: {profile_id}"
        )
    credential = config.credential_profiles.get(profile.credential_profile)
    if credential is None:
        raise RemoteWritePolicyError(
            f"repository profile references an unavailable credential profile: {profile.credential_profile}"
        )
    return profile, credential


def _validate_profile_matches_request(
    profile: RepositoryProfile,
    request: RemoteApprovalRequest,
) -> None:
    try:
        location = parse_git_location(
            profile.repository_url,
            allowed_hosts=profile.allowed_hosts,
            allowed_repository=profile.allowed_repository,
            allow_file_url=profile.allow_file_url,
        )
    except RepositoryWorkspaceError as exc:
        raise RemoteWritePolicyError(str(exc)) from exc
    repository_name = profile.pull_request_repository or profile.allowed_repository
    if location.sanitized_url != request.repository_url:
        raise RemoteWriteConflictError("repository profile URL changed after the developer run")
    if profile.ref != request.base_ref:
        raise RemoteWriteConflictError("repository profile base ref changed after the developer run")
    if repository_name != request.repository_name:
        raise RemoteWriteConflictError("pull-request repository changed after the developer run")
    if profile.credential_profile != request.credential_profile:
        raise RemoteWriteConflictError("credential profile changed after the developer run")
    if profile.draft_pr_creation != request.draft_pr_creation:
        raise RemoteWriteConflictError("draft-PR creation policy changed after the developer run")
    if profile.git_author_name != request.git_author_name:
        raise RemoteWriteConflictError("Git author name changed after the developer run")
    if profile.git_author_email != request.git_author_email:
        raise RemoteWriteConflictError("Git author email changed after the developer run")
    expected_branch = deterministic_branch_name(profile.branch_prefix, request.run_id)
    if expected_branch != request.branch_name:
        raise RemoteWriteConflictError("branch policy changed after the developer run")


def _github_api_base_url() -> str:
    raw = os.environ.get("SAFEPLANE_GITHUB_API_URL", "https://api.github.com").rstrip("/")
    parsed = urllib.parse.urlsplit(raw)
    if (
        parsed.scheme == "https"
        and parsed.hostname == "api.github.com"
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    ):
        return "https://api.github.com"
    local_allowed = os.environ.get("SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES", "no").lower() in {
        "1",
        "true",
        "yes",
    }
    if (
        local_allowed
        and parsed.scheme == "http"
        and (parsed.hostname or "") in {"127.0.0.1", "localhost", "github-mock"}
    ):
        return raw
    raise RemoteWritePolicyError(
        "GitHub API URL must be https://api.github.com outside explicit local fixtures"
    )


class GitHubPullRequestClient:
    def __init__(self, *, token: str, repository: str) -> None:
        if not token:
            raise RemoteWritePolicyError("GitHub token is empty")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise RemoteWritePolicyError(f"invalid GitHub repository name: {repository}")
        self.token = token
        self.repository = repository
        self.api_base = _github_api_base_url()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.api_base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "safeplane-harness",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace").replace(self.token, "[REDACTED]")
            raise RemoteWriteError(f"GitHub API request failed with HTTP {exc.code}: {body[:2000]}") from exc
        except urllib.error.URLError as exc:
            raise RemoteWriteError(f"GitHub API request failed: {exc.reason}") from exc
        try:
            return json.loads(body) if body else None
        except json.JSONDecodeError as exc:
            raise RemoteWriteError("GitHub API returned invalid JSON") from exc

    def find_open_pull_request(self, *, branch_name: str, base_ref: str) -> dict[str, Any] | None:
        owner = self.repository.split("/", 1)[0]
        result = self._request(
            "GET",
            f"/repos/{self.repository}/pulls",
            query={
                "state": "open",
                "head": f"{owner}:{branch_name}",
                "base": base_ref,
            },
        )
        if not isinstance(result, list):
            raise RemoteWriteError("GitHub pull-request search returned an invalid response")
        for item in result:
            if isinstance(item, dict):
                return item
        return None

    def create_draft_pull_request(
        self,
        *,
        title: str,
        body: str,
        branch_name: str,
        base_ref: str,
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            f"/repos/{self.repository}/pulls",
            payload={
                "title": title,
                "body": body,
                "head": branch_name,
                "base": base_ref,
                "draft": True,
            },
        )
        if not isinstance(result, dict):
            raise RemoteWriteError("GitHub pull-request creation returned an invalid response")
        return result


def compose_pull_request_body(
    *,
    proposal_body: str,
    request: RemoteApprovalRequest,
    run: dict[str, Any],
    pipeline: dict[str, Any],
    plan: dict[str, Any],
) -> str:
    changed_paths = [
        *[str(item) for item in plan.get("files_to_modify") or []],
        *[str(item) for item in plan.get("files_to_create") or []],
        *[str(item) for item in plan.get("files_to_delete") or []],
    ]
    commands = [
        " ".join(str(part) for part in argv)
        for argv in plan.get("test_commands") or []
        if isinstance(argv, list)
    ]
    model_lines: list[str] = []
    for item in pipeline.get("agent_runs") or []:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage_id") or "unknown")
        provider = str(item.get("actual_provider") or "unknown")
        model = str(item.get("actual_model") or item.get("configured_model") or "unknown")
        model_lines.append(f"- `{stage}`: `{provider}` / `{model}`")

    sections = [proposal_body.rstrip(), "", "## Safeplane evidence", ""]
    sections.extend(
        [
            f"- Run: `{request.run_id}`",
            f"- Base: `{request.base_ref}` at `{request.base_commit}`",
            f"- Approved workspace: `{request.workspace_tree_sha256}`",
            f"- Review verdict: `{pipeline.get('review_verdict')}`",
            f"- Controlled checks: `{(pipeline.get('check_summary') or {}).get('status')}`",
            f"- Documentation impact: {plan.get('documentation_impact') or 'not stated'}",
        ]
    )
    if changed_paths:
        sections.extend(["", "### Changed paths", ""])
        sections.extend(f"- `{path}`" for path in changed_paths)
    if commands:
        sections.extend(["", "### Declared checks", ""])
        sections.extend(f"- `{command}`" for command in commands)
    risks = [str(item) for item in plan.get("risks") or []]
    if risks:
        sections.extend(["", "### Known risks", ""])
        sections.extend(f"- {risk}" for risk in risks)
    if model_lines:
        sections.extend(["", "### Model execution", ""])
        sections.extend(model_lines)
    sections.extend(
        [
            "",
            "Safeplane created this as a **draft** after explicit operator approval. ",
            "Human inspection is required. Safeplane does not merge pull requests.",
        ]
    )
    return "\n".join(sections).rstrip() + "\n"


def _normalize_pull_request(data: dict[str, Any]) -> dict[str, Any]:
    number = data.get("number")
    url = data.get("html_url")
    draft = data.get("draft")
    if not isinstance(number, int) or number < 1:
        raise RemoteWriteError("pull-request response is missing a valid number")
    if not isinstance(url, str) or not url:
        raise RemoteWriteError("pull-request response is missing a URL")
    if draft is not True:
        raise RemoteWritePolicyError("Safeplane only accepts a draft pull request")
    return {"number": number, "url": url, "draft": True}


def _load_json_artifact(safeplane_home: Path, ref: str, *, expected_run_id: str) -> dict[str, Any]:
    prefix = f"workspaces/{expected_run_id}/pipeline/"
    if not ref.startswith(prefix):
        raise RemoteWriteError("pipeline artifact reference escapes the run workspace")
    path = (safeplane_home / ref).resolve(strict=True)
    root = (safeplane_home / "workspaces" / expected_run_id / "pipeline").resolve(strict=True)
    if path.parent != root:
        raise RemoteWriteError("pipeline artifact path escapes the pipeline directory")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RemoteWriteError(f"pipeline artifact is invalid JSON: {ref}") from exc
    if not isinstance(raw, dict):
        raise RemoteWriteError(f"pipeline artifact must be an object: {ref}")
    return raw


def _approval_evidence_path(safeplane_home: Path, run_id: str, approval_id: str) -> Path:
    return remote_approvals_dir(safeplane_home, run_id) / f"{approval_id}.evidence.json"


def _write_evidence(
    safeplane_home: Path,
    *,
    run_id: str,
    approval_id: str,
    content: dict[str, Any],
) -> str:
    path = _approval_evidence_path(safeplane_home, run_id, approval_id)
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(path.relative_to(safeplane_home))


def _mark_pipeline_remote_write_completed(
    safeplane_home: Path,
    *,
    run_id: str,
    result: RemoteWriteResult,
) -> None:
    state_path = safeplane_home / "workspaces" / run_id / "pipeline" / "pipeline.json"
    if not state_path.is_file():
        raise RemoteWriteError("developer pipeline state is missing")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("current_state") not in {"waiting_for_remote_approval", "completed"}:
        raise RemoteWriteConflictError(
            f"developer pipeline cannot complete remote write from state {state.get('current_state')}"
        )
    completed_stages = list(state.get("completed_stages") or [])
    if "remote_write" not in completed_stages:
        completed_stages.append("remote_write")
    state["current_state"] = "completed"
    state["completed_stages"] = completed_stages
    artifacts = dict(state.get("artifacts") or {})
    artifacts["remote-write.json"] = result.evidence_ref
    state["artifacts"] = artifacts
    state["updated_at"] = utc_now()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run = load_run(safeplane_home, run_id)
    summary = dict(run.get("developer_pipeline") or {})
    summary.update(
        {
            "current_state": "completed",
            "completed_stages": completed_stages,
            "remote_approval_possible": False,
            "remote_write": result.model_dump(mode="json"),
            "pull_request_url": result.pull_request_url,
        }
    )
    update_run(
        safeplane_home,
        run_id,
        developer_pipeline=summary,
        remote_write=result.model_dump(mode="json"),
        final_message=(
            f"Draft pull request created: {result.pull_request_url}. "
            "Safeplane did not merge it. Human inspection is required."
        ),
    )


def execute_remote_write(
    *,
    safeplane_home: Path,
    contract: dict[str, Any],
    run_id: str,
    connector: Literal["cli", "telegram"],
    authorization_source: Literal["operator_approval", "repository_policy"] = "operator_approval",
) -> RemoteWriteResult:
    run = load_run(safeplane_home, run_id)
    if run.get("workflow_id") != "developer" or run.get("entrypoint") != "develop":
        raise RemoteWritePolicyError("remote approval is only available for develop workflow runs")
    allowed_statuses = {"completed"}
    if authorization_source == "repository_policy":
        allowed_statuses.add("running")
    if run.get("status") not in allowed_statuses:
        raise RemoteWriteConflictError(
            f"developer run status does not allow remote write: {run.get('status')}"
        )
    pipeline = run.get("developer_pipeline") or {}
    if pipeline.get("current_state") == "completed" and run.get("remote_write"):
        return RemoteWriteResult.model_validate(run["remote_write"])
    if pipeline.get("current_state") != "waiting_for_remote_approval":
        raise RemoteWriteConflictError(
            f"developer pipeline is not waiting for remote approval: {pipeline.get('current_state')}"
        )
    if (pipeline.get("check_summary") or {}).get("status") != "passed":
        raise RemoteWritePolicyError("remote write requires passing controlled checks")
    if pipeline.get("review_verdict") != "LGTM":
        raise RemoteWritePolicyError("remote write requires an LGTM review verdict")

    request = load_remote_approval_request(safeplane_home, run_id)
    if authorization_source == "repository_policy" and request.draft_pr_creation != "automatic":
        raise RemoteWritePolicyError("repository policy does not authorize automatic draft-PR creation")
    profile, credential = _load_profile_and_credential(
        contract=contract,
        profile_id=request.repository_profile,
    )
    _validate_profile_matches_request(profile, request)

    current_tree, current_count = hash_workspace_tree(
        safeplane_home / "workspaces" / run_id / "repo"
    )
    if current_tree != request.workspace_tree_sha256 or current_count != request.workspace_file_count:
        raise RemoteWriteConflictError(
            "target workspace changed after remote approval was requested"
        )

    artifacts = pipeline.get("artifacts") or {}
    pr_ref = str(artifacts.get("pr.json") or "")
    plan_ref = str(artifacts.get("planning.json") or "")
    checks_ref = str(artifacts.get("checks.json") or "")
    review_ref = str(artifacts.get("review.json") or "")
    pr_proposal = _load_json_artifact(safeplane_home, pr_ref, expected_run_id=run_id)
    plan = _load_json_artifact(safeplane_home, plan_ref, expected_run_id=run_id)
    check_result = _load_json_artifact(safeplane_home, checks_ref, expected_run_id=run_id)
    review_result = _load_json_artifact(safeplane_home, review_ref, expected_run_id=run_id)
    if canonical_json_sha256(pr_proposal) != request.pr_proposal_sha256:
        raise RemoteWriteConflictError("PR proposal changed after remote approval was requested")
    if canonical_json_sha256(plan) != request.implementation_plan_sha256:
        raise RemoteWriteConflictError("implementation plan changed after remote approval was requested")
    if canonical_json_sha256(check_result) != request.checks_sha256:
        raise RemoteWriteConflictError("check evidence changed after remote approval was requested")
    if canonical_json_sha256(review_result) != request.review_sha256:
        raise RemoteWriteConflictError("review evidence changed after remote approval was requested")
    if check_result.get("status") != "passed":
        raise RemoteWritePolicyError("remote write requires passing immutable check evidence")
    if review_result.get("verdict") != "LGTM":
        raise RemoteWritePolicyError("remote write requires immutable LGTM review evidence")
    if str(plan.get("commit_message") or "").strip() != request.commit_message:
        raise RemoteWriteConflictError("commit message changed after remote approval was requested")
    if pr_proposal.get("draft") is not True:
        raise RemoteWritePolicyError("PR proposal must request a draft pull request")

    approval = create_or_load_remote_approval(
        safeplane_home,
        request=request,
        connector=connector,
        authorization_source=authorization_source,
    )
    if approval.get("status") == "completed" and approval.get("result"):
        completed_result = RemoteWriteResult.model_validate(approval["result"])
        _mark_pipeline_remote_write_completed(
            safeplane_home,
            run_id=run_id,
            result=completed_result,
        )
        return completed_result

    approval_id = str(approval["approval_id"])
    approval = update_remote_approval(
        safeplane_home,
        approval,
        status="processing",
        attempt_count=int(approval.get("attempt_count") or 0) + 1,
        processing_started_at=utc_now(),
        error=None,
    )

    staged: Path | None = None
    try:
        staged = _prepare_remote_write_repository(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
        )
        with git_auth_environment(
            run_tmp_dir=_remote_write_dir(safeplane_home, run_id, approval_id) / "tmp",
            credential=credential,
        ) as (env, secrets):
            head = _run_git(["rev-parse", "HEAD"], cwd=staged, env=env, secrets=secrets).stdout.strip().lower()
            if head != request.base_commit:
                raise RemoteWriteConflictError("target checkout base commit changed after the developer run")
            remote_url = _run_git(
                ["remote", "get-url", "origin"], cwd=staged, env=env, secrets=secrets
            ).stdout.strip()
            if remote_url != request.repository_url:
                raise RemoteWriteConflictError("target checkout remote URL changed after the developer run")

            remote_base = _remote_ref_commit(
                repository=staged,
                ref=f"refs/heads/{request.base_ref}",
                env=env,
                secrets=secrets,
            )
            if remote_base != request.base_commit:
                raise RemoteWriteConflictError(
                    "remote base branch moved after the developer run; start a new developer run"
                )

            _run_git(
                ["config", "user.name", request.git_author_name],
                cwd=staged,
                env=env,
                secrets=secrets,
            )
            _run_git(
                ["config", "user.email", request.git_author_email],
                cwd=staged,
                env=env,
                secrets=secrets,
            )
            _run_git(
                ["switch", "--quiet", "-C", request.branch_name, request.base_commit],
                cwd=staged,
                env=env,
                secrets=secrets,
            )
            _run_git(["add", "--all"], cwd=staged, env=env, secrets=secrets)
            staged_diff = _run_git(
                ["diff", "--cached", "--name-only"], cwd=staged, env=env, secrets=secrets
            ).stdout.strip()
            if not staged_diff:
                raise RemoteWritePolicyError("remote write requires at least one committed target change")
            commit_env = {
                **env,
                "GIT_AUTHOR_DATE": request.created_at,
                "GIT_COMMITTER_DATE": request.created_at,
            }
            _run_git(
                ["commit", "--quiet", "--no-gpg-sign", "-m", request.commit_message],
                cwd=staged,
                env=commit_env,
                secrets=secrets,
            )
            commit_sha = _run_git(
                ["rev-parse", "HEAD"], cwd=staged, env=env, secrets=secrets
            ).stdout.strip().lower()
            if not GIT_COMMIT_PATTERN.fullmatch(commit_sha):
                raise RemoteWriteError("git created an invalid commit id")

            remote_branch_ref = f"refs/heads/{request.branch_name}"
            existing_branch = _remote_ref_commit(
                repository=staged,
                ref=remote_branch_ref,
                env=env,
                secrets=secrets,
            )
            branch_reused = existing_branch == commit_sha
            if existing_branch is not None and existing_branch != commit_sha:
                raise RemoteWriteConflictError(
                    "deterministic Safeplane branch already exists with different content; no force push allowed"
                )
            if existing_branch is None:
                _run_git(
                    ["push", "--porcelain", "origin", f"HEAD:{remote_branch_ref}"],
                    cwd=staged,
                    env=env,
                    secrets=secrets,
                )
            verified_branch = _remote_ref_commit(
                repository=staged,
                ref=remote_branch_ref,
                env=env,
                secrets=secrets,
            )
            if verified_branch != commit_sha:
                raise RemoteWriteError("remote branch verification failed after push")

            token = env.get("SAFEPLANE_GIT_TOKEN", "")
            github = GitHubPullRequestClient(token=token, repository=request.repository_name)
            existing_pr = github.find_open_pull_request(
                branch_name=request.branch_name,
                base_ref=request.base_ref,
            )
            pull_request_reused = existing_pr is not None
            pull_request_body = compose_pull_request_body(
                proposal_body=str(pr_proposal.get("body_markdown") or ""),
                request=request,
                run=run,
                pipeline=pipeline,
                plan=plan,
            )
            pr_data = existing_pr or github.create_draft_pull_request(
                title=str(pr_proposal.get("title") or ""),
                body=pull_request_body,
                branch_name=request.branch_name,
                base_ref=request.base_ref,
            )
            normalized_pr = _normalize_pull_request(pr_data)

        evidence = {
            "version": 1,
            "approval_id": approval_id,
            "run_id": run_id,
            "binding_sha256": approval["binding_sha256"],
            "repository_profile": request.repository_profile,
            "repository_url": request.repository_url,
            "repository_name": request.repository_name,
            "credential_profile": request.credential_profile,
            "git_author_name": request.git_author_name,
            "git_author_email": request.git_author_email,
            "base_ref": request.base_ref,
            "base_commit": request.base_commit,
            "workspace_tree_sha256": request.workspace_tree_sha256,
            "pr_proposal_sha256": request.pr_proposal_sha256,
            "implementation_plan_sha256": request.implementation_plan_sha256,
            "checks_sha256": request.checks_sha256,
            "review_sha256": request.review_sha256,
            "branch_name": request.branch_name,
            "branch_commit": commit_sha,
            "branch_reused": branch_reused,
            "pull_request_number": normalized_pr["number"],
            "pull_request_url": normalized_pr["url"],
            "pull_request_reused": pull_request_reused,
            "pull_request_body_sha256": hashlib.sha256(
                pull_request_body.encode("utf-8")
            ).hexdigest(),
            "draft": True,
            "force_push": False,
            "merge_performed": False,
            "completed_at": utc_now(),
        }
        evidence_ref = _write_evidence(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
            content=evidence,
        )
        result = RemoteWriteResult(
            approval_id=approval_id,
            run_id=run_id,
            branch_name=request.branch_name,
            commit_sha=commit_sha,
            pull_request_number=normalized_pr["number"],
            pull_request_url=normalized_pr["url"],
            draft=True,
            branch_reused=branch_reused,
            pull_request_reused=pull_request_reused,
            approval_ref=str(
                remote_approval_path(safeplane_home, run_id, approval_id).relative_to(safeplane_home)
            ),
            evidence_ref=evidence_ref,
        )
        approval = update_remote_approval(
            safeplane_home,
            approval,
            status="completed",
            completed_at=utc_now(),
            commit_sha=commit_sha,
            pull_request=normalized_pr,
            evidence_ref=evidence_ref,
            result=result.model_dump(mode="json"),
            error=None,
        )
        _mark_pipeline_remote_write_completed(
            safeplane_home,
            run_id=run_id,
            result=result,
        )
        return result
    except RepositoryWorkspaceError as exc:
        translated = RemoteWritePolicyError(str(exc))
        latest = load_remote_approval(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
        )
        if latest.get("status") != "completed":
            update_remote_approval(
                safeplane_home,
                latest,
                status="failed",
                failed_at=utc_now(),
                error={"type": type(translated).__name__, "message": str(translated)},
            )
        raise translated from exc
    except Exception as exc:
        latest = load_remote_approval(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
        )
        if latest.get("status") != "completed":
            update_remote_approval(
                safeplane_home,
                latest,
                status="failed",
                failed_at=utc_now(),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        raise
    finally:
        if staged is not None:
            _cleanup_remote_write_repository(safeplane_home, run_id, approval_id)
