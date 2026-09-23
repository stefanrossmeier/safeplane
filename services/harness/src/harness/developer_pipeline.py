from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.documentation_agent import (
    DocumentationAgentError,
    DocumentationAgentResponse,
    DocumentationDocumentSnapshot,
    DocumentationEvidenceBundle,
    build_documentation_patch_from_replacements,
    collect_documentation_evidence,
    documentation_plan_budget,
    expand_documentation_placeholders,
    normalize_documentation_patch,
    normalize_documentation_response_metadata,
    parse_documentation_patch,
    snapshot_documentation,
    validate_documentation_patch_applicability,
    validate_documentation_response_patch,
)
from harness.mcp_schemas import validate_tool_input
from harness.patch_approval_store import (
    cleanup_patch_apply_workspace,
    create_patch_approval,
    prepare_patch_apply_workspace,
    publish_patch_apply_workspace,
    sha256_text,
    update_patch_approval,
    utc_now as approval_utc_now,
)
from harness.remote_write import (
    build_remote_approval_request,
    save_remote_approval_request,
)
from harness.run_store import load_run, update_run

PIPELINE_VERSION = "v1"
DEFAULT_FAKE_SCENARIO = "default"
FAKE_SCENARIO_PREFIX = "[safeplane-fake-scenario:"
ANALYSIS_RESEARCH_TOOL_CALL_LIMIT = 2
ANALYSIS_RESEARCH_TOOL_LOOP_TIMEOUT_SECONDS = 180


class DeveloperPipelineError(RuntimeError):
    pass


class DeveloperPipelineTransitionError(DeveloperPipelineError):
    pass


class DeveloperPipelineContractError(DeveloperPipelineError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeveloperRequestArtifact(StrictModel):
    task: str = Field(min_length=1)
    fake_scenario: str = DEFAULT_FAKE_SCENARIO


class RepositoryContextArtifact(StrictModel):
    repository_profile: str
    workspace_kind: Literal["local_snapshot", "git_multi_repository"]
    repository_root: str
    base_commit: str | None = None
    external_skill_commit: str | None = None
    external_sources: dict[str, str] = Field(default_factory=dict)
    note: str


class DocumentationResult(StrictModel):
    stage: Literal["baseline", "final"]
    summary: str = Field(min_length=1)
    documentation_files: list[str]
    changed: bool
    evidence_notes: list[str]
    uncertainties: list[str]
    skill_source_id: str | None = None
    skill_source_commit: str | None = None
    skill_files_read: list[str] = Field(default_factory=list)
    repository_files_read: list[str] = Field(default_factory=list)
    tool_evidence_refs: list[str] = Field(default_factory=list)
    patch_proposal_id: str | None = None
    patch_sha256: str | None = None
    apply_evidence_ref: str | None = None
    changed_files: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[DocumentationDocumentSnapshot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_live_documentation_metadata(self) -> "DocumentationResult":
        if self.skill_source_commit and len(self.skill_source_commit) < 7:
            raise ValueError("skill_source_commit is invalid")
        if self.changed and self.skill_source_commit:
            if not self.patch_proposal_id or not self.patch_sha256 or not self.apply_evidence_ref:
                raise ValueError("changed live documentation requires patch and apply evidence")
            if not self.changed_files:
                raise ValueError("changed live documentation requires changed_files")
        return self


class AnalysisResult(StrictModel):
    requirements_markdown: str = Field(min_length=1)
    architecture_tasks_markdown: str = Field(min_length=1)
    assumptions: list[str]
    open_questions: list[str]
    scope_risks: list[str]


class AnalysisToolCall(StrictModel):
    type: Literal["tool_call"]
    server_id: Literal["web-research"]
    tool_name: Literal["web_research_clarify"]
    arguments: dict[str, Any]


class FileChangePolicy(StrictModel):
    expected_change_summary: str = Field(min_length=1)
    max_changed_lines: int = Field(ge=1, le=2000)
    max_hunks: int = Field(ge=1, le=100)


@dataclass(frozen=True)
class OperatorFileConstraints:
    allowed_change_paths: frozenset[str] | None = None
    prohibit_new_files: bool = False
    prohibit_file_deletions: bool = False
    prohibit_check_script_changes: bool = False


_OPERATOR_PATH_TOKEN = re.compile(
    r"`([^`\n]+)`|(?<![\w/.-])((?:[A-Za-z0-9_.-]+/)*"
    r"(?:[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+|README))(?![\w/.-])",
    flags=re.IGNORECASE,
)
_OPERATOR_SCOPE_ACTION = re.compile(
    r"\b(change|modify|update|edit|touch|create|add|delete|remove)\b",
    flags=re.IGNORECASE,
)
_OPERATOR_CONDITIONAL_ESCAPE = re.compile(
    r"\b(unless|except|if necessary|if needed)\b",
    flags=re.IGNORECASE,
)


def _normalize_operator_path(value: str) -> str:
    normalized = value.strip().strip("`'\"").strip(" ,:()[]{}")
    normalized = normalized.replace("\\", "/")
    if normalized.casefold() in {"readme", "readme.md"}:
        return "README.md"
    return normalized


def _operator_constraint_sentences(task: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"[\n;]+|(?<=[.!?])\s+", task)
        if sentence.strip()
    ]


def _extract_operator_file_constraints(task: str) -> OperatorFileConstraints:
    only_scopes: list[set[str]] = []
    prohibit_new_files = False
    prohibit_file_deletions = False
    prohibit_check_script_changes = False

    for sentence in _operator_constraint_sentences(task):
        conditional = bool(_OPERATOR_CONDITIONAL_ESCAPE.search(sentence))
        lower = sentence.casefold()
        scope_sentence = sentence.rstrip(" \t.!?")

        path_candidates = {
            _normalize_operator_path(match.group(1) or match.group(2))
            for match in _OPERATOR_PATH_TOKEN.finditer(scope_sentence)
        }
        path_candidates.discard("")
        has_only_scope = bool(
            re.search(r"\bonly\b", scope_sentence, flags=re.IGNORECASE)
            and (
                _OPERATOR_SCOPE_ACTION.search(scope_sentence)
                or re.search(
                    r"^\s*(?:the\s+)?(?:file\s+)?README(?:\.md)?\s+only(?:\s*,|\s+and\b|\s*$)",
                    scope_sentence,
                    flags=re.IGNORECASE,
                )
                or re.search(
                    r"\bonly\s+(?:the\s+)?(?:file\s+)?README(?:\.md)?\b",
                    scope_sentence,
                    flags=re.IGNORECASE,
                )
            )
        )
        if has_only_scope and path_candidates and not conditional:
            only_scopes.append(path_candidates)

        if conditional:
            continue
        prohibit_new_files = prohibit_new_files or bool(
            re.search(r"\bno new files?\b", lower)
            or re.search(
                r"\b(?:do not|don't|must not|without)\s+(?:add|adding|create|creating)\s+"
                r"(?:any\s+)?(?:new\s+)?files?\b",
                lower,
            )
        )
        prohibit_file_deletions = prohibit_file_deletions or bool(
            re.search(r"\bno (?:file )?deletions?\b", lower)
            or re.search(
                r"\b(?:do not|don't|must not|without)\s+(?:delete|deleting|remove|removing)\s+"
                r"(?:any\s+)?files?\b",
                lower,
            )
        )
        prohibit_check_script_changes = prohibit_check_script_changes or bool(
            re.search(r"\bno (?:new )?(?:check|test|verification) scripts?\b", lower)
            or re.search(
                r"\b(?:do not|don't|must not|without)\s+"
                r"(?:add|adding|create|creating|modify|modifying|change|changing)\s+"
                r"(?:any\s+)?(?:new\s+)?(?:check|test|verification) scripts?\b",
                lower,
            )
        )

    allowed_change_paths: frozenset[str] | None = None
    if only_scopes:
        allowed = set(only_scopes[0])
        for scope in only_scopes[1:]:
            allowed.intersection_update(scope)
        allowed_change_paths = frozenset(allowed)

    return OperatorFileConstraints(
        allowed_change_paths=allowed_change_paths,
        prohibit_new_files=prohibit_new_files,
        prohibit_file_deletions=prohibit_file_deletions,
        prohibit_check_script_changes=prohibit_check_script_changes,
    )


def _normalize_commit_message(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    summary = re.sub(r"\s+", " ", lines[0]).strip()
    if len(summary) <= 120:
        return summary
    boundary = summary.rfind(" ", 0, 121)
    if boundary < 1:
        return summary[:120].rstrip()
    return summary[:boundary].rstrip()


def _drop_zero_budget_plan_paths(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    raw_policy = value.get("file_change_policy")
    if not isinstance(raw_policy, dict):
        return value

    zero_budget_paths = {
        path
        for path, policy in raw_policy.items()
        if isinstance(path, str)
        and isinstance(policy, dict)
        and type(policy.get("max_changed_lines")) is int
        and policy.get("max_changed_lines") == 0
    }
    if not zero_budget_paths:
        return value

    normalized = dict(value)
    for field_name in ("files_to_modify", "files_to_create", "files_to_delete"):
        raw_paths = value.get(field_name)
        if isinstance(raw_paths, list):
            normalized[field_name] = [
                path for path in raw_paths if path not in zero_budget_paths
            ]
    normalized["file_change_policy"] = {
        path: policy
        for path, policy in raw_policy.items()
        if path not in zero_budget_paths
    }
    return normalized


class ImplementationPlan(StrictModel):
    developer_plan_markdown: str = Field(min_length=1)
    files_to_modify: list[str]
    files_to_create: list[str]
    files_to_delete: list[str]
    file_change_policy: dict[str, FileChangePolicy]
    test_commands: list[list[str]] = Field(default_factory=list, max_length=20)
    documentation_impact: str
    risks: list[str]
    assumptions: list[str]
    commit_message: str = Field(min_length=1, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def drop_zero_budget_noop_paths(cls, value: Any) -> Any:
        return _drop_zero_budget_plan_paths(value)

    @field_validator("commit_message", mode="before")
    @classmethod
    def normalize_commit_message(cls, value: Any) -> Any:
        return _normalize_commit_message(value)

    @model_validator(mode="after")
    def validate_plan_paths_and_policies(self) -> "ImplementationPlan":
        groups = [self.files_to_modify, self.files_to_create, self.files_to_delete]
        flattened = [path for group in groups for path in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("implementation plan file lists must not overlap")

        planned_change_paths = (
            set(self.files_to_modify) | set(self.files_to_create) | set(self.files_to_delete)
        )
        policy_paths = set(self.file_change_policy)
        if planned_change_paths != policy_paths:
            raise ValueError(
                "file_change_policy must exist for every modified, created, or deleted file and no others"
            )

        for path in flattened:
            validate_relative_repository_path(path)

        for argv in self.test_commands:
            if not argv or any(not isinstance(item, str) or not item for item in argv):
                raise ValueError("test_commands must contain non-empty argument vectors")
            forbidden = {"|", "||", "&&", ">", ">>", "<", ";", "$(", "`"}
            if any(any(token in item for token in forbidden) for item in argv):
                raise ValueError("test_commands must not contain shell operators")

        return self


class ImplementationReplacement(StrictModel):
    path: str
    old_text: str
    new_text: str

    @model_validator(mode="after")
    def validate_replacement(self) -> "ImplementationReplacement":
        validate_relative_repository_path(self.path)
        if self.old_text == self.new_text:
            raise ValueError("implementation replacement must change text")
        return self


class ImplementationToolCall(StrictModel):
    type: Literal["tool_call"]
    server_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ImplementationFinalResponse(StrictModel):
    type: Literal["final"]
    implementation_summary_markdown: str = Field(min_length=1)
    replacements: list[ImplementationReplacement] = Field(min_length=1)
    changed_files: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_changed_files(self) -> "ImplementationFinalResponse":
        for path in self.changed_files:
            validate_relative_repository_path(path)
        if len(self.changed_files) != len(set(self.changed_files)):
            raise ValueError("implementation changed_files must not contain duplicates")
        return self


class ImplementationPatch(StrictModel):
    implementation_summary_markdown: str = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    changed_files: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_patch(self) -> "ImplementationPatch":
        if not self.unified_diff.startswith("diff --git "):
            raise ValueError("unified_diff must start with a Git-style diff header")
        for path in self.changed_files:
            validate_relative_repository_path(path)
        return self


class ImplementationApplyResult(StrictModel):
    proposal_id: str
    patch_sha256: str
    authorization_source: Literal["developer_pipeline_plan"]
    changed_files: list[dict[str, Any]]
    evidence_ref: str
    visibility_evidence_ref: str | None = None
    plan_budget_result: dict[str, Any]


class CheckCommandResult(StrictModel):
    profile_id: str
    argv: list[str]
    status: Literal["passed", "failed", "timed_out", "skipped"]
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    evidence_ref: str | None = None
    network_policy: Literal["disabled"] | None = None


class CheckResult(StrictModel):
    mode: Literal["controlled"]
    status: Literal["passed", "failed"]
    command_results: list[CheckCommandResult]
    summary: str


class ReviewResult(StrictModel):
    verdict: Literal["LGTM", "REQUEST_CHANGES"]
    summary: str = Field(min_length=1)
    plan_alignment: Literal["ALIGNED", "DEVIATION"]
    requested_changes: list[str]
    docs_update_needed: bool
    risk_notes: list[str]

    @model_validator(mode="after")
    def validate_requested_changes(self) -> "ReviewResult":
        if self.verdict == "LGTM" and self.plan_alignment != "ALIGNED":
            raise ValueError("LGTM requires plan_alignment ALIGNED")
        if self.verdict == "REQUEST_CHANGES" and self.plan_alignment == "ALIGNED" and not self.requested_changes:
            raise ValueError("REQUEST_CHANGES requires requested changes")
        if self.verdict == "LGTM" and self.requested_changes:
            raise ValueError("requested_changes must be empty for LGTM")
        if self.verdict == "REQUEST_CHANGES" and not self.requested_changes:
            raise ValueError("requested_changes must be non-empty for REQUEST_CHANGES")
        return self


class PrProposal(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    body_markdown: str = Field(min_length=1)
    draft: Literal[True]


class AgentRunMetadata(StrictModel):
    stage_id: str
    agent_id: str
    prompt_id: str
    prompt_version: str
    model_profile: str
    configured_model: str | None = None
    actual_model: str | None = None
    actual_provider: str | None = None
    model_mode: str | None = None
    generation_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    model_call_count: int = Field(default=1, ge=1)
    tool_call_count: int = Field(default=0, ge=0)
    artifact_refs: list[str]


class PipelineState(StrictModel):
    version: Literal["v1"] = PIPELINE_VERSION
    run_id: str
    workflow_id: Literal["developer"] = "developer"
    entrypoint: Literal["develop"] = "develop"
    current_state: str
    fake_scenario: str
    completed_stages: list[str]
    artifacts: dict[str, str]
    agent_runs: list[AgentRunMetadata]
    created_at: str
    updated_at: str


ARTIFACT_MODELS: dict[str, type[BaseModel]] = {
    "DocumentationResult": DocumentationResult,
    "AnalysisResult": AnalysisResult,
    "ImplementationPlan": ImplementationPlan,
    "ImplementationPatch": ImplementationPatch,
    "ReviewResult": ReviewResult,
    "PrProposal": PrProposal,
}


EXPECTED_TRANSITIONS: dict[str, tuple[str, set[str]]] = {
    "repositories": ("created", {"repositories_ready"}),
    "baseline_documentation": ("repositories_ready", {"documentation_ready"}),
    "analysis": ("documentation_ready", {"analysis_ready"}),
    "planning": ("analysis_ready", {"plan_ready"}),
    "implementation": ("plan_ready", {"implementation_ready"}),
    "checks": ("implementation_ready", {"checks_passed", "blocked", "failed"}),
    "final_documentation": ("checks_passed", {"documentation_reconciled"}),
    "review": (
        "documentation_reconciled",
        {"review_lgtm", "review_changes_requested"},
    ),
    "pr": ("review_lgtm", {"pr_ready"}),
    "remote_approval": ("pr_ready", {"waiting_for_remote_approval"}),
}


@dataclass(frozen=True)
class StageModelCallResult:
    content: str
    model: dict[str, Any]
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class AnalysisAgentLoopResult:
    artifact: AnalysisResult
    final_call: StageModelCallResult
    retry_count: int
    model_call_count: int
    tool_call_count: int
    usage: dict[str, Any] | None


@dataclass(frozen=True)
class ImplementationAgentLoopResult:
    artifact: ImplementationPatch
    final_call: StageModelCallResult
    retry_count: int
    model_call_count: int
    tool_call_count: int
    usage: dict[str, Any] | None


@dataclass(frozen=True)
class DeveloperPipelineResult:
    final_message: str
    current_state: str
    pipeline_ref: str


StageModelCaller = Callable[
    [str, str, str, list[dict[str, str]]],
    StageModelCallResult,
]
StageToolCaller = Callable[
    [str, str | None, str, str, dict[str, Any], str | None, str | None],
    dict[str, Any],
]
TraceWriter = Callable[
    [str, dict[str, Any] | None, dict[str, Any] | None, list[str] | None, dict[str, Any] | None],
    None,
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_relative_repository_path(raw: str) -> None:
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe repository-relative path: {raw!r}")
    if path.parts and path.parts[0] == ".git":
        raise ValueError(".git paths are not allowed")


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
        if fenced:
            value = json.loads(fenced.group(1))
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end <= start:
                raise DeveloperPipelineError("stage model did not return a JSON object")
            value = json.loads(stripped[start : end + 1])

    if not isinstance(value, dict):
        raise DeveloperPipelineError("stage model response must be a JSON object")
    return value


def parse_markdown_with_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise DeveloperPipelineContractError(f"developer prompt file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise DeveloperPipelineContractError(
            f"developer prompt must contain YAML frontmatter: {path}"
        )
    parts = raw.split("---\n", 2)
    if len(parts) != 3:
        raise DeveloperPipelineContractError(f"invalid prompt frontmatter: {path}")
    frontmatter = yaml.safe_load(parts[1]) or {}
    if not isinstance(frontmatter, dict):
        raise DeveloperPipelineContractError(f"prompt frontmatter must be a mapping: {path}")
    return frontmatter, parts[2].lstrip("\n")


def resolve_repo_resource(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return config_path.parent / path


def parse_fake_scenario(
    operator_message: str,
    pipeline_config: dict[str, Any],
) -> tuple[str, str]:
    message = operator_message.strip()
    scenario = DEFAULT_FAKE_SCENARIO
    if message.startswith(FAKE_SCENARIO_PREFIX):
        closing = message.find("]")
        if closing == -1:
            raise DeveloperPipelineError("invalid fake scenario marker")
        scenario = message[len(FAKE_SCENARIO_PREFIX) : closing].strip()
        message = message[closing + 1 :].lstrip()

    scenarios = pipeline_config.get("fake_scenarios", {})
    if scenario not in scenarios:
        raise DeveloperPipelineError(f"unknown developer fake scenario: {scenario}")
    if not message:
        raise DeveloperPipelineError("developer task is empty")
    return scenario, message


class DeveloperPipelineStore:
    def __init__(self, *, safeplane_home: Path, run_id: str, fake_scenario: str) -> None:
        self.safeplane_home = safeplane_home
        self.run_id = run_id
        self.run_dir = safeplane_home / "workspaces" / run_id
        self.pipeline_dir = self.run_dir / "pipeline"
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.pipeline_dir / "pipeline.json"
        self.events_path = self.pipeline_dir / "stage-events.jsonl"
        self.resumed = self.state_path.exists()
        if self.resumed:
            self.state = PipelineState.model_validate_json(
                self.state_path.read_text(encoding="utf-8")
            )
            if self.state.run_id != run_id:
                raise DeveloperPipelineTransitionError(
                    f"developer pipeline run id mismatch: {self.state.run_id} != {run_id}"
                )
            if self.state.fake_scenario != fake_scenario:
                raise DeveloperPipelineTransitionError(
                    "developer pipeline fake scenario cannot change during resume"
                )
        else:
            now = utc_now()
            self.state = PipelineState(
                run_id=run_id,
                current_state="created",
                fake_scenario=fake_scenario,
                completed_stages=[],
                artifacts={},
                agent_runs=[],
                created_at=now,
                updated_at=now,
            )
            self._persist()

    def relative_ref(self, path: Path) -> str:
        return str(path.relative_to(self.safeplane_home))

    def _persist(self) -> None:
        self.state_path.write_text(
            self.state.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def append_event(
        self,
        *,
        event: str,
        stage_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": utc_now(),
            "run_id": self.run_id,
            "event": event,
            "stage_id": stage_id,
            "current_state": self.state.current_state,
            "data": data or {},
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_json_artifact(self, name: str, model: BaseModel | dict[str, Any]) -> str:
        path = self.pipeline_dir / name
        if isinstance(model, BaseModel):
            raw = model.model_dump_json(indent=2)
        else:
            raw = json.dumps(model, ensure_ascii=False, indent=2)
        path.write_text(raw + "\n", encoding="utf-8")
        return self.relative_ref(path)

    def write_text_artifact(self, name: str, content: str) -> str:
        path = self.pipeline_dir / name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return self.relative_ref(path)

    def update_run_summary(self, **fields: Any) -> None:
        try:
            run = load_run(self.safeplane_home, self.run_id)
        except FileNotFoundError:
            return
        summary = dict(run.get("developer_pipeline") or {})
        summary.update(fields)
        update_run(self.safeplane_home, self.run_id, developer_pipeline=summary)

    def transition(
        self,
        *,
        stage_id: str,
        target_state: str,
        artifact_refs: dict[str, str] | None = None,
        agent_run: AgentRunMetadata | None = None,
    ) -> None:
        if stage_id in self.state.completed_stages:
            raise DeveloperPipelineTransitionError(f"stage already completed: {stage_id}")
        expected = EXPECTED_TRANSITIONS.get(stage_id)
        if expected is None:
            raise DeveloperPipelineTransitionError(f"unknown pipeline stage: {stage_id}")
        expected_state, allowed_targets = expected
        if self.state.current_state != expected_state:
            raise DeveloperPipelineTransitionError(
                f"stage {stage_id} requires state {expected_state}, "
                f"current state is {self.state.current_state}"
            )
        if target_state not in allowed_targets:
            raise DeveloperPipelineTransitionError(
                f"stage {stage_id} cannot transition to {target_state}"
            )

        self.state.current_state = target_state
        self.state.completed_stages.append(stage_id)
        if artifact_refs:
            self.state.artifacts.update(artifact_refs)
        if agent_run is not None:
            self.state.agent_runs.append(agent_run)
        self.state.updated_at = utc_now()
        self._persist()
        progress = {
            "current_state": target_state,
            "completed_stages": list(self.state.completed_stages),
            "artifacts": dict(self.state.artifacts),
            "agent_runs": [item.model_dump(mode="json") for item in self.state.agent_runs],
            "remote_approval_possible": target_state == "waiting_for_remote_approval",
        }
        self.update_run_summary(**progress)
        self.append_event(
            event="stage_completed",
            stage_id=stage_id,
            data={
                "target_state": target_state,
                "artifact_refs": artifact_refs or {},
                "agent_id": agent_run.agent_id if agent_run else None,
            },
        )


def validate_developer_pipeline_contract(contract: dict[str, Any]) -> None:
    pipeline = contract.get("developer_pipeline")
    agents = contract.get("agents")
    profiles = contract.get("model_profiles", {})
    if not isinstance(pipeline, dict) or not pipeline.get("enabled"):
        raise DeveloperPipelineContractError("developer_pipeline.enabled must be true")
    if pipeline.get("entrypoint") != "develop":
        raise DeveloperPipelineContractError("developer pipeline entrypoint must be 'develop'")
    if not isinstance(agents, dict) or not agents:
        raise DeveloperPipelineContractError("developer workflow must define agents")

    for profile_id, profile_config in profiles.items():
        if not isinstance(profile_config, dict):
            raise DeveloperPipelineContractError(
                f"model profile {profile_id} must be a mapping"
            )
        timeout_seconds = profile_config.get("request_timeout_seconds", 30)
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds < 1
            or timeout_seconds > 3600
        ):
            raise DeveloperPipelineContractError(
                f"model profile {profile_id} request_timeout_seconds must be between 1 and 3600"
            )
        response_format = profile_config.get("response_format")
        if response_format not in {None, "json_object"}:
            raise DeveloperPipelineContractError(
                f"model profile {profile_id} response_format must be json_object when configured"
            )

    required_agents = {"documentation", "analysis", "planning", "implementation", "review", "pr"}
    if set(agents) != required_agents:
        raise DeveloperPipelineContractError(
            "developer agents must be exactly: " + ", ".join(sorted(required_agents))
        )

    for agent_id, config in agents.items():
        if not isinstance(config, dict):
            raise DeveloperPipelineContractError(f"agent {agent_id} must be a mapping")
        prompt = config.get("prompt")
        if not isinstance(prompt, dict) or not all(prompt.get(key) for key in ("id", "version", "path")):
            raise DeveloperPipelineContractError(
                f"agent {agent_id} must define prompt.id, prompt.version, and prompt.path"
            )
        profile = config.get("model_profile")
        if profile not in profiles:
            raise DeveloperPipelineContractError(
                f"agent {agent_id} references unknown model profile: {profile}"
            )
        attempts = config.get("max_model_attempts")
        if not isinstance(attempts, int) or attempts < 1 or attempts > 10:
            raise DeveloperPipelineContractError(
                f"agent {agent_id} max_model_attempts must be between 1 and 10"
            )
        tool_loop_timeout = config.get("tool_loop_timeout_seconds")
        if tool_loop_timeout is not None and (
            not isinstance(tool_loop_timeout, int)
            or isinstance(tool_loop_timeout, bool)
            or tool_loop_timeout < 1
            or tool_loop_timeout > 14400
        ):
            raise DeveloperPipelineContractError(
                f"agent {agent_id} tool_loop_timeout_seconds must be between 1 and 14400"
            )
        if agent_id == "implementation" and tool_loop_timeout is None:
            raise DeveloperPipelineContractError(
                "implementation agent must define tool_loop_timeout_seconds"
            )
        if agent_id != "implementation" and tool_loop_timeout is not None:
            raise DeveloperPipelineContractError(
                "tool_loop_timeout_seconds is supported only for the implementation agent"
            )

        agent_servers = config.get("allowed_mcp_servers")
        if not isinstance(agent_servers, dict):
            raise DeveloperPipelineContractError(
                f"agent {agent_id} allowed_mcp_servers must be a mapping"
            )

    mcp = contract.get("mcp") or {}
    workflow_servers = mcp.get("allowed_servers") or {}
    if not isinstance(workflow_servers, dict):
        raise DeveloperPipelineContractError("developer mcp.allowed_servers must be a mapping")

    def configured_tools(policies: dict[str, Any], server_id: str) -> set[str]:
        policy = policies.get(server_id)
        if isinstance(policy, dict):
            return {str(item) for item in policy.get("tools") or []}
        if isinstance(policy, list):
            return {str(item) for item in policy}
        return set()

    for agent_id, config in agents.items():
        agent_servers = config["allowed_mcp_servers"]
        for server_id in agent_servers:
            if server_id not in workflow_servers:
                raise DeveloperPipelineContractError(
                    f"agent {agent_id} references unavailable MCP server: {server_id}"
                )
            extra = configured_tools(agent_servers, server_id) - configured_tools(
                workflow_servers, server_id
            )
            if extra:
                raise DeveloperPipelineContractError(
                    f"agent {agent_id} references unavailable MCP tools: {', '.join(sorted(extra))}"
                )

    external_tools = {"dev_external_skill_list", "dev_external_skill_read"}
    documentation_tools = configured_tools(
        agents["documentation"]["allowed_mcp_servers"], "dev-workspace"
    )
    if not external_tools.issubset(documentation_tools):
        raise DeveloperPipelineContractError(
            "documentation agent must have both external archdoc read tools"
        )
    for agent_id in required_agents - {"documentation"}:
        tools = configured_tools(agents[agent_id]["allowed_mcp_servers"], "dev-workspace")
        if tools & external_tools:
            raise DeveloperPipelineContractError(
                f"only documentation may receive external skill tools: {agent_id}"
            )
    if agents["pr"]["allowed_mcp_servers"]:
        raise DeveloperPipelineContractError("PR agent must not receive repository tools")

    command_profiles = (contract.get("developer_tools") or {}).get("command_profiles")
    if not isinstance(command_profiles, dict) or "python_check" not in command_profiles:
        raise DeveloperPipelineContractError(
            "developer workflow must define the python_check command profile"
        )
    python_check = command_profiles["python_check"]
    if not isinstance(python_check, dict) or python_check.get("network") != "disabled":
        raise DeveloperPipelineContractError("python_check network must be disabled")

    if "dev_check_run" not in configured_tools(workflow_servers, "dev-check"):
        raise DeveloperPipelineContractError(
            "developer workflow must broker dev_check_run through dev-check"
        )
    approval_servers = mcp.get("approval_required_servers") or {}
    if "dev_workspace_apply_patch" not in configured_tools(
        approval_servers, "dev-workspace-apply"
    ):
        raise DeveloperPipelineContractError(
            "developer workflow must require approval for dev_workspace_apply_patch"
        )
    implementation_tools = configured_tools(
        agents["implementation"]["allowed_mcp_servers"], "dev-workspace"
    )
    if "dev_workspace_propose_patch" not in implementation_tools:
        raise DeveloperPipelineContractError(
            "implementation agent must be able to propose its patch"
        )
    forbidden_agent_tools = {"dev_check_run", "dev_workspace_apply_patch"}
    for agent_id, config in agents.items():
        all_tools: set[str] = set()
        for server_id in config["allowed_mcp_servers"]:
            all_tools.update(configured_tools(config["allowed_mcp_servers"], server_id))
        if all_tools & forbidden_agent_tools:
            raise DeveloperPipelineContractError(
                f"deterministic apply and check tools must not be assigned to agent {agent_id}"
            )
    model_servers = mcp.get("model_allowed_servers") or {}
    model_tools = {
        tool
        for server_id in model_servers
        for tool in configured_tools(model_servers, server_id)
    }
    if model_tools & {"dev_check_run", "dev_workspace_apply_patch", *external_tools}:
        raise DeveloperPipelineContractError(
            "model-visible tools must exclude controlled checks, patch apply, and external skill reads"
        )

    stages = pipeline.get("stages")
    if not isinstance(stages, list) or not stages:
        raise DeveloperPipelineContractError("developer pipeline must define stages")
    stage_ids: list[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            raise DeveloperPipelineContractError("developer pipeline stage must be a mapping")
        stage_id = stage.get("id")
        agent_id = stage.get("agent")
        schema = stage.get("output_schema")
        if not stage_id or not agent_id or not schema:
            raise DeveloperPipelineContractError(
                "developer pipeline stages require id, agent, and output_schema"
            )
        if stage_id in stage_ids:
            raise DeveloperPipelineContractError(f"duplicate developer stage: {stage_id}")
        if agent_id not in agents:
            raise DeveloperPipelineContractError(
                f"developer stage {stage_id} references unknown agent: {agent_id}"
            )
        if schema not in ARTIFACT_MODELS:
            raise DeveloperPipelineContractError(
                f"developer stage {stage_id} references unknown output schema: {schema}"
            )
        stage_ids.append(stage_id)

    expected = [
        "baseline_documentation",
        "analysis",
        "planning",
        "implementation",
        "final_documentation",
        "review",
        "pr",
    ]
    if stage_ids != expected:
        raise DeveloperPipelineContractError(
            "developer pipeline stage order must be: " + ", ".join(expected)
        )

    scenarios = pipeline.get("fake_scenarios")
    if not isinstance(scenarios, dict) or DEFAULT_FAKE_SCENARIO not in scenarios:
        raise DeveloperPipelineContractError("developer pipeline must define fake_scenarios.default")

    repository_workspace = contract.get("repository_workspace")
    if not isinstance(repository_workspace, dict):
        raise DeveloperPipelineContractError("developer workflow must define repository_workspace")
    external_sources = repository_workspace.get("external_sources")
    if not isinstance(external_sources, dict) or "archdoc" not in external_sources:
        raise DeveloperPipelineContractError(
            "developer workflow must define the external archdoc source"
        )
    archdoc = external_sources["archdoc"]
    if not isinstance(archdoc, dict):
        raise DeveloperPipelineContractError("external archdoc source must be a mapping")
    if archdoc.get("required_path") != "skills/archdoc":
        raise DeveloperPipelineContractError(
            "external archdoc source must use required_path skills/archdoc"
        )
    if archdoc.get("allowed_agents") != ["documentation"]:
        raise DeveloperPipelineContractError(
            "only the documentation agent may access the external archdoc source"
        )
    if archdoc.get("read_only") is not True:
        raise DeveloperPipelineContractError("external archdoc source must be read-only")

    documentation_runtime = pipeline.get("documentation_runtime")
    if not isinstance(documentation_runtime, dict) or documentation_runtime.get("enabled") is not True:
        raise DeveloperPipelineContractError(
            "developer pipeline must enable documentation_runtime"
        )
    if documentation_runtime.get("source_id") != "archdoc":
        raise DeveloperPipelineContractError(
            "documentation_runtime.source_id must be archdoc"
        )
    if documentation_runtime.get("skill_entrypoint") != "SKILL.md":
        raise DeveloperPipelineContractError(
            "documentation_runtime.skill_entrypoint must be SKILL.md"
        )
    target_paths = documentation_runtime.get("target_document_paths")
    required_target_paths = {
        "docs/REPO_MAP.md",
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
    }
    if not isinstance(target_paths, list) or not required_target_paths.issubset(
        {str(item) for item in target_paths}
    ):
        raise DeveloperPipelineContractError(
            "documentation_runtime must include the primary archdoc target files"
        )
    for field_name in (
        "max_skill_files",
        "max_skill_total_bytes",
        "max_skill_file_bytes",
        "read_page_lines",
        "tracked_file_page_size",
        "max_repository_files",
        "max_repository_total_bytes",
        "max_repository_file_bytes",
        "max_changed_lines_per_file",
        "max_hunks_per_file",
    ):
        value = documentation_runtime.get(field_name)
        if not isinstance(value, int) or value < 1:
            raise DeveloperPipelineContractError(
                f"documentation_runtime.{field_name} must be a positive integer"
            )
    if documentation_runtime["read_page_lines"] > 2000:
        raise DeveloperPipelineContractError(
            "documentation_runtime.read_page_lines must not exceed the MCP per-read limit"
        )
    if documentation_runtime["tracked_file_page_size"] > 10000:
        raise DeveloperPipelineContractError(
            "documentation_runtime.tracked_file_page_size must not exceed the MCP listing limit"
        )
    if documentation_runtime.get("require_complete_repository_evidence") is not True:
        raise DeveloperPipelineContractError(
            "documentation_runtime must require complete repository evidence"
        )


def _render_stage_user_message(
    *,
    stage_id: str,
    task: str,
    input_artifacts: dict[str, Any],
) -> str:
    if stage_id in {"baseline_documentation", "final_documentation"}:
        documentation_inputs = {
            name: value
            for name, value in input_artifacts.items()
            if name != "developer_request"
        }
        return json.dumps(
            {
                "stage_id": stage_id,
                "stage_boundary": (
                    "Reconcile only the configured primary documentation files under "
                    "docs/. The operator task is intentionally not an implementation "
                    "instruction for this stage. README.md and all non-docs paths belong "
                    "to implementation."
                ),
                "input_artifacts": documentation_inputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        {
            "stage_id": stage_id,
            "operator_task": task,
            "input_artifacts": input_artifacts,
        },
        ensure_ascii=False,
        indent=2,
    )


def _documentation_repair_message(error: Exception) -> str:
    return (
        "Your previous response was rejected by Safeplane's deterministic "
        "documentation validator. Return one complete corrected JSON object only; "
        "do not return commentary, Markdown fences, or any keys outside the exact "
        "schema below.\n\n"
        f"Validation error: {type(error).__name__}: {error}\n\n"
        "Use this exact top-level shape: stage, summary, documentation_files, "
        "changed, replacements, evidence_notes, uncertainties. Do not add `notes` "
        "or `unified_diff`.\n\n"
        "This stage may reconcile only the configured primary files under `docs/`. "
        "It must never implement the operator task, modify `README.md`, or change "
        "application, test, check, configuration, or other repository files. If the "
        "operator task affects only non-docs files and the configured docs remain "
        "accurate, return `changed`: false with empty `documentation_files` and "
        "`replacements`.\n\n"
        "For a changed response, `replacements` must be a non-empty array of exact "
        "text replacements. Each item has only `path`, `old_text`, and `new_text`. "
        "Copy `old_text` exactly from the supplied repository file. It must match "
        "exactly once. Use an empty `old_text` only to create a missing file. "
        "Safeplane deterministically builds and validates the Git patch; do not "
        "write any `@@` hunk headers yourself. For an unchanged response, return "
        "`replacements`: [].\n\n"
        "For every changed Markdown file, include this exact metadata structure near "
        "the top of the resulting `new_text`. Keep the field names and literal "
        "placeholders exactly as shown:\n\n"
        "> Generated with `ai-craftkit` skill: `archdoc`\n"
        "> Source: `ai-craftkit` at commit `${ARCHDOC_COMMIT}`\n"
        "> Skill bundle SHA-256: `${ARCHDOC_SKILL_SHA256}`\n"
        "> Prompt: `${DOCUMENTATION_PROMPT}`\n"
        "> Repository profile: `${REPOSITORY_PROFILE}`\n\n"
        "Doc Status: DRAFT\n"
        "Source Basis: repository files supplied through Safeplane MCP tools and "
        "the external archdoc skill\n\n"
        "The validator checks the literal field names `Doc Status:` and `Source "
        "Basis:`. Do not rename them, convert them into a table, or express them only "
        "in prose. Safeplane expands the placeholders deterministically before "
        "validation and patch application."
    )


def _planning_repair_message(
    error: Exception,
    *,
    contract: dict[str, Any],
) -> str:
    profiles = ((contract.get("developer_tools") or {}).get("command_profiles") or {})
    profile_lines: list[str] = []
    for profile_id, profile in sorted(profiles.items()):
        if not isinstance(profile, dict):
            continue
        executable = str(profile.get("executable") or "")
        roots = [str(item) for item in profile.get("allowed_roots") or []]
        suffixes = [str(item) for item in profile.get("allowed_suffixes") or []]
        profile_lines.append(
            f"- {profile_id}: executable={executable!r}, "
            f"allowed_roots={roots}, allowed_suffixes={suffixes}"
        )
    rendered_profiles = "\n".join(profile_lines) or "- none"
    return (
        "Your previous planning response was rejected by Safeplane's deterministic "
        "plan validator. Return one complete corrected JSON object only; do not "
        "return commentary or Markdown fences. Preserve the valid task scope and "
        "repair the structured fields named in the validation error.\n\n"
        f"Validation error: {type(error).__name__}: {error}\n\n"
        "Declared check commands are executed later by the harness in an isolated, "
        "network-disabled container. Every command must match exactly one profile "
        "below. Its script path must already be a regular repository file or be "
        "listed in files_to_create/files_to_modify with a positive change policy. "
        "Do not copy example or placeholder paths. The script must be directly "
        "runnable by the exact argv and must exit non-zero when its focused "
        "assertion fails. Do not assume project dependencies or a test runner are "
        "installed unless an existing repository check proves that they are.\n\n"
        "Allowed command profiles:\n"
        f"{rendered_profiles}\n\n"
        "Explicit operator file constraints are binding. A plan must not add paths "
        "outside an `only` scope, create files when new files were forbidden, delete "
        "files when deletion was forbidden, or add/modify check scripts when check "
        "scripts were forbidden. When no existing repository check is both directly "
        "relevant and proven by repository evidence, return an empty test_commands "
        "list instead of inventing or relocating a check path."
    )


IMPLEMENTATION_INSPECTION_TOOLS = {
    "dev_workspace_list",
    "dev_workspace_find",
    "dev_workspace_grep",
    "dev_workspace_read",
    "dev_git_metadata",
    "dev_git_status",
    "dev_git_diff",
    "dev_git_log",
    "dev_git_show",
    "dev_git_tracked_files",
}


def _planned_implementation_operations(plan: ImplementationPlan) -> dict[str, str]:
    operations: dict[str, str] = {}
    for path in plan.files_to_modify:
        operations[path] = "modify"
    for path in plan.files_to_create:
        operations[path] = "create"
    for path in plan.files_to_delete:
        operations[path] = "delete"
    return operations


def _resolve_implementation_path(repository_root: Path, path: str) -> Path:
    validate_relative_repository_path(path)
    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise DeveloperPipelineError(
            f"target repository is unavailable for implementation: {exc}"
        ) from exc
    unresolved = root / path
    if unresolved.is_symlink():
        raise DeveloperPipelineError(
            f"implementation may not target a symlink: {path}"
        )
    candidate = unresolved.resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise DeveloperPipelineError(
            f"implementation path escapes repository root: {path}"
        )
    return candidate


def build_implementation_patch_from_replacements(
    replacements: list[ImplementationReplacement],
    *,
    plan: ImplementationPlan,
    repository_root: Path,
) -> str:
    """Build a plan-bound Git patch from exact model-authored replacements."""

    if not replacements:
        raise DeveloperPipelineError(
            "implementation final response requires at least one replacement"
        )

    operations = _planned_implementation_operations(plan)
    planned_paths = set(operations)
    replacement_paths = {item.path for item in replacements}
    if replacement_paths != planned_paths:
        raise DeveloperPipelineError(
            "implementation replacement paths must exactly match planned change paths"
        )

    grouped: dict[str, list[ImplementationReplacement]] = {
        path: [] for path in operations
    }
    for replacement in replacements:
        grouped[replacement.path].append(replacement)

    original_by_path: dict[str, str] = {}
    updated_by_path: dict[str, str] = {}
    ordered_paths = plan.files_to_modify + plan.files_to_create + plan.files_to_delete

    for path in ordered_paths:
        operation = operations[path]
        candidate = _resolve_implementation_path(repository_root, path)
        path_replacements = grouped[path]

        if operation == "create":
            if candidate.exists():
                raise DeveloperPipelineError(
                    f"planned implementation create path already exists: {path}"
                )
            if len(path_replacements) != 1:
                raise DeveloperPipelineError(
                    f"implementation create path requires exactly one replacement: {path}"
                )
            replacement = path_replacements[0]
            if replacement.old_text != "" or replacement.new_text == "":
                raise DeveloperPipelineError(
                    "implementation create replacement requires empty old_text and "
                    f"non-empty new_text: {path}"
                )
            original = ""
            updated = replacement.new_text
        else:
            if not candidate.is_file():
                raise DeveloperPipelineError(
                    f"planned implementation {operation} path is not a regular file: {path}"
                )
            try:
                original = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise DeveloperPipelineError(
                    f"implementation path is not UTF-8 text: {path}"
                ) from exc

            if operation == "delete":
                if len(path_replacements) != 1:
                    raise DeveloperPipelineError(
                        f"implementation delete path requires exactly one replacement: {path}"
                    )
                replacement = path_replacements[0]
                if replacement.old_text != original or replacement.new_text != "":
                    raise DeveloperPipelineError(
                        "implementation delete replacement must contain the complete "
                        f"current file as old_text and empty new_text: {path}"
                    )
                updated = ""
            else:
                updated = original
                for replacement in path_replacements:
                    if replacement.old_text == "":
                        raise DeveloperPipelineError(
                            "empty old_text is allowed only for a planned create path: "
                            f"{path}"
                        )
                    occurrences = updated.count(replacement.old_text)
                    if occurrences != 1:
                        raise DeveloperPipelineError(
                            "implementation replacement old_text must match exactly once: "
                            f"{path} matched {occurrences} times"
                        )
                    updated = updated.replace(
                        replacement.old_text,
                        replacement.new_text,
                        1,
                    )
                if updated == "":
                    raise DeveloperPipelineError(
                        f"planned modify may not delete the complete file: {path}"
                    )

        if original == updated:
            raise DeveloperPipelineError(
                f"implementation replacements produced no change: {path}"
            )
        original_by_path[path] = original
        updated_by_path[path] = updated

    sections: list[str] = []
    for path in ordered_paths:
        operation = operations[path]
        old = original_by_path[path]
        new = updated_by_path[path]
        from_file = "/dev/null" if operation == "create" else f"a/{path}"
        to_file = "/dev/null" if operation == "delete" else f"b/{path}"
        diff_lines = list(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=from_file,
                tofile=to_file,
                n=3,
                lineterm="",
            )
        )
        if not diff_lines:
            raise DeveloperPipelineError(
                f"implementation replacements produced no diff: {path}"
            )
        section = [f"diff --git a/{path} b/{path}"]
        if operation == "create":
            section.append("new file mode 100644")
        elif operation == "delete":
            section.append("deleted file mode 100644")
        section.extend(diff_lines)
        sections.append("\n".join(section) + "\n")

    return "".join(sections)


def _configured_agent_tools(agent: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    raw_servers = agent.get("allowed_mcp_servers") or {}
    if not isinstance(raw_servers, dict):
        return result
    for server_id, policy in raw_servers.items():
        if isinstance(policy, dict):
            tools = policy.get("tools") or []
        elif isinstance(policy, list):
            tools = policy
        else:
            tools = []
        result[str(server_id)] = {str(item) for item in tools}
    return result


def _validate_analysis_tool_call(
    tool_call: AnalysisToolCall,
    *,
    agent: dict[str, Any],
) -> None:
    allowed = _configured_agent_tools(agent)
    if tool_call.server_id not in allowed:
        raise DeveloperPipelineError("analysis web-research server is not allowed")
    if tool_call.tool_name not in allowed[tool_call.server_id]:
        raise DeveloperPipelineError("analysis web-research tool is not allowed")
    validate_tool_input(tool_call.tool_name, tool_call.arguments)


def _validate_implementation_tool_call(
    tool_call: ImplementationToolCall,
    *,
    agent: dict[str, Any],
) -> None:
    allowed = _configured_agent_tools(agent)
    if tool_call.server_id not in allowed:
        raise DeveloperPipelineError(
            f"implementation tool server is not allowed: {tool_call.server_id}"
        )
    if tool_call.tool_name not in allowed[tool_call.server_id]:
        raise DeveloperPipelineError(
            "implementation tool is not allowed: "
            f"{tool_call.server_id}/{tool_call.tool_name}"
        )
    if tool_call.tool_name not in IMPLEMENTATION_INSPECTION_TOOLS:
        raise DeveloperPipelineError(
            "implementation tool loop permits read-only repository inspection only: "
            f"{tool_call.tool_name}"
        )
    validate_tool_input(tool_call.tool_name, tool_call.arguments)


def _accumulate_model_usage(
    total: dict[str, Any] | None,
    usage: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not usage:
        return total
    result = dict(total or {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result[key] = int(result.get(key) or 0) + value
    cost = usage.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        result["cost"] = float(result.get("cost") or 0.0) + float(cost)
    return result or None


def _run_analysis_agent_loop(
    *,
    agent: dict[str, Any],
    model_profile: str,
    response_key: str,
    system_prompt: str,
    user_message: str,
    max_attempts: int,
    call_stage_model: StageModelCaller,
    call_stage_tool: StageToolCaller | None,
    trace: TraceWriter,
    store: DeveloperPipelineStore,
) -> AnalysisAgentLoopResult:
    """Allow only bounded public-research clarification before AnalysisResult."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    deadline = time.monotonic() + ANALYSIS_RESEARCH_TOOL_LOOP_TIMEOUT_SECONDS
    invalid_attempts = 0
    model_call_count = 0
    tool_call_count = 0
    total_usage: dict[str, Any] | None = None
    trace(
        "developer_pipeline_analysis_research_loop_started",
        {
            "stage_id": "analysis",
            "timeout_seconds": ANALYSIS_RESEARCH_TOOL_LOOP_TIMEOUT_SECONDS,
            "max_validation_attempts": max_attempts,
            "tool_call_limit": ANALYSIS_RESEARCH_TOOL_CALL_LIMIT,
        },
        None,
        None,
        None,
    )
    while True:
        if time.monotonic() >= deadline:
            raise DeveloperPipelineError(
                "analysis research loop exceeded its wall-clock deadline before "
                "the model returned a valid AnalysisResult"
            )
        call_result = call_stage_model(
            "analysis",
            response_key,
            model_profile,
            messages,
        )
        model_call_count += 1
        total_usage = _accumulate_model_usage(total_usage, call_result.usage)
        content = call_result.content
        try:
            raw = extract_json_object(content)
            if raw.get("type") == "tool_call":
                if tool_call_count >= ANALYSIS_RESEARCH_TOOL_CALL_LIMIT:
                    raise DeveloperPipelineError(
                        "analysis exceeded the public web-research call limit"
                    )
                tool_call = AnalysisToolCall.model_validate(raw)
                _validate_analysis_tool_call(tool_call, agent=agent)
                tool_call_count += 1
                tool_error: dict[str, str] | None = None
                tool_content: dict[str, Any] = {}
                try:
                    if call_stage_tool is None:
                        raise DeveloperPipelineError(
                            "analysis web-research tool caller is unavailable"
                        )
                    tool_content = call_stage_tool(
                        "analysis",
                        "analysis",
                        tool_call.server_id,
                        tool_call.tool_name,
                        tool_call.arguments,
                        None,
                        None,
                    )
                except Exception as exc:
                    tool_error = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                tool_result = {
                    "type": "tool_result",
                    "server_id": tool_call.server_id,
                    "tool_name": tool_call.tool_name,
                    "ok": tool_error is None,
                    "result": tool_content if tool_error is None else None,
                    "error": tool_error,
                }
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Safeplane executed the isolated public-research request.\n"
                                "Tool result JSON:\n"
                                + json.dumps(
                                    tool_result,
                                    ensure_ascii=False,
                                    indent=2,
                                    default=str,
                                )
                                + "\n\nUse the result only as external clarification. "
                                "Return the final AnalysisResult when ready."
                            ),
                        },
                    ]
                )
                trace(
                    "developer_pipeline_analysis_research_turn_completed",
                    {
                        "stage_id": "analysis",
                        "tool_call_index": tool_call_count,
                        "server_id": tool_call.server_id,
                        "tool_name": tool_call.tool_name,
                    },
                    {"ok": tool_error is None, "model_call_count": model_call_count},
                    None,
                    tool_error,
                )
                continue
            artifact = AnalysisResult.model_validate(raw)
            final_call = StageModelCallResult(
                content=call_result.content,
                model=call_result.model,
                usage=total_usage,
                finish_reason=call_result.finish_reason,
            )
            return AnalysisAgentLoopResult(
                artifact=artifact,
                final_call=final_call,
                retry_count=invalid_attempts,
                model_call_count=model_call_count,
                tool_call_count=tool_call_count,
                usage=total_usage,
            )
        except Exception as exc:
            invalid_attempts += 1
            trace(
                "developer_pipeline_stage_attempt_failed",
                {
                    "stage_id": "analysis",
                    "agent_id": "analysis",
                    "attempt": invalid_attempts,
                    "max_attempts": max_attempts,
                    "model_call_count": model_call_count,
                    "tool_call_count": tool_call_count,
                },
                None,
                None,
                {"type": type(exc).__name__, "message": str(exc)},
            )
            store.append_event(
                event="stage_attempt_failed",
                stage_id="analysis",
                data={
                    "attempt": invalid_attempts,
                    "max_attempts": max_attempts,
                    "error_type": type(exc).__name__,
                    "model_call_count": model_call_count,
                    "tool_call_count": tool_call_count,
                },
            )
            if invalid_attempts >= max_attempts:
                raise DeveloperPipelineError(
                    "stage analysis produced no valid output after "
                    f"{max_attempts} attempts: {exc}"
                ) from exc
            messages.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Return either one allowed public-research tool_call or the "
                            "required final AnalysisResult JSON object. Do not widen the "
                            f"research request. Validation error: {type(exc).__name__}."
                        ),
                    },
                ]
            )


def _implementation_import_failure_guidance(
    error: Exception,
    *,
    plan: ImplementationPlan,
) -> str:
    error_text = str(error)
    if (
        "candidate implementation failed a declared check before final acceptance"
        not in error_text
        or not re.search(r"\b(?:ModuleNotFoundError|ImportError)\b", error_text)
    ):
        return ""

    python_sources = sorted(
        path for path in plan.files_to_modify if Path(path).suffix == ".py"
    )
    source_hint = (
        " Planned Python source paths: "
        + json.dumps(python_sources, ensure_ascii=False)
        + "."
        if python_sources
        else ""
    )
    return (
        "\n\nThe candidate traceback shows a Python import failure inside the isolated "
        "check container. Do not repair this only by changing `sys.path`, adding "
        "the repository root to the import path, or loading a planned application "
        "module with `importlib.util.spec_from_file_location` and `exec_module`; "
        "those approaches still execute transitive application imports whose "
        "dependencies or external services may be unavailable. Keep the declared "
        "argv unchanged and make the focused check self-contained with the Python "
        "standard library. When the assertion concerns a static declaration or data "
        "structure, read the target source file with `pathlib` and inspect it as text "
        "or with `ast.parse` without importing or executing the application module."
        + source_hint
    )


def _implementation_budget_failure_guidance(
    error: Exception,
    *,
    plan: ImplementationPlan,
) -> str:
    error_text = str(error)
    if "implementation exceeds approved plan budget" not in error_text:
        return ""

    violations = re.findall(
        r"changed-line budget exceeded for ([^:]+): (\d+) > (\d+)",
        error_text,
    )
    if not violations:
        return ""

    created = set(plan.files_to_create)
    details: list[str] = []
    for path, actual_text, maximum_text in violations:
        if path not in created or Path(path).suffix != ".py":
            continue
        actual = int(actual_text)
        maximum = int(maximum_text)
        details.append(
            f" `{path}` is a created Python file with {actual} changed lines and "
            f"must contain at most {maximum} physical lines."
        )

    if not details:
        return ""

    return (
        "\n\nThe budget failure is in a newly created Python check."
        + "".join(details)
        + " Count the complete `new_text` before returning final. Keep only the "
        "imports and assertions required by the declared check. Remove shebangs, "
        "module docstrings, run instructions, exit-code catalogs, legacy-AST "
        "compatibility branches, wrapper functions, and explanatory comments unless "
        "they are required for correctness. When checking a static literal "
        "assignment, prefer `ast.parse` plus `ast.literal_eval` over manually walking "
        "every dictionary key and value node. Do not weaken the assertion or change "
        "the approved mechanism merely to fit the budget."
    )


def _implementation_repair_message(
    error: Exception,
    *,
    plan: ImplementationPlan,
) -> str:
    planned_paths = sorted(
        set(plan.files_to_modify)
        | set(plan.files_to_create)
        | set(plan.files_to_delete)
    )
    import_failure_guidance = _implementation_import_failure_guidance(
        error,
        plan=plan,
    )
    budget_failure_guidance = _implementation_budget_failure_guidance(
        error,
        plan=plan,
    )
    return (
        "Your previous implementation response was rejected by Safeplane's "
        "deterministic validator. You may request another repository tool before "
        "trying the final response again. Do not claim completion until you can "
        "return a valid final response.\n\n"
        f"Validation error: {type(error).__name__}: {error}\n\n"
        "A tool turn must use exactly this shape: "
        '{"type":"tool_call","server_id":"dev-workspace","tool_name":"...",'
        '"arguments":{...}}. A final turn must use `type: final`, '
        "`implementation_summary_markdown`, `replacements`, and `changed_files`. "
        "Do not return `unified_diff` or Git hunk syntax.\n\n"
        "The `changed_files` array and replacement path set must exactly equal: "
        f"{json.dumps(planned_paths, ensure_ascii=False)}. Approved per-file budgets: "
        f"{json.dumps(_implementation_plan_budget(plan), ensure_ascii=False)}. "
        "Changed-line counts include both added and removed diff lines; every line of "
        "a newly created file counts as changed. Hunk counts are the generated Git "
        "diff hunk count. Safeplane also preflights every declared check against the "
        "candidate patch in the isolated network-disabled check container before "
        "accepting final. If the validation error includes check stdout or stderr, "
        "repair the implementation so the exact declared argv passes; do not change "
        "the approved plan or command. Reduce the implementation to fit the approved "
        "plan; do not ask Safeplane to enlarge the budget. For modified files, copy narrow "
        "old_text snippets exactly from content returned by repository tools; each "
        "must match exactly once. For created files, use empty old_text and the "
        "complete new file. For deleted files, use the complete current file as "
        "old_text and empty new_text."
        + import_failure_guidance
        + budget_failure_guidance
    )


def _candidate_check_expected_files(
    *,
    plan: ImplementationPlan,
    repository_root: Path,
) -> dict[str, str | None]:
    expected: dict[str, str | None] = {}
    create_paths = set(plan.files_to_create)
    for path in sorted(_planned_implementation_operations(plan)):
        candidate = _resolve_implementation_path(repository_root, path)
        if path in create_paths:
            if candidate.exists():
                raise DeveloperPipelineError(
                    f"candidate check expected a new path but it already exists: {path}"
                )
            expected[path] = None
            continue
        if not candidate.is_file() or candidate.is_symlink():
            raise DeveloperPipelineError(
                f"candidate check baseline path is not a regular file: {path}"
            )
        expected[path] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return expected


def _read_candidate_check_output(
    *,
    store: DeveloperPipelineStore,
    inline: Any,
    ref: Any,
    max_bytes: int = 6000,
) -> str:
    if isinstance(inline, str) and inline:
        return inline[:max_bytes]
    if not isinstance(ref, str) or not ref:
        return ""
    candidate = (store.safeplane_home / ref).resolve(strict=False)
    try:
        candidate.relative_to(store.safeplane_home.resolve())
    except ValueError:
        return ""
    if not candidate.is_file() or candidate.is_symlink():
        return ""
    try:
        return candidate.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _validate_candidate_implementation_checks(
    *,
    contract: dict[str, Any],
    plan: ImplementationPlan,
    patch: ImplementationPatch,
    repository_root: Path,
    call_stage_tool: StageToolCaller | None,
    trace: TraceWriter,
    store: DeveloperPipelineStore,
) -> None:
    if call_stage_tool is None:
        raise DeveloperPipelineError(
            "candidate implementation checks require the harness MCP tool caller"
        )

    expected_files = _candidate_check_expected_files(
        plan=plan,
        repository_root=repository_root,
    )
    artifact_refs: list[str] = []
    for argv in plan.test_commands:
        profile_id, arguments = _resolve_check_profile(contract, argv)
        output = call_stage_tool(
            "implementation_candidate_checks",
            None,
            "dev-check",
            "dev_check_run",
            {
                "profile_id": profile_id,
                "arguments": arguments,
                "expected_files": expected_files,
                "candidate_patch": patch.unified_diff,
            },
            None,
            None,
        )
        status = str(output.get("status") or "failed")
        for ref in (output.get("stdout_ref"), output.get("stderr_ref"), output.get("evidence_ref")):
            if ref:
                artifact_refs.append(str(ref))
        if status == "passed":
            continue
        if status not in {"failed", "timed_out"}:
            raise DeveloperPipelineError(
                f"candidate implementation check returned invalid status: {status}"
            )
        stdout = _read_candidate_check_output(
            store=store,
            inline=output.get("stdout"),
            ref=output.get("stdout_ref"),
        ).strip()
        stderr = _read_candidate_check_output(
            store=store,
            inline=output.get("stderr"),
            ref=output.get("stderr_ref"),
        ).strip()
        details = [
            "candidate implementation failed a declared check before final acceptance",
            f"argv={json.dumps(argv, ensure_ascii=False)}",
            f"status={status}",
            f"exit_code={output.get('exit_code')}",
        ]
        if stderr:
            details.append("stderr:\n" + stderr)
        if stdout:
            details.append("stdout:\n" + stdout)
        raise DeveloperPipelineError("; ".join(details))

    trace(
        "developer_pipeline_implementation_candidate_checks_passed",
        {
            "stage_id": "implementation",
            "command_count": len(plan.test_commands),
        },
        {
            "status": "passed",
            "candidate_patch_applied": True,
        },
        sorted(set(artifact_refs)),
        None,
    )


def _run_implementation_agent_loop(
    *,
    contract: dict[str, Any],
    agent: dict[str, Any],
    model_profile: str,
    response_key: str,
    system_prompt: str,
    user_message: str,
    plan: ImplementationPlan,
    repository_root: Path,
    max_attempts: int,
    tool_loop_timeout_seconds: int,
    require_repository_inspection: bool,
    call_stage_model: StageModelCaller,
    call_stage_tool: StageToolCaller | None,
    trace: TraceWriter,
    store: DeveloperPipelineStore,
) -> ImplementationAgentLoopResult:
    """Run model/tool turns until the implementation model explicitly finishes.

    Valid tool calls never consume the model validation retry budget. There is no
    tool-call count limit. The wall-clock deadline is a fail-closed safety boundary;
    reaching it fails the stage rather than manufacturing a final response.
    """

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    deadline = time.monotonic() + tool_loop_timeout_seconds
    invalid_attempts = 0
    model_call_count = 0
    tool_call_count = 0
    successful_inspection_calls = 0
    total_usage: dict[str, Any] | None = None

    trace(
        "developer_pipeline_implementation_tool_loop_started",
        {
            "stage_id": "implementation",
            "timeout_seconds": tool_loop_timeout_seconds,
            "max_validation_attempts": max_attempts,
            "tool_call_limit": None,
        },
        None,
        None,
        None,
    )

    while True:
        if time.monotonic() >= deadline:
            raise DeveloperPipelineError(
                "implementation tool loop exceeded its wall-clock deadline before "
                "the model returned a valid final response"
            )

        call_result = call_stage_model(
            "implementation",
            response_key,
            model_profile,
            messages,
        )
        model_call_count += 1
        total_usage = _accumulate_model_usage(total_usage, call_result.usage)
        content = call_result.content

        try:
            raw = extract_json_object(content)
            proposal_type = raw.get("type")

            if proposal_type == "tool_call":
                tool_call = ImplementationToolCall.model_validate(raw)
                _validate_implementation_tool_call(tool_call, agent=agent)
                tool_call_count += 1

                tool_error: dict[str, str] | None = None
                tool_content: dict[str, Any] = {}
                try:
                    if call_stage_tool is None:
                        raise DeveloperPipelineError(
                            "implementation repository tool caller is unavailable"
                        )
                    tool_content = call_stage_tool(
                        "implementation",
                        "implementation",
                        tool_call.server_id,
                        tool_call.tool_name,
                        tool_call.arguments,
                        None,
                        None,
                    )
                except Exception as exc:
                    tool_error = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }

                if (
                    tool_error is None
                    and tool_call.tool_name in IMPLEMENTATION_INSPECTION_TOOLS
                    and int(tool_content.get("exit_code", 0)) == 0
                ):
                    successful_inspection_calls += 1

                tool_result = {
                    "type": "tool_result",
                    "server_id": tool_call.server_id,
                    "tool_name": tool_call.tool_name,
                    "arguments": tool_call.arguments,
                    "ok": tool_error is None,
                    "result": tool_content if tool_error is None else None,
                    "error": tool_error,
                }
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Safeplane executed the requested MCP tool.\n"
                                "Tool result JSON:\n"
                                + json.dumps(
                                    tool_result,
                                    ensure_ascii=False,
                                    indent=2,
                                    default=str,
                                )
                                + "\n\nRequest another allowed tool if needed. "
                                "Return `type: final` only when implementation is "
                                "complete and grounded in the repository content."
                            ),
                        },
                    ]
                )
                trace(
                    "developer_pipeline_implementation_tool_turn_completed",
                    {
                        "stage_id": "implementation",
                        "tool_call_index": tool_call_count,
                        "server_id": tool_call.server_id,
                        "tool_name": tool_call.tool_name,
                    },
                    {
                        "ok": tool_error is None,
                        "successful_inspection_calls": successful_inspection_calls,
                        "model_call_count": model_call_count,
                    },
                    [
                        str(ref)
                        for ref in (
                            tool_content.get("evidence_ref"),
                            tool_content.get("artifact_ref"),
                        )
                        if ref
                    ],
                    tool_error,
                )
                continue

            if proposal_type != "final":
                raise DeveloperPipelineError(
                    "implementation response type must be either tool_call or final"
                )
            if require_repository_inspection and successful_inspection_calls < 1:
                raise DeveloperPipelineError(
                    "implementation must inspect the repository with at least one "
                    "successful read-only MCP tool call before returning final"
                )

            final = ImplementationFinalResponse.model_validate(raw)
            planned_paths = set(_planned_implementation_operations(plan))
            if set(final.changed_files) != planned_paths:
                raise DeveloperPipelineError(
                    "implementation changed_files must exactly match planned change paths"
                )
            patch = ImplementationPatch(
                implementation_summary_markdown=final.implementation_summary_markdown,
                unified_diff=build_implementation_patch_from_replacements(
                    final.replacements,
                    plan=plan,
                    repository_root=repository_root,
                ),
                changed_files=final.changed_files,
            )
            _validate_implementation_attempt(
                patch,
                plan=plan,
                repository_root=repository_root,
            )
            if require_repository_inspection:
                _validate_candidate_implementation_checks(
                    contract=contract,
                    plan=plan,
                    patch=patch,
                    repository_root=repository_root,
                    call_stage_tool=call_stage_tool,
                    trace=trace,
                    store=store,
                )
            final_call = StageModelCallResult(
                content=call_result.content,
                model=call_result.model,
                usage=total_usage,
                finish_reason=call_result.finish_reason,
            )
            trace(
                "developer_pipeline_implementation_tool_loop_finished",
                {"stage_id": "implementation"},
                {
                    "model_call_count": model_call_count,
                    "tool_call_count": tool_call_count,
                    "successful_inspection_calls": successful_inspection_calls,
                    "retry_count": invalid_attempts,
                },
                None,
                None,
            )
            return ImplementationAgentLoopResult(
                artifact=patch,
                final_call=final_call,
                retry_count=invalid_attempts,
                model_call_count=model_call_count,
                tool_call_count=tool_call_count,
                usage=total_usage,
            )

        except Exception as exc:
            invalid_attempts += 1
            trace(
                "developer_pipeline_stage_attempt_failed",
                {
                    "stage_id": "implementation",
                    "agent_id": "implementation",
                    "attempt": invalid_attempts,
                    "max_attempts": max_attempts,
                    "model_call_count": model_call_count,
                    "tool_call_count": tool_call_count,
                },
                None,
                None,
                {"type": type(exc).__name__, "message": str(exc)},
            )
            store.append_event(
                event="stage_attempt_failed",
                stage_id="implementation",
                data={
                    "attempt": invalid_attempts,
                    "max_attempts": max_attempts,
                    "error_type": type(exc).__name__,
                    "model_call_count": model_call_count,
                    "tool_call_count": tool_call_count,
                },
            )
            if invalid_attempts >= max_attempts:
                raise DeveloperPipelineError(
                    "stage implementation produced no valid output after "
                    f"{max_attempts} attempts: {exc}"
                ) from exc
            messages.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": _implementation_repair_message(exc, plan=plan),
                    },
                ]
            )


def _validate_implementation_patch_applicability(
    patch: str,
    *,
    repository_root: Path,
    timeout_seconds: int = 15,
) -> set[str]:
    """Read-only Git validation for an implementation patch model attempt."""

    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise DeveloperPipelineError(
            f"target repository is unavailable for implementation patch validation: {exc}"
        ) from exc
    if not root.is_dir():
        raise DeveloperPipelineError(
            "target repository is not a directory for implementation patch validation"
        )

    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "apply",
                "--check",
                "--whitespace=nowarn",
                "-",
            ],
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DeveloperPipelineError(
            "Git is unavailable for implementation patch validation"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeveloperPipelineError(
            "implementation patch validation timed out"
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git apply --check failed").strip()
        detail = detail.replace(str(root), "<target-repository>")
        if len(detail) > 2000:
            detail = detail[:2000] + "..."
        raise DeveloperPipelineError(
            "implementation unified_diff is malformed or does not apply cleanly: " + detail
        )

    try:
        parsed = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "apply",
                "--numstat",
                "-z",
                "-",
            ],
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DeveloperPipelineError(
            "Git is unavailable for implementation patch path validation"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeveloperPipelineError(
            "implementation patch path validation timed out"
        ) from exc
    if parsed.returncode != 0:
        detail = (parsed.stderr or parsed.stdout or "git apply --numstat failed").strip()
        raise DeveloperPipelineError(
            "implementation unified_diff paths could not be parsed: " + detail
        )

    records = parsed.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        columns = record.split("\t", 2)
        if len(columns) != 3:
            raise DeveloperPipelineError(
                "implementation unified_diff produced invalid Git numstat output"
            )
        path = columns[2]
        if path:
            validate_relative_repository_path(path)
            paths.add(path)
            index += 1
            continue
        if index + 2 >= len(records):
            raise DeveloperPipelineError(
                "implementation unified_diff produced incomplete rename metadata"
            )
        for renamed_path in (records[index + 1], records[index + 2]):
            validate_relative_repository_path(renamed_path)
            paths.add(renamed_path)
        index += 3

    if not paths:
        raise DeveloperPipelineError(
            "implementation unified_diff does not contain any changed paths"
        )
    return paths



def _implementation_patch_budget_stats(
    patch: str,
) -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    current_path: str | None = None

    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            marker = " b/"
            split_at = line.rfind(marker)
            if split_at < len("diff --git a/"):
                current_path = None
                continue
            current_path = line[split_at + len(marker):]
            stats[current_path] = {
                "changed_lines": 0,
                "hunks": 0,
                "operation": "modified",
            }
            continue

        if current_path is None:
            continue

        if line.startswith("new file mode ") or line == "--- /dev/null":
            stats[current_path]["operation"] = "created"
        elif line.startswith("deleted file mode ") or line == "+++ /dev/null":
            stats[current_path]["operation"] = "deleted"
        elif line.startswith("@@"):
            stats[current_path]["hunks"] = int(stats[current_path]["hunks"]) + 1
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            stats[current_path]["changed_lines"] = (
                int(stats[current_path]["changed_lines"]) + 1
            )

    return stats


def _validate_implementation_patch_budget(
    patch: str,
    *,
    plan: ImplementationPlan,
) -> None:
    stats = _implementation_patch_budget_stats(patch)
    operations = _planned_implementation_operations(plan)
    violations: list[str] = []

    for path in sorted(operations):
        values = stats.get(path)
        if values is None:
            violations.append(f"planned path is absent from patch statistics: {path}")
            continue
        policy = plan.file_change_policy[path]
        changed_lines = int(values["changed_lines"])
        hunks = int(values["hunks"])
        expected_operation = {
            "modify": "modified",
            "create": "created",
            "delete": "deleted",
        }[operations[path]]
        if values["operation"] != expected_operation:
            violations.append(
                f"operation mismatch for {path}: "
                f"{values['operation']} != {expected_operation}"
            )
        if changed_lines > policy.max_changed_lines:
            violations.append(
                f"changed-line budget exceeded for {path}: "
                f"{changed_lines} > {policy.max_changed_lines}"
            )
        if hunks > policy.max_hunks:
            violations.append(
                f"hunk budget exceeded for {path}: "
                f"{hunks} > {policy.max_hunks}"
            )

    if violations:
        raise DeveloperPipelineError(
            "implementation exceeds approved plan budget: " + "; ".join(violations)
        )


def _validate_implementation_attempt(
    patch: ImplementationPatch,
    *,
    plan: ImplementationPlan,
    repository_root: Path,
) -> None:
    planned_paths = (
        set(plan.files_to_modify)
        | set(plan.files_to_create)
        | set(plan.files_to_delete)
    )
    if set(patch.changed_files) != planned_paths:
        raise DeveloperPipelineError(
            "implementation changed_files must exactly match planned change paths"
        )
    patch_paths = _validate_implementation_patch_applicability(
        patch.unified_diff,
        repository_root=repository_root,
    )
    if patch_paths != planned_paths:
        raise DeveloperPipelineError(
            "implementation unified_diff paths must exactly match planned change paths"
        )
    _validate_implementation_patch_budget(patch.unified_diff, plan=plan)


def _stage_config(contract: dict[str, Any], stage_id: str) -> dict[str, Any]:
    stages = contract["developer_pipeline"]["stages"]
    for stage in stages:
        if stage["id"] == stage_id:
            return stage
    raise DeveloperPipelineContractError(f"developer stage not configured: {stage_id}")


def _response_key(
    pipeline_config: dict[str, Any],
    scenario: str,
    stage_id: str,
    *,
    default_key: str | None = None,
) -> str:
    scenario_config = pipeline_config["fake_scenarios"].get(scenario, {})
    overrides = scenario_config.get("stage_response_keys", {})
    return str(overrides.get(stage_id, default_key or stage_id))


def _artifact_payloads_for_prompt(artifacts: dict[str, BaseModel]) -> dict[str, Any]:
    return {name: value.model_dump(mode="json") for name, value in artifacts.items()}


def _write_stage_artifacts(
    store: DeveloperPipelineStore,
    stage_id: str,
    artifact: BaseModel,
) -> dict[str, str]:
    refs: dict[str, str] = {}
    refs[f"{stage_id}.json"] = store.write_json_artifact(f"{stage_id}.json", artifact)

    if isinstance(artifact, DocumentationResult):
        refs[f"{stage_id}.md"] = store.write_text_artifact(
            f"{stage_id}.md",
            f"# Documentation Result\n\n{artifact.summary}",
        )
    elif isinstance(artifact, AnalysisResult):
        refs["requirements.md"] = store.write_text_artifact(
            "requirements.md", artifact.requirements_markdown
        )
        refs["tasks.md"] = store.write_text_artifact(
            "tasks.md", artifact.architecture_tasks_markdown
        )
    elif isinstance(artifact, ImplementationPlan):
        refs["plan.md"] = store.write_text_artifact("plan.md", artifact.developer_plan_markdown)
        refs["check-plan.json"] = store.write_json_artifact(
            "check-plan.json", {"commands": artifact.test_commands}
        )
    elif isinstance(artifact, ImplementationPatch):
        refs["implementation-summary.md"] = store.write_text_artifact(
            "implementation-summary.md", artifact.implementation_summary_markdown
        )
        refs["implementation.patch"] = store.write_text_artifact(
            "implementation.patch", artifact.unified_diff
        )
    elif isinstance(artifact, ReviewResult):
        body = ["# Review", "", f"Verdict: **{artifact.verdict}**", "", artifact.summary]
        if artifact.requested_changes:
            body.extend(["", "## Requested Changes", ""])
            body.extend(f"- {item}" for item in artifact.requested_changes)
        refs["review.md"] = store.write_text_artifact("review.md", "\n".join(body))
    elif isinstance(artifact, PrProposal):
        refs["pr.md"] = store.write_text_artifact(
            "pr.md", f"# {artifact.title}\n\n{artifact.body_markdown}"
        )

    return refs


def _documentation_tool(
    *,
    call_stage_tool: StageToolCaller,
    stage_id: str,
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    approval_id: str | None = None,
    approval_token: str | None = None,
    agent_id: str | None = "documentation",
) -> dict[str, Any]:
    return call_stage_tool(
        stage_id,
        agent_id,
        server_id,
        tool_name,
        arguments,
        approval_id,
        approval_token,
    )


def _apply_documentation_patch(
    *,
    safeplane_home: Path,
    run_id: str,
    stage_id: str,
    response: DocumentationAgentResponse,
    evidence: DocumentationEvidenceBundle,
    repository_root: Path,
    documentation_runtime: dict[str, Any],
    call_stage_tool: StageToolCaller,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    patch = str(response.unified_diff or "")
    patch_files = validate_documentation_response_patch(
        response,
        evidence=evidence,
    )
    validate_documentation_patch_applicability(
        patch,
        repository_root=repository_root,
    )

    proposal = _documentation_tool(
        call_stage_tool=call_stage_tool,
        stage_id=stage_id,
        server_id="dev-workspace",
        tool_name="dev_workspace_propose_patch",
        arguments={"summary": response.summary, "patch": patch},
    )
    proposal_id = str(proposal.get("proposal_id") or "")
    if not proposal_id:
        raise DocumentationAgentError("documentation patch proposal did not receive an id")

    run = load_run(safeplane_home, run_id)
    proposal_record = {
        "proposal_id": proposal_id,
        "patch_ref": proposal.get("artifact_ref"),
        "patch_sha256": sha256_text(patch),
    }
    approval, approval_token = create_patch_approval(
        safeplane_home,
        run=run,
        proposal=proposal_record,
        connector="harness-developer-pipeline-documentation",
    )
    approval = update_patch_approval(
        safeplane_home,
        approval,
        authorization_source="developer_pipeline_plan",
        stage_id=stage_id,
        agent_id="documentation",
    )
    approval_id = str(approval["approval_id"])
    prepare_patch_apply_workspace(
        safeplane_home,
        run_id=run_id,
        approval_id=approval_id,
    )

    budget = documentation_plan_budget(
        patch_files,
        max_changed_lines=int(documentation_runtime["max_changed_lines_per_file"]),
        max_hunks=int(documentation_runtime["max_hunks_per_file"]),
    )
    published = False
    try:
        applied = _documentation_tool(
            call_stage_tool=call_stage_tool,
            stage_id=stage_id,
            server_id="dev-workspace-apply",
            tool_name="dev_workspace_apply_patch",
            arguments={
                "proposal_id": proposal_id,
                "patch": patch,
                "patch_sha256": proposal_record["patch_sha256"],
                "authorization_source": "developer_pipeline_plan",
                "plan_budget": budget,
            },
            approval_id=approval_id,
            approval_token=approval_token,
            agent_id=None,
        )
        changed_files = list(applied.get("changed_files") or [])
        publish_patch_apply_workspace(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
        )
        published = True
        update_patch_approval(
            safeplane_home,
            approval,
            status="applied",
            applied_at=approval_utc_now(),
            changed_files=changed_files,
            evidence_ref=applied.get("evidence_ref"),
            error=None,
        )
        expected_files = {
            str(item["path"]): item.get("after_sha256")
            for item in changed_files
        }
        call_stage_tool(
            f"{stage_id}_visibility",
            None,
            "dev-workspace",
            "dev_workspace_ready",
            {"timeout_seconds": 15, "expected_files": expected_files},
            None,
            None,
        )
        return applied, changed_files
    except Exception as exc:
        if not published:
            cleanup_patch_apply_workspace(
                safeplane_home,
                run_id=run_id,
                approval_id=approval_id,
            )
            update_patch_approval(
                safeplane_home,
                approval,
                status="failed",
                failed_at=approval_utc_now(),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        raise


def _live_documentation_result(
    *,
    safeplane_home: Path,
    run_id: str,
    stage_id: str,
    response: DocumentationAgentResponse,
    evidence: DocumentationEvidenceBundle,
    repository_root: Path,
    documentation_runtime: dict[str, Any],
    call_stage_tool: StageToolCaller,
) -> DocumentationResult:
    applied: dict[str, Any] = {}
    changed_files: list[dict[str, Any]] = []
    if response.changed:
        applied, changed_files = _apply_documentation_patch(
            safeplane_home=safeplane_home,
            run_id=run_id,
            stage_id=stage_id,
            response=response,
            evidence=evidence,
            repository_root=repository_root,
            documentation_runtime=documentation_runtime,
            call_stage_tool=call_stage_tool,
        )

    def call_tool(server_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _documentation_tool(
            call_stage_tool=call_stage_tool,
            stage_id=stage_id,
            server_id=server_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    snapshots = snapshot_documentation(
        paths=response.documentation_files,
        call_tool=call_tool,
    )
    snapshot_paths = {item.path for item in snapshots}
    missing = set(response.documentation_files) - snapshot_paths
    if missing:
        raise DocumentationAgentError(
            "documentation result references files that are absent from the target: "
            + ", ".join(sorted(missing))
        )

    refs = set(evidence.tool_evidence_refs)
    if applied.get("evidence_ref"):
        refs.add(str(applied["evidence_ref"]))
    return DocumentationResult(
        stage=response.stage,
        summary=response.summary,
        documentation_files=response.documentation_files,
        changed=response.changed,
        evidence_notes=response.evidence_notes,
        uncertainties=response.uncertainties,
        skill_source_id=evidence.source_id,
        skill_source_commit=evidence.source_commit,
        skill_files_read=[item.path for item in evidence.skill_files],
        repository_files_read=[item.path for item in evidence.repository_files],
        tool_evidence_refs=sorted(refs),
        patch_proposal_id=str(applied.get("proposal_id") or "") or None,
        patch_sha256=str(applied.get("patch_sha256") or "") or None,
        apply_evidence_ref=str(applied.get("evidence_ref") or "") or None,
        changed_files=changed_files,
        documents=snapshots,
    )



def _implementation_plan_budget(plan: ImplementationPlan) -> list[dict[str, Any]]:
    operations: dict[str, str] = {}
    operations.update({path: "modified" for path in plan.files_to_modify})
    operations.update({path: "created" for path in plan.files_to_create})
    operations.update({path: "deleted" for path in plan.files_to_delete})
    return [
        {
            "path": path,
            "operation": operations[path],
            "max_changed_lines": plan.file_change_policy[path].max_changed_lines,
            "max_hunks": plan.file_change_policy[path].max_hunks,
        }
        for path in sorted(operations)
    ]


def _apply_implementation_patch(
    *,
    safeplane_home: Path,
    run_id: str,
    patch: ImplementationPatch,
    plan: ImplementationPlan,
    call_stage_tool: StageToolCaller,
) -> ImplementationApplyResult:
    proposal = call_stage_tool(
        "implementation",
        "implementation",
        "dev-workspace",
        "dev_workspace_propose_patch",
        {
            "summary": patch.implementation_summary_markdown,
            "patch": patch.unified_diff,
        },
        None,
        None,
    )
    proposal_id = str(proposal.get("proposal_id") or "")
    if not proposal_id:
        raise DeveloperPipelineError("implementation patch proposal did not receive an id")

    run = load_run(safeplane_home, run_id)
    patch_sha256 = sha256_text(patch.unified_diff)
    approval, approval_token = create_patch_approval(
        safeplane_home,
        run=run,
        proposal={
            "proposal_id": proposal_id,
            "patch_ref": proposal.get("artifact_ref"),
            "patch_sha256": patch_sha256,
        },
        connector="harness-developer-pipeline-implementation",
    )
    approval = update_patch_approval(
        safeplane_home,
        approval,
        authorization_source="developer_pipeline_plan",
        stage_id="implementation",
        agent_id="implementation",
    )
    approval_id = str(approval["approval_id"])
    prepare_patch_apply_workspace(
        safeplane_home,
        run_id=run_id,
        approval_id=approval_id,
    )
    published = False
    try:
        applied = call_stage_tool(
            "implementation",
            None,
            "dev-workspace-apply",
            "dev_workspace_apply_patch",
            {
                "proposal_id": proposal_id,
                "patch": patch.unified_diff,
                "patch_sha256": patch_sha256,
                "authorization_source": "developer_pipeline_plan",
                "plan_budget": _implementation_plan_budget(plan),
            },
            approval_id,
            approval_token,
        )
        changed_files = list(applied.get("changed_files") or [])
        changed_paths = {str(item.get("path") or "") for item in changed_files}
        expected_paths = set(patch.changed_files)
        if changed_paths != expected_paths:
            raise DeveloperPipelineError(
                "applied implementation paths do not exactly match the implementation artifact"
            )
        budget_result = dict(applied.get("plan_budget_result") or {})
        if budget_result.get("status") != "passed":
            raise DeveloperPipelineError("implementation patch did not pass the plan budget")
        evidence_ref = str(applied.get("evidence_ref") or applied.get("tool_evidence_path") or "")
        if not evidence_ref:
            raise DeveloperPipelineError("implementation apply evidence is missing")
        publish_patch_apply_workspace(
            safeplane_home,
            run_id=run_id,
            approval_id=approval_id,
        )
        published = True
        update_patch_approval(
            safeplane_home,
            approval,
            status="applied",
            applied_at=approval_utc_now(),
            changed_files=changed_files,
            evidence_ref=evidence_ref,
            error=None,
        )
        expected_files = {
            str(item["path"]): item.get("after_sha256")
            for item in changed_files
        }
        visible = call_stage_tool(
            "implementation_visibility",
            None,
            "dev-workspace",
            "dev_workspace_ready",
            {"timeout_seconds": 15, "expected_files": expected_files},
            None,
            None,
        )
        visibility_evidence_ref = str(visible.get("evidence_ref") or "") or None
        return ImplementationApplyResult(
            proposal_id=proposal_id,
            patch_sha256=patch_sha256,
            authorization_source="developer_pipeline_plan",
            changed_files=changed_files,
            evidence_ref=evidence_ref,
            visibility_evidence_ref=visibility_evidence_ref,
            plan_budget_result=budget_result,
        )
    except Exception as exc:
        if not published:
            cleanup_patch_apply_workspace(
                safeplane_home,
                run_id=run_id,
                approval_id=approval_id,
            )
            update_patch_approval(
                safeplane_home,
                approval,
                status="failed",
                failed_at=approval_utc_now(),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        raise


def _validate_planned_check_commands(
    *,
    contract: dict[str, Any],
    plan: ImplementationPlan,
    repository_root: Path,
) -> None:
    profiles = ((contract.get("developer_tools") or {}).get("command_profiles") or {})
    if not isinstance(profiles, dict) or not profiles:
        raise DeveloperPipelineContractError(
            "developer workflow must define command profiles before planning"
        )

    repository_root = repository_root.resolve()
    planned_create = set(plan.files_to_create)
    planned_modify = set(plan.files_to_modify)
    planned_delete = set(plan.files_to_delete)

    for argv in plan.test_commands:
        profile_id, arguments = _resolve_check_profile(contract, argv)
        profile = profiles.get(profile_id)
        if not isinstance(profile, dict):
            raise DeveloperPipelineContractError(
                f"invalid developer command profile: {profile_id}"
            )
        if not arguments:
            raise DeveloperPipelineError(
                f"declared check command requires a repository script path: {argv!r}"
            )

        script = arguments[0]
        validate_relative_repository_path(script)
        raw_path = Path(script)
        if script.startswith("-"):
            raise DeveloperPipelineError(
                f"declared check script path must not start with '-': {script}"
            )

        allowed_roots = {str(item) for item in profile.get("allowed_roots") or []}
        if not raw_path.parts or raw_path.parts[0] not in allowed_roots:
            raise DeveloperPipelineError(
                "declared check script must be below one of the profile roots "
                f"{sorted(allowed_roots)}: {script}"
            )
        allowed_suffixes = {str(item) for item in profile.get("allowed_suffixes") or []}
        if raw_path.suffix not in allowed_suffixes:
            raise DeveloperPipelineError(
                "declared check script has a disallowed extension "
                f"for profile {profile_id}: {script}"
            )
        if script in planned_delete:
            raise DeveloperPipelineError(
                f"declared check script cannot be planned for deletion: {script}"
            )

        resolved = (repository_root / raw_path).resolve(strict=False)
        if not resolved.is_relative_to(repository_root):
            raise DeveloperPipelineError(
                f"declared check script path escapes the repository: {script}"
            )

        if script in planned_create:
            if resolved.exists():
                raise DeveloperPipelineError(
                    f"declared check script is listed for creation but already exists: {script}"
                )
            continue

        if script in planned_modify:
            if not resolved.is_file() or resolved.is_symlink():
                raise DeveloperPipelineError(
                    "declared check script is listed for modification but is not a "
                    f"regular file: {script}"
                )
            continue

        if resolved.is_file() and not resolved.is_symlink():
            continue

        raise DeveloperPipelineError(
            "declared check script must already exist as a regular repository file "
            "or be included in files_to_create/files_to_modify: "
            f"{script}"
        )


def _is_declared_check_script_path(
    *,
    contract: dict[str, Any],
    path: str,
) -> bool:
    profiles = ((contract.get("developer_tools") or {}).get("command_profiles") or {})
    normalized = path.replace("\\", "/")
    suffix = PurePosixPath(normalized).suffix
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        allowed_roots = [
            str(item).strip("/")
            for item in profile.get("allowed_roots") or []
            if str(item).strip("/")
        ]
        allowed_suffixes = {str(item) for item in profile.get("allowed_suffixes") or []}
        if suffix not in allowed_suffixes:
            continue
        if any(normalized == root or normalized.startswith(f"{root}/") for root in allowed_roots):
            return True
    return False


def _validate_plan_against_operator_constraints(
    *,
    contract: dict[str, Any],
    task: str,
    plan: ImplementationPlan,
) -> None:
    constraints = _extract_operator_file_constraints(task)
    changed_paths = sorted(
        set(plan.files_to_modify) | set(plan.files_to_create) | set(plan.files_to_delete)
    )
    violations: list[str] = []

    if constraints.allowed_change_paths is not None:
        allowed_by_casefold = {
            path.casefold(): path for path in constraints.allowed_change_paths
        }
        outside_scope = [
            path for path in changed_paths if path.casefold() not in allowed_by_casefold
        ]
        if outside_scope:
            violations.append(
                "paths outside explicit only-scope "
                f"{sorted(constraints.allowed_change_paths)}: {outside_scope}"
            )

    if constraints.prohibit_new_files and plan.files_to_create:
        violations.append(f"new files were forbidden: {sorted(plan.files_to_create)}")

    if constraints.prohibit_file_deletions and plan.files_to_delete:
        violations.append(f"file deletions were forbidden: {sorted(plan.files_to_delete)}")

    if constraints.prohibit_check_script_changes:
        check_script_changes = [
            path
            for path in changed_paths
            if _is_declared_check_script_path(contract=contract, path=path)
        ]
        if check_script_changes:
            violations.append(
                "check-script changes were forbidden: "
                f"{sorted(check_script_changes)}"
            )

    if violations:
        raise DeveloperPipelineError(
            "implementation plan contradicts explicit operator file constraints: "
            + "; ".join(violations)
        )


def _resolve_check_profile(contract: dict[str, Any], argv: list[str]) -> tuple[str, list[str]]:
    if not argv:
        raise DeveloperPipelineError("declared check command is empty")
    profiles = ((contract.get("developer_tools") or {}).get("command_profiles") or {})
    matches = [
        str(profile_id)
        for profile_id, profile in profiles.items()
        if isinstance(profile, dict) and str(profile.get("executable") or "") == argv[0]
    ]
    if len(matches) != 1:
        raise DeveloperPipelineError(
            f"declared check executable must match exactly one command profile: {argv[0]!r}"
        )
    return matches[0], argv[1:]


def _run_declared_checks(
    *,
    contract: dict[str, Any],
    store: DeveloperPipelineStore,
    plan: ImplementationPlan,
    implementation_apply: ImplementationApplyResult,
    call_stage_tool: StageToolCaller,
) -> CheckResult:
    results: list[CheckCommandResult] = []
    failed = False
    expected_files = {
        str(item["path"]): item.get("after_sha256")
        for item in implementation_apply.changed_files
    }
    for argv in plan.test_commands:
        profile_id, arguments = _resolve_check_profile(contract, argv)
        output = call_stage_tool(
            "checks",
            None,
            "dev-check",
            "dev_check_run",
            {
                "profile_id": profile_id,
                "arguments": arguments,
                "expected_files": expected_files,
            },
            None,
            None,
        )
        status = str(output.get("status") or "failed")
        if status not in {"passed", "failed", "timed_out"}:
            raise DeveloperPipelineError(f"invalid controlled check status: {status}")
        failed = failed or status != "passed"
        results.append(
            CheckCommandResult(
                profile_id=profile_id,
                argv=argv,
                status=status,
                exit_code=output.get("exit_code"),
                duration_ms=int(output.get("duration_ms") or 0),
                stdout_ref=output.get("stdout_ref"),
                stderr_ref=output.get("stderr_ref"),
                evidence_ref=output.get("evidence_ref"),
                network_policy=output.get("network_policy"),
            )
        )
    return CheckResult(
        mode="controlled",
        status="failed" if failed else "passed",
        command_results=results,
        summary=(
            "No repository checks were declared; deterministic scope, patch, and review "
            "validation remain in force."
            if not plan.test_commands
            else (
                "One or more declared checks failed or timed out."
                if failed
                else "All declared checks passed through the controlled MCP execution boundary."
            )
        ),
    )


def _restore_completed_artifacts(store: DeveloperPipelineStore) -> dict[str, BaseModel]:
    restored: dict[str, BaseModel] = {}
    artifact_specs: list[tuple[str, str, type[BaseModel]]] = [
        ("request.json", "developer_request", DeveloperRequestArtifact),
        ("repository-context.json", "repository_context", RepositoryContextArtifact),
        ("baseline_documentation.json", "baseline_documentation", DocumentationResult),
        ("analysis.json", "analysis", AnalysisResult),
        ("planning.json", "implementation_plan", ImplementationPlan),
        ("implementation.json", "implementation_patch", ImplementationPatch),
        ("implementation-apply.json", "implementation_apply", ImplementationApplyResult),
        ("checks.json", "check_result", CheckResult),
        ("final_documentation.json", "final_documentation", DocumentationResult),
        ("review.json", "review_result", ReviewResult),
        ("pr.json", "pr_proposal", PrProposal),
    ]
    for filename, key, model in artifact_specs:
        path = store.pipeline_dir / filename
        if path.exists():
            restored[key] = model.model_validate_json(path.read_text(encoding="utf-8"))
    return restored


def run_developer_pipeline(
    *,
    contract: dict[str, Any],
    config_path: Path,
    safeplane_home: Path,
    run_id: str,
    operator_message: str,
    workspace_manifest: dict[str, Any],
    call_stage_model: StageModelCaller,
    trace: TraceWriter,
    call_stage_tool: StageToolCaller | None = None,
) -> DeveloperPipelineResult:
    validate_developer_pipeline_contract(contract)
    pipeline_config = contract["developer_pipeline"]
    scenario, task = parse_fake_scenario(operator_message, pipeline_config)
    store = DeveloperPipelineStore(
        safeplane_home=safeplane_home,
        run_id=run_id,
        fake_scenario=scenario,
    )

    target = workspace_manifest.get("target") or {}
    external_sources = workspace_manifest.get("external_sources") or {}
    archdoc = external_sources.get("archdoc") or {}
    workspace_kind = str(workspace_manifest.get("workspace_kind") or "local_snapshot")
    full_execution_enabled = workspace_kind == "git_multi_repository"

    if store.resumed:
        artifacts = _restore_completed_artifacts(store)
        request_artifact = artifacts.get("developer_request")
        repository_context = artifacts.get("repository_context")
        if not isinstance(request_artifact, DeveloperRequestArtifact):
            raise DeveloperPipelineTransitionError("resumed pipeline is missing request.json")
        if not isinstance(repository_context, RepositoryContextArtifact):
            raise DeveloperPipelineTransitionError(
                "resumed pipeline is missing repository-context.json"
            )
    else:
        request_artifact = DeveloperRequestArtifact(task=task, fake_scenario=scenario)
        repository_context = RepositoryContextArtifact(
            repository_profile=str(target.get("profile_id") or "local-snapshot"),
            workspace_kind=workspace_kind,
            repository_root=str(workspace_manifest["repository_root"]),
            base_commit=target.get("resolved_commit"),
            external_skill_commit=archdoc.get("resolved_commit"),
            external_sources={
                str(source_id): str(source.get("resolved_commit"))
                for source_id, source in external_sources.items()
                if source.get("resolved_commit")
            },
            note=(
                "An isolated Git checkout and exact target and external-source commits "
                "were prepared. External skill content is exposed only to documentation."
                if workspace_kind == "git_multi_repository"
                else (
                    "Compatibility mode uses a local read-only snapshot; full patch application "
                    "and controlled checks require a named Git repository profile."
                )
            ),
        )
        request_ref = store.write_json_artifact("request.json", request_artifact)
        context_ref = store.write_json_artifact("repository-context.json", repository_context)
        store.transition(
            stage_id="repositories",
            target_state="repositories_ready",
            artifact_refs={"request.json": request_ref, "repository-context.json": context_ref},
        )
        artifacts = {
            "developer_request": request_artifact,
            "repository_context": repository_context,
        }

    observed_modes = {item.model_mode for item in store.state.agent_runs if item.model_mode}
    documentation_runtime = pipeline_config["documentation_runtime"]
    live_documentation_enabled = (
        workspace_kind == "git_multi_repository"
        and bool(repository_context.external_skill_commit)
    )
    if full_execution_enabled and call_stage_tool is None:
        raise DeveloperPipelineError(
            "the single-pass developer workflow requires the harness MCP tool caller"
        )

    model_stage_ids = [
        "baseline_documentation",
        "analysis",
        "planning",
        "implementation",
        "final_documentation",
        "review",
        "pr",
    ]

    for stage_id in model_stage_ids:
        if stage_id in store.state.completed_stages:
            continue

        if stage_id == "final_documentation" and "checks" not in store.state.completed_stages:
            plan = artifacts.get("implementation_plan")
            assert isinstance(plan, ImplementationPlan)
            if full_execution_enabled:
                assert call_stage_tool is not None
                implementation_apply = artifacts.get("implementation_apply")
                if not isinstance(implementation_apply, ImplementationApplyResult):
                    raise DeveloperPipelineError(
                        "controlled checks require implementation apply evidence"
                    )
                check_result = _run_declared_checks(
                    contract=contract,
                    store=store,
                    plan=plan,
                    implementation_apply=implementation_apply,
                    call_stage_tool=call_stage_tool,
                )
            else:
                command_results = [
                    CheckCommandResult(
                        profile_id="compatibility_fake",
                        argv=argv,
                        status="passed",
                        exit_code=0,
                        duration_ms=1,
                    )
                    for argv in plan.test_commands
                ]
                check_result = CheckResult(
                    mode="controlled",
                    status="passed",
                    command_results=command_results,
                    summary="Compatibility fake evidence; full controlled execution requires a named repository profile.",
                )
            check_ref = store.write_json_artifact("checks.json", check_result)
            check_refs = {"checks.json": check_ref}
            for index, item in enumerate(check_result.command_results, start=1):
                if item.stdout_ref:
                    check_refs[f"check-{index}.stdout"] = item.stdout_ref
                if item.stderr_ref:
                    check_refs[f"check-{index}.stderr"] = item.stderr_ref
                if item.evidence_ref:
                    check_refs[f"check-{index}.evidence"] = item.evidence_ref
            target_state = "checks_passed" if check_result.status == "passed" else "failed"
            store.transition(
                stage_id="checks",
                target_state=target_state,
                artifact_refs=check_refs,
            )
            artifacts["check_result"] = check_result
            store.update_run_summary(
                check_summary={
                    "status": check_result.status,
                    "commands": [item.model_dump(mode="json") for item in check_result.command_results],
                }
            )
            trace(
                "developer_pipeline_checks_completed",
                {"stage_id": "checks"},
                {
                    "status": check_result.status,
                    "command_count": len(check_result.command_results),
                    "controlled": full_execution_enabled,
                },
                sorted(check_refs.values()),
                None,
            )
            if check_result.status != "passed":
                raise DeveloperPipelineError(
                    "developer pipeline stopped because a required check failed or timed out"
                )

        if stage_id == "pr" and store.state.current_state == "review_changes_requested":
            return DeveloperPipelineResult(
                final_message=(
                    "Developer pipeline stopped with REQUEST_CHANGES. No automatic rework or "
                    "pull-request proposal was started."
                ),
                current_state=store.state.current_state,
                pipeline_ref=store.relative_ref(store.state_path),
            )

        stage_started_monotonic = time.monotonic()
        stage = _stage_config(contract, stage_id)
        agent_id = str(stage["agent"])
        agent = contract["agents"][agent_id]
        prompt_config = agent["prompt"]
        prompt_path = resolve_repo_resource(config_path, str(prompt_config["path"]))
        frontmatter, system_prompt = parse_markdown_with_frontmatter(prompt_path)
        prompt_id = str(frontmatter.get("id") or frontmatter.get("prompt_id") or "")
        prompt_version = str(frontmatter.get("version") or "")
        if prompt_id != prompt_config["id"] or prompt_version != prompt_config["version"]:
            raise DeveloperPipelineContractError(
                f"prompt metadata mismatch for agent {agent_id}: {prompt_path}"
            )

        model_profile = str(agent["model_profile"])
        configured_model = contract["model_profiles"][model_profile].get("litellm_model")
        prompt_artifacts = _artifact_payloads_for_prompt(artifacts)
        documentation_evidence: DocumentationEvidenceBundle | None = None
        documentation_evidence_ref: str | None = None
        documentation_patch_ref: str | None = None
        default_response_key: str | None = None
        existing_documentation_paths: set[str] = set()

        if stage_id in {"baseline_documentation", "final_documentation"} and live_documentation_enabled:
            assert call_stage_tool is not None
            stage_kind: Literal["baseline", "final"] = (
                "baseline" if stage_id == "baseline_documentation" else "final"
            )

            def documentation_call_tool(
                server_id: str, tool_name: str, arguments: dict[str, Any]
            ) -> dict[str, Any]:
                return _documentation_tool(
                    call_stage_tool=call_stage_tool,
                    stage_id=stage_id,
                    server_id=server_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )

            documentation_evidence = collect_documentation_evidence(
                stage=stage_kind,
                expected_source_commit=str(repository_context.external_skill_commit),
                config=documentation_runtime,
                call_tool=documentation_call_tool,
            )
            documentation_evidence_ref = store.write_json_artifact(
                f"{stage_id}-evidence.json",
                documentation_evidence.artifact_payload(),
            )
            prompt_artifacts["documentation_evidence"] = documentation_evidence.prompt_payload()
            existing_documentation_paths = {
                item.path
                for item in documentation_evidence.repository_files
                if item.path in set(documentation_evidence.target_document_paths)
            }
            if stage_id == "baseline_documentation":
                default_response_key = (
                    "baseline_documentation_preserve"
                    if existing_documentation_paths
                    else "baseline_documentation_live"
                )
            else:
                default_response_key = "final_documentation_live"

        response_key = _response_key(
            pipeline_config,
            scenario,
            stage_id,
            default_key=default_response_key,
        )
        user_message = _render_stage_user_message(
            stage_id=stage_id,
            task=task,
            input_artifacts=prompt_artifacts,
        )

        trace(
            "developer_pipeline_stage_started",
            {
                "stage_id": stage_id,
                "agent_id": agent_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_profile": model_profile,
                "response_key": response_key,
            },
            None,
            None,
            None,
        )
        store.append_event(
            event="stage_started",
            stage_id=stage_id,
            data={
                "agent_id": agent_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_profile": model_profile,
            },
        )

        max_attempts = int(agent["max_model_attempts"])
        call_result: StageModelCallResult | None = None
        documentation_response: DocumentationAgentResponse | None = None
        artifact: BaseModel | None = None
        retry_count = 0
        model_call_count = 0
        tool_call_count = 0
        schema_name = str(stage["output_schema"])
        documentation_repair_message: str | None = None
        planning_repair_history: list[dict[str, str]] = []

        if stage_id == "analysis":
            loop_result = _run_analysis_agent_loop(
                agent=agent,
                model_profile=model_profile,
                response_key=response_key,
                system_prompt=system_prompt,
                user_message=user_message,
                max_attempts=max_attempts,
                call_stage_model=call_stage_model,
                call_stage_tool=call_stage_tool,
                trace=trace,
                store=store,
            )
            call_result = loop_result.final_call
            artifact = loop_result.artifact
            retry_count = loop_result.retry_count
            model_call_count = loop_result.model_call_count
            tool_call_count = loop_result.tool_call_count
            observed_modes.add(str(call_result.model.get("mode") or ""))
        elif stage_id == "implementation":
            plan = artifacts.get("implementation_plan")
            if not isinstance(plan, ImplementationPlan):
                raise DeveloperPipelineError(
                    "implementation tool loop requires the normalized implementation plan"
                )
            loop_result = _run_implementation_agent_loop(
                contract=contract,
                agent=agent,
                model_profile=model_profile,
                response_key=response_key,
                system_prompt=system_prompt,
                user_message=user_message,
                plan=plan,
                repository_root=Path(str(workspace_manifest["repository_root"])),
                max_attempts=max_attempts,
                tool_loop_timeout_seconds=int(agent["tool_loop_timeout_seconds"]),
                require_repository_inspection=full_execution_enabled,
                call_stage_model=call_stage_model,
                call_stage_tool=call_stage_tool,
                trace=trace,
                store=store,
            )
            call_result = loop_result.final_call
            artifact = loop_result.artifact
            retry_count = loop_result.retry_count
            model_call_count = loop_result.model_call_count
            tool_call_count = loop_result.tool_call_count
            model_mode = str(call_result.model.get("mode") or "")
            observed_modes.add(model_mode)
        else:
            for attempt_index in range(max_attempts):
                response_content = ""
                try:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                        *planning_repair_history,
                    ]
                    if documentation_repair_message is not None:
                        messages.append(
                            {"role": "user", "content": documentation_repair_message}
                        )
                    call_result = call_stage_model(
                        stage_id,
                        response_key,
                        model_profile,
                        messages,
                    )
                    model_call_count += 1
                    model_mode = str(call_result.model.get("mode") or "")
                    response_content = call_result.content
                    if documentation_evidence is not None:
                        response_content = expand_documentation_placeholders(
                            response_content,
                            evidence=documentation_evidence,
                            repository_profile=repository_context.repository_profile,
                            prompt_id=prompt_id,
                            prompt_version=prompt_version,
                        )
                    raw = extract_json_object(response_content)
                    if documentation_evidence is not None:
                        raw = normalize_documentation_response_metadata(dict(raw))
                        replacements_present = "replacements" in raw
                        if raw.get("changed") is True and replacements_present:
                            if raw.get("unified_diff") not in {None, ""}:
                                raise DocumentationAgentError(
                                    "documentation response must use either replacements or "
                                    "unified_diff, not both"
                                )
                            raw["unified_diff"] = build_documentation_patch_from_replacements(
                                raw.pop("replacements"),
                                repository_root=Path(
                                    str(workspace_manifest["repository_root"])
                                ),
                                allowed_paths=documentation_evidence.target_document_paths,
                            )
                        elif replacements_present:
                            replacements = raw.pop("replacements")
                            if replacements is not None and replacements != []:
                                raise DocumentationAgentError(
                                    "unchanged documentation must not include replacements"
                                )
                        if raw.get("changed") is True and isinstance(
                            raw.get("unified_diff"), str
                        ):
                            raw["unified_diff"] = normalize_documentation_patch(
                                str(raw["unified_diff"])
                            )
                            raw["documentation_files"] = [
                                item.path
                                for item in parse_documentation_patch(
                                    str(raw["unified_diff"])
                                )
                            ]
                        if (
                            model_mode == "fake"
                            and raw.get("changed") is False
                            and existing_documentation_paths
                        ):
                            raw = dict(raw)
                            raw["documentation_files"] = sorted(existing_documentation_paths)
                        documentation_response = DocumentationAgentResponse.model_validate(raw)
                        expected_stage = (
                            "baseline" if stage_id == "baseline_documentation" else "final"
                        )
                        if documentation_response.stage != expected_stage:
                            raise DeveloperPipelineError(
                                f"{stage_id} result has wrong documentation stage"
                            )
                        validate_documentation_response_patch(
                            documentation_response,
                            evidence=documentation_evidence,
                        )
                        if documentation_response.changed:
                            validate_documentation_patch_applicability(
                                str(documentation_response.unified_diff or ""),
                                repository_root=Path(
                                    str(workspace_manifest["repository_root"])
                                ),
                            )
                    else:
                        artifact_model = ARTIFACT_MODELS[schema_name]
                        artifact = artifact_model.model_validate(raw)
                        if stage_id == "planning":
                            assert isinstance(artifact, ImplementationPlan)
                            _validate_plan_against_operator_constraints(
                                contract=contract,
                                task=task,
                                plan=artifact,
                            )
                            _validate_planned_check_commands(
                                contract=contract,
                                plan=artifact,
                                repository_root=Path(
                                    str(workspace_manifest["repository_root"])
                                ),
                            )
                    retry_count = attempt_index
                    observed_modes.add(model_mode)
                    break
                except Exception as exc:
                    retry_count = attempt_index
                    if documentation_evidence is not None:
                        documentation_repair_message = _documentation_repair_message(exc)
                    elif stage_id == "planning":
                        if response_content:
                            planning_repair_history.append(
                                {"role": "assistant", "content": response_content}
                            )
                        planning_repair_history.append(
                            {
                                "role": "user",
                                "content": _planning_repair_message(
                                    exc,
                                    contract=contract,
                                ),
                            }
                        )
                    trace(
                        "developer_pipeline_stage_attempt_failed",
                        {
                            "stage_id": stage_id,
                            "agent_id": agent_id,
                            "attempt": attempt_index + 1,
                            "max_attempts": max_attempts,
                        },
                        None,
                        None,
                        {"type": type(exc).__name__, "message": str(exc)},
                    )
                    store.append_event(
                        event="stage_attempt_failed",
                        stage_id=stage_id,
                        data={
                            "attempt": attempt_index + 1,
                            "max_attempts": max_attempts,
                            "error_type": type(exc).__name__,
                        },
                    )
                    if attempt_index + 1 >= max_attempts:
                        raise DeveloperPipelineError(
                            f"stage {stage_id} produced no valid output after {max_attempts} attempts: {exc}"
                        ) from exc
        assert call_result is not None
        model_mode = str(call_result.model.get("mode") or "")
        if documentation_evidence is not None:
            assert call_stage_tool is not None
            assert documentation_response is not None
            if documentation_response.changed and documentation_response.unified_diff:
                documentation_patch_ref = store.write_text_artifact(
                    f"{stage_id}.patch", documentation_response.unified_diff
                )
            artifact = _live_documentation_result(
                safeplane_home=safeplane_home,
                run_id=run_id,
                stage_id=stage_id,
                response=documentation_response,
                evidence=documentation_evidence,
                repository_root=Path(str(workspace_manifest["repository_root"])),
                documentation_runtime=documentation_runtime,
                call_stage_tool=call_stage_tool,
            )
        assert artifact is not None

        if stage_id == "baseline_documentation" and isinstance(artifact, DocumentationResult):
            if artifact.stage != "baseline":
                raise DeveloperPipelineError("baseline documentation result has wrong stage")
            artifact_key = "baseline_documentation"
            target_state = "documentation_ready"
        elif stage_id == "analysis" and isinstance(artifact, AnalysisResult):
            artifact_key = "analysis"
            target_state = "analysis_ready"
        elif stage_id == "planning" and isinstance(artifact, ImplementationPlan):
            artifact_key = "implementation_plan"
            target_state = "plan_ready"
        elif stage_id == "implementation" and isinstance(artifact, ImplementationPatch):
            plan = artifacts.get("implementation_plan")
            assert isinstance(plan, ImplementationPlan)
            planned = set(plan.files_to_modify) | set(plan.files_to_create) | set(plan.files_to_delete)
            if set(artifact.changed_files) != planned:
                raise DeveloperPipelineError(
                    "implementation changed_files must exactly match planned change paths"
                )
            artifact_key = "implementation_patch"
            target_state = "implementation_ready"
        elif stage_id == "final_documentation" and isinstance(artifact, DocumentationResult):
            if artifact.stage != "final":
                raise DeveloperPipelineError("final documentation result has wrong stage")
            artifact_key = "final_documentation"
            target_state = "documentation_reconciled"
        elif stage_id == "review" and isinstance(artifact, ReviewResult):
            artifact_key = "review_result"
            target_state = (
                "review_lgtm" if artifact.verdict == "LGTM" else "review_changes_requested"
            )
        elif stage_id == "pr" and isinstance(artifact, PrProposal):
            artifact_key = "pr_proposal"
            target_state = "pr_ready"
        else:
            raise DeveloperPipelineError(
                f"stage {stage_id} returned incompatible schema {schema_name}"
            )

        refs = _write_stage_artifacts(store, stage_id, artifact)
        if stage_id == "implementation" and full_execution_enabled:
            assert call_stage_tool is not None
            assert isinstance(artifact, ImplementationPatch)
            plan = artifacts.get("implementation_plan")
            assert isinstance(plan, ImplementationPlan)
            implementation_apply = _apply_implementation_patch(
                safeplane_home=safeplane_home,
                run_id=run_id,
                patch=artifact,
                plan=plan,
                call_stage_tool=call_stage_tool,
            )
            apply_ref = store.write_json_artifact(
                "implementation-apply.json", implementation_apply
            )
            refs["implementation-apply.json"] = apply_ref
            refs["implementation-apply-evidence"] = implementation_apply.evidence_ref
            if implementation_apply.visibility_evidence_ref:
                refs["implementation-visibility-evidence"] = (
                    implementation_apply.visibility_evidence_ref
                )
            artifacts["implementation_apply"] = implementation_apply
        if documentation_evidence_ref is not None:
            refs[f"{stage_id}-evidence.json"] = documentation_evidence_ref
        if documentation_patch_ref is not None:
            refs[f"{stage_id}.patch"] = documentation_patch_ref
        usage = call_result.usage or {}
        resolved_configured_model = (
            call_result.model.get("configured_model") or configured_model
        )
        stage_duration_ms = int((time.monotonic() - stage_started_monotonic) * 1000)
        agent_run = AgentRunMetadata(
            stage_id=stage_id,
            agent_id=agent_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_profile=model_profile,
            configured_model=(
                str(resolved_configured_model) if resolved_configured_model else None
            ),
            actual_model=call_result.model.get("actual_model"),
            actual_provider=call_result.model.get("actual_provider"),
            model_mode=model_mode,
            generation_id=call_result.model.get("generation_id"),
            finish_reason=call_result.finish_reason,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            cost=usage.get("cost"),
            duration_ms=stage_duration_ms,
            retry_count=retry_count,
            model_call_count=model_call_count,
            tool_call_count=tool_call_count,
            artifact_refs=sorted(refs.values()),
        )
        store.transition(
            stage_id=stage_id,
            target_state=target_state,
            artifact_refs=refs,
            agent_run=agent_run,
        )
        artifacts[artifact_key] = artifact
        if isinstance(artifact, ReviewResult):
            store.update_run_summary(
                review_verdict=artifact.verdict,
                review_plan_alignment=artifact.plan_alignment,
            )
        if isinstance(artifact, DocumentationResult) and artifact.stage == "final":
            store.update_run_summary(
                documentation_summary={
                    "changed": artifact.changed,
                    "files": artifact.documentation_files,
                    "skill_commit": artifact.skill_source_commit,
                }
            )
        trace(
            "developer_pipeline_stage_completed",
            {
                "stage_id": stage_id,
                "agent_id": agent_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_profile": model_profile,
            },
            {
                "target_state": target_state,
                "model_mode": model_mode,
                "configured_model": resolved_configured_model,
                "actual_model": call_result.model.get("actual_model"),
                "actual_provider": call_result.model.get("actual_provider"),
                "generation_id": call_result.model.get("generation_id"),
                "finish_reason": call_result.finish_reason,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost": usage.get("cost"),
                "duration_ms": stage_duration_ms,
                "model_call_count": model_call_count,
                "tool_call_count": tool_call_count,
                "artifact_count": len(refs),
            },
            sorted(refs.values()),
            None,
        )

        if stage_id == "review" and target_state == "review_changes_requested":
            return DeveloperPipelineResult(
                final_message=(
                    "Developer pipeline stopped with REQUEST_CHANGES. No automatic rework or "
                    "pull-request proposal was started."
                ),
                current_state=store.state.current_state,
                pipeline_ref=store.relative_ref(store.state_path),
            )

    pr = artifacts.get("pr_proposal")
    plan = artifacts.get("implementation_plan")
    check_result = artifacts.get("check_result")
    review_result = artifacts.get("review_result")
    assert isinstance(pr, PrProposal)
    assert isinstance(plan, ImplementationPlan)
    assert isinstance(check_result, CheckResult)
    assert isinstance(review_result, ReviewResult)
    if "remote_approval" not in store.state.completed_stages:
        remote_approval_refs: dict[str, str] = {}
        remote_approval_request = None
        target_remote_metadata = workspace_manifest.get("target") or {}
        if (
            workspace_manifest.get("workspace_kind") == "git_multi_repository"
            and target_remote_metadata.get("remote_write_allowed") is True
            and target_remote_metadata.get("repository_url")
            and (
                target_remote_metadata.get("pull_request_repository")
                or target_remote_metadata.get("repository_name")
            )
            and target_remote_metadata.get("requested_ref")
        ):
            remote_approval_request = build_remote_approval_request(
                safeplane_home=safeplane_home,
                run_id=run_id,
                workspace_manifest=workspace_manifest,
                pr_proposal=pr.model_dump(mode="json"),
                implementation_plan=plan.model_dump(mode="json"),
                check_result=check_result.model_dump(mode="json"),
                review_result=review_result.model_dump(mode="json"),
                created_at=store.state.created_at,
            )
            request_ref = save_remote_approval_request(
                safeplane_home,
                remote_approval_request,
            )
            remote_approval_refs["remote-approval-request.json"] = request_ref
            store.update_run_summary(
                remote_approval_binding={
                    "repository_profile": remote_approval_request.repository_profile,
                    "repository_name": remote_approval_request.repository_name,
                    "credential_profile": remote_approval_request.credential_profile,
                    "draft_pr_creation": remote_approval_request.draft_pr_creation,
                    "base_ref": remote_approval_request.base_ref,
                    "base_commit": remote_approval_request.base_commit,
                    "workspace_tree_sha256": remote_approval_request.workspace_tree_sha256,
                    "pr_proposal_sha256": remote_approval_request.pr_proposal_sha256,
                    "checks_sha256": remote_approval_request.checks_sha256,
                    "review_sha256": remote_approval_request.review_sha256,
                    "branch_name": remote_approval_request.branch_name,
                    "request_ref": request_ref,
                }
            )
        store.transition(
            stage_id="remote_approval",
            target_state="waiting_for_remote_approval",
            artifact_refs=remote_approval_refs,
        )
        store.update_run_summary(
            remote_approval_possible=remote_approval_request is not None
        )
        trace(
            "developer_pipeline_waiting_for_remote_approval",
            {"stage_id": "remote_approval"},
            {
                "title": pr.title,
                "remote_write_performed": False,
                "approval_request_created": remote_approval_request is not None,
                "branch_name": (
                    remote_approval_request.branch_name if remote_approval_request else None
                ),
            },
            [store.relative_ref(store.state_path), *remote_approval_refs.values()],
            None,
        )
    return DeveloperPipelineResult(
        final_message=(
            f"Developer pipeline is waiting_for_remote_approval. Draft PR proposal: {pr.title}. "
            "No branch was pushed and no pull request was created."
        ),
        current_state=store.state.current_state,
        pipeline_ref=store.relative_ref(store.state_path),
    )
