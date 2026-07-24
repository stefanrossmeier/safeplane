from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DevWorkspaceCommandOutput(StrictModel):
    command: list[str]
    cwd: str
    workspace_root: str
    exit_code: int = 0
    truncated: bool = False
    evidence_ref: str | None = None


class DevWorkspaceEntry(StrictModel):
    path: str
    type: str
    size_bytes: int | None = None


class DevWorkspaceReadyInput(StrictModel):
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    expected_files: dict[str, str | None] = Field(default_factory=dict, max_length=200)

    @field_validator("expected_files")
    @classmethod
    def validate_expected_files(cls, values: dict[str, str | None]) -> dict[str, str | None]:
        for path, digest in values.items():
            if not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("expected file paths must stay inside the repository")
            if digest is not None and (
                len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("expected file hashes must be lowercase SHA-256 digests")
        return values


class DevWorkspaceReadyOutput(DevWorkspaceCommandOutput):
    ready: Literal[True]
    workspace_version: int
    target_commit: str
    external_source_commits: dict[str, str]


class DevWorkspaceListInput(StrictModel):
    path: str = "."
    max_depth: int = Field(default=2, ge=0, le=8)
    max_entries: int = Field(default=200, ge=1, le=2000)


class DevWorkspaceListOutput(DevWorkspaceCommandOutput):
    entries: list[DevWorkspaceEntry]


class DevWorkspaceFindInput(StrictModel):
    pattern: str
    path: str = "."
    max_results: int = Field(default=100, ge=1, le=1000)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pattern must not be empty")
        return value


class DevWorkspaceFindOutput(DevWorkspaceCommandOutput):
    matches: list[str]


class DevWorkspaceGrepMatch(StrictModel):
    path: str
    line_number: int
    line: str


class DevWorkspaceGrepInput(StrictModel):
    query: str
    path: str = "."
    file_glob: str = "*"
    case_sensitive: bool = False
    max_results: int = Field(default=100, ge=1, le=1000)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value:
            raise ValueError("query must not be empty")
        return value


class DevWorkspaceGrepOutput(DevWorkspaceCommandOutput):
    matches: list[DevWorkspaceGrepMatch]


class DevWorkspaceReadInput(StrictModel):
    path: str
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=200, ge=1, le=2000)
    max_bytes: int = Field(default=65536, ge=1, le=1048576)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value


class DevWorkspaceReadOutput(DevWorkspaceCommandOutput):
    path: str
    start_line: int
    end_line: int
    next_start_line: int | None = None
    content: str


class DevGitMetadataInput(StrictModel):
    include_remote: bool = True


class DevGitMetadataOutput(DevWorkspaceCommandOutput):
    head_commit: str
    detached: bool
    branch: str | None
    remote_url: str | None
    requested_ref: str | None
    resolved_base_commit: str | None


class DevGitStatusInput(StrictModel):
    include_untracked: bool = True


class DevGitStatusEntry(StrictModel):
    path: str
    index_status: str
    worktree_status: str


class DevGitStatusOutput(DevWorkspaceCommandOutput):
    clean: bool
    entries: list[DevGitStatusEntry]


class DevGitDiffInput(StrictModel):
    paths: list[str] = Field(default_factory=list, max_length=50)
    staged: bool = False
    context_lines: int = Field(default=3, ge=0, le=20)
    max_bytes: int = Field(default=262144, ge=1, le=1048576)


class DevGitDiffOutput(DevWorkspaceCommandOutput):
    diff: str
    paths: list[str]


class DevGitLogInput(StrictModel):
    max_commits: int = Field(default=20, ge=1, le=100)
    path: str | None = None


class DevGitCommit(StrictModel):
    commit: str
    author_name: str
    authored_at: str
    subject: str


class DevGitLogOutput(DevWorkspaceCommandOutput):
    commits: list[DevGitCommit]


class DevGitShowInput(StrictModel):
    ref: str = "HEAD"
    path: str | None = None
    max_bytes: int = Field(default=262144, ge=1, le=1048576)

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        if not value or value.startswith("-") or any(char.isspace() for char in value):
            raise ValueError("ref is invalid")
        return value


class DevGitShowOutput(DevWorkspaceCommandOutput):
    requested_ref: str
    resolved_commit: str
    content: str


class DevGitTrackedFilesInput(StrictModel):
    path: str = "."
    start_after: str | None = None
    max_results: int = Field(default=1000, ge=1, le=10000)

    @field_validator("start_after")
    @classmethod
    def validate_start_after(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value
            or len(value) > 4096
            or "\x00" in value
            or "\n" in value
            or "\r" in value
        ):
            raise ValueError("start_after is invalid")
        return value


class DevGitTrackedFilesOutput(DevWorkspaceCommandOutput):
    files: list[str]
    next_start_after: str | None = None


class DevExternalSkillListInput(StrictModel):
    source_id: str = "archdoc"
    path: str = "."
    max_depth: int = Field(default=3, ge=0, le=8)
    max_entries: int = Field(default=200, ge=1, le=2000)


class DevExternalSkillListOutput(DevWorkspaceCommandOutput):
    source_id: str
    source_commit: str
    entries: list[DevWorkspaceEntry]


class DevExternalSkillReadInput(StrictModel):
    source_id: str = "archdoc"
    path: str
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=300, ge=1, le=2000)
    max_bytes: int = Field(default=131072, ge=1, le=1048576)


class DevExternalSkillReadOutput(DevWorkspaceCommandOutput):
    source_id: str
    source_commit: str
    path: str
    start_line: int
    end_line: int
    next_start_line: int | None = None
    content: str


class DevCheckRunInput(StrictModel):
    profile_id: str
    arguments: list[str] = Field(default_factory=list, max_length=16)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    expected_files: dict[str, str | None] = Field(default_factory=dict, max_length=200)
    candidate_patch: str | None = Field(default=None, max_length=2_000_000)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("profile_id contains unsafe characters")
        return value

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, values: list[str]) -> list[str]:
        forbidden = ("|", "||", "&&", ">", ">>", "<", ";", "$(", "`", "\n", "\r", "\x00")
        for value in values:
            if not value or len(value) > 512:
                raise ValueError("command arguments must be non-empty and at most 512 characters")
            if any(token in value for token in forbidden):
                raise ValueError("command arguments must not contain shell operators")
        return values

    @field_validator("expected_files")
    @classmethod
    def validate_expected_files(cls, values: dict[str, str | None]) -> dict[str, str | None]:
        for path, digest in values.items():
            if not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("expected file paths must stay inside the repository")
            if digest is not None and (
                len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("expected file hashes must be lowercase SHA-256 digests")
        return values

    @field_validator("candidate_patch")
    @classmethod
    def validate_candidate_patch(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("candidate_patch must be a non-empty Git-style patch")
        return value


class DevCheckRunOutput(DevWorkspaceCommandOutput):
    profile_id: str
    status: Literal["passed", "failed", "timed_out"]
    duration_ms: int = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    environment_keys: list[str]
    network_policy: Literal["disabled"]
    resource_limits: dict[str, int]
    candidate_patch_applied: bool = False


class DevWorkspacePatchProposalInput(StrictModel):
    summary: str
    patch: str

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("patch must not be empty")
        if len(value.encode("utf-8")) > 1_000_000:
            raise ValueError("patch must not exceed 1,000,000 bytes")
        if "diff --git " not in value and not ("\n--- " in "\n" + value and "\n+++ " in "\n" + value):
            raise ValueError("patch must be a unified diff")
        return value


class DevWorkspacePatchProposalOutput(DevWorkspaceCommandOutput):
    summary: str
    patch: str
    proposal_id: str | None = None
    artifact_ref: str | None = None
    approval_command: str | None = None


class DevWorkspacePatchFileBudget(StrictModel):
    path: str
    operation: Literal["created", "modified", "deleted"]
    max_changed_lines: int = Field(ge=1, le=5000)
    max_hunks: int = Field(ge=1, le=200)


class DevWorkspacePatchApplyInput(StrictModel):
    proposal_id: str
    patch: str
    patch_sha256: str
    authorization_source: Literal["operator_patch_approval", "developer_pipeline_plan"] = (
        "operator_patch_approval"
    )
    plan_budget: list[DevWorkspacePatchFileBudget] = Field(default_factory=list, max_length=200)

    @field_validator("proposal_id")
    @classmethod
    def validate_proposal_id(cls, value: str) -> str:
        if not value.startswith("patch_proposal_"):
            raise ValueError("proposal_id must start with patch_proposal_")
        return value

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: str) -> str:
        return DevWorkspacePatchProposalInput.validate_patch(value)

    @field_validator("patch_sha256")
    @classmethod
    def validate_patch_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("patch_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_budget_requirement(self) -> "DevWorkspacePatchApplyInput":
        if self.authorization_source == "developer_pipeline_plan" and not self.plan_budget:
            raise ValueError("developer_pipeline_plan authorization requires plan_budget")
        paths = [item.path for item in self.plan_budget]
        if len(paths) != len(set(paths)):
            raise ValueError("plan_budget paths must be unique")
        return self


class DevWorkspaceFileWrite(StrictModel):
    path: str
    operation: Literal["created", "modified", "deleted"]
    before_sha256: str | None = None
    after_sha256: str | None = None
    before_size_bytes: int | None = None
    after_size_bytes: int | None = None


class DevWorkspacePatchBudgetResult(StrictModel):
    status: Literal["passed", "not_provided"]
    checked_paths: list[str]
    violations: list[str]


class DevWorkspacePatchApplyOutput(DevWorkspaceCommandOutput):
    proposal_id: str
    patch_sha256: str
    authorization_source: Literal["operator_patch_approval", "developer_pipeline_plan"] = (
        "operator_patch_approval"
    )
    changed_files: list[DevWorkspaceFileWrite]
    diff_size_bytes: int = Field(default=1, ge=1)
    plan_budget_result: DevWorkspacePatchBudgetResult = Field(
        default_factory=lambda: DevWorkspacePatchBudgetResult(
            status="not_provided", checked_paths=[], violations=[]
        )
    )
    tool_evidence_path: str | None = None


DEV_WORKSPACE_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "dev_workspace_ready": {"input_model": DevWorkspaceReadyInput, "output_model": DevWorkspaceReadyOutput},
    "dev_workspace_list": {"input_model": DevWorkspaceListInput, "output_model": DevWorkspaceListOutput},
    "dev_workspace_find": {"input_model": DevWorkspaceFindInput, "output_model": DevWorkspaceFindOutput},
    "dev_workspace_grep": {"input_model": DevWorkspaceGrepInput, "output_model": DevWorkspaceGrepOutput},
    "dev_workspace_read": {"input_model": DevWorkspaceReadInput, "output_model": DevWorkspaceReadOutput},
    "dev_git_metadata": {"input_model": DevGitMetadataInput, "output_model": DevGitMetadataOutput},
    "dev_git_status": {"input_model": DevGitStatusInput, "output_model": DevGitStatusOutput},
    "dev_git_diff": {"input_model": DevGitDiffInput, "output_model": DevGitDiffOutput},
    "dev_git_log": {"input_model": DevGitLogInput, "output_model": DevGitLogOutput},
    "dev_git_show": {"input_model": DevGitShowInput, "output_model": DevGitShowOutput},
    "dev_git_tracked_files": {
        "input_model": DevGitTrackedFilesInput,
        "output_model": DevGitTrackedFilesOutput,
    },
    "dev_external_skill_list": {
        "input_model": DevExternalSkillListInput,
        "output_model": DevExternalSkillListOutput,
    },
    "dev_external_skill_read": {
        "input_model": DevExternalSkillReadInput,
        "output_model": DevExternalSkillReadOutput,
    },
    "dev_check_run": {"input_model": DevCheckRunInput, "output_model": DevCheckRunOutput},
    "dev_workspace_propose_patch": {
        "input_model": DevWorkspacePatchProposalInput,
        "output_model": DevWorkspacePatchProposalOutput,
    },
    "dev_workspace_apply_patch": {
        "input_model": DevWorkspacePatchApplyInput,
        "output_model": DevWorkspacePatchApplyOutput,
    },
}
