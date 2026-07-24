from __future__ import annotations

import difflib
import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class DocumentationAgentError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentationTextReplacement(StrictModel):
    path: str
    old_text: str
    new_text: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not value.startswith("docs/"):
            raise ValueError(f"documentation path must stay under docs/: {value}")
        return value

    @model_validator(mode="after")
    def validate_replacement(self) -> "DocumentationTextReplacement":
        if self.old_text == self.new_text:
            raise ValueError("documentation replacement must change text")
        return self


class DocumentationAgentResponse(StrictModel):
    stage: Literal["baseline", "final"]
    summary: str = Field(min_length=1)
    documentation_files: list[str]
    changed: bool
    unified_diff: str | None = None
    evidence_notes: list[str]
    uncertainties: list[str]

    @field_validator("documentation_files")
    @classmethod
    def validate_documentation_files(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("documentation_files must not contain duplicates")
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or not value.startswith("docs/"):
                raise ValueError(f"documentation path must stay under docs/: {value}")
        return values

    @model_validator(mode="after")
    def validate_change_payload(self) -> "DocumentationAgentResponse":
        if self.changed:
            if not self.documentation_files:
                raise ValueError("changed documentation requires documentation_files")
            if not self.unified_diff or not self.unified_diff.startswith("diff --git "):
                raise ValueError("changed documentation requires a Git-style unified_diff")
        elif self.unified_diff not in {None, ""}:
            raise ValueError("unchanged documentation must not include unified_diff")
        return self


class DocumentationDocumentSnapshot(StrictModel):
    path: str
    sha256: str
    content: str


class DocumentationEvidenceFile(StrictModel):
    path: str
    sha256: str
    size_bytes: int
    truncated: bool
    chunk_count: int = 1
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_ref: str | None = None
    content: str


class DocumentationEvidenceBundle(StrictModel):
    stage: Literal["baseline", "final"]
    source_id: str
    source_commit: str
    skill_files: list[DocumentationEvidenceFile]
    repository_files: list[DocumentationEvidenceFile]
    repository_tracked_paths: list[str] = Field(default_factory=list)
    repository_skipped_paths: list[str] = Field(default_factory=list)
    repository_complete: bool = True
    target_document_paths: list[str]
    tool_evidence_refs: list[str]

    def prompt_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def artifact_payload(self) -> dict[str, Any]:
        def summarize(item: DocumentationEvidenceFile) -> dict[str, Any]:
            return {
                "path": item.path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "truncated": item.truncated,
                "chunk_count": item.chunk_count,
                "evidence_refs": item.evidence_refs,
                "evidence_ref": item.evidence_ref,
            }

        return {
            "stage": self.stage,
            "source_id": self.source_id,
            "source_commit": self.source_commit,
            "skill_files": [summarize(item) for item in self.skill_files],
            "repository_files": [summarize(item) for item in self.repository_files],
            "repository_tracked_paths": self.repository_tracked_paths,
            "repository_skipped_paths": self.repository_skipped_paths,
            "repository_complete": self.repository_complete,
            "target_document_paths": self.target_document_paths,
            "tool_evidence_refs": self.tool_evidence_refs,
        }


@dataclass(frozen=True)
class DocumentationPatchFile:
    path: str
    operation: Literal["created", "modified", "deleted"]
    changed_lines: int
    hunks: int


DocumentationToolCaller = Callable[[str, str, dict[str, Any]], dict[str, Any]]


SENSITIVE_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)(secrets?|credentials?)(\.|/|$)", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|crt)$", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519)$", re.IGNORECASE),
)

SECRET_CONTENT_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

UNRESOLVED_PLACEHOLDER_PATTERNS = (
    "[Describe",
    "[Insert",
    "[file or module]",
    "[command]",
    "[status]",
    "[verified/inferred]",
)


DEFAULT_TARGET_DOCUMENTS = [
    "docs/REPO_MAP.md",
    "docs/ARCHITECTURE.md",
    "docs/API_SURFACE.md",
    "docs/OPERATIONS.md",
]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_sensitive_repository_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in SENSITIVE_PATH_PATTERNS)


BINARY_FILE_SUFFIXES = {
    ".7z", ".a", ".avi", ".bin", ".bmp", ".bz2", ".class", ".db", ".dll",
    ".dylib", ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg",
    ".mov", ".mp3", ".mp4", ".o", ".otf", ".pdf", ".png", ".pyc", ".so",
    ".sqlite", ".sqlite3", ".tar", ".tgz", ".ttf", ".war", ".webm", ".webp",
    ".woff", ".woff2", ".xz", ".zip",
}


def is_repository_text_path(path: str) -> bool:
    """Return whether a tracked path is eligible for documentation evidence.

    The policy deliberately uses a binary denylist rather than a narrow text
    allowlist so extensionless scripts and uncommon source/configuration files
    remain visible to the documentation agent.
    """

    return PurePosixPath(path).suffix.lower() not in BINARY_FILE_SUFFIXES


def _is_missing_untracked_target(path: str, *, tracked_paths: set[str], error: Exception) -> bool:
    if path in tracked_paths:
        return False
    message = str(error).lower()
    return "file not found" in message or "not a regular file" in message


def _is_oversized_single_line_read(error: Exception) -> bool:
    return bool(
        re.search(
            r"line \d+ exceeds the per-read byte limit",
            str(error),
            flags=re.IGNORECASE,
        )
    )


def _priority_for_repository_path(path: str, targets: set[str]) -> tuple[int, str]:
    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    if path in targets:
        return (0, path)
    if lower.startswith("docs/") and lower.endswith(".md"):
        return (1, path)
    if name.startswith("readme") or name in {"contributing.md", "security.md", "development.md"}:
        return (2, path)
    if name in {
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "requirements.txt",
        "makefile",
        "dockerfile",
        "docker-compose.yml",
        "compose.yml",
        "safeplane.yaml",
    }:
        return (3, path)
    if lower.startswith(("tests/", "test/", "spec/", ".github/workflows/")):
        return (4, path)
    if any(token in name for token in ("main", "app", "server", "cli", "index", "routes", "api")):
        return (5, path)
    if lower.startswith(("src/", "app/", "lib/", "cmd/", "services/")):
        return (6, path)
    return (9, path)


def _read_tool_file(
    *,
    call_tool: DocumentationToolCaller,
    tool_name: str,
    path: str,
    max_bytes: int,
    page_lines: int,
    source_id: str | None = None,
    expected_source_commit: str | None = None,
) -> DocumentationEvidenceFile:
    start_line = 1
    chunks: list[str] = []
    evidence_refs: list[str] = []
    total_bytes = 0
    observed_path = path

    while True:
        remaining = max_bytes - total_bytes
        if remaining <= 0:
            raise DocumentationAgentError(
                f"evidence byte budget was exhausted before EOF: {path}"
            )
        arguments: dict[str, Any] = {
            "path": path,
            "start_line": start_line,
            "max_lines": page_lines,
            "max_bytes": min(1048576, remaining),
        }
        if source_id is not None:
            arguments["source_id"] = source_id
        result = call_tool("dev-workspace", tool_name, arguments)
        if expected_source_commit is not None:
            observed_commit = str(result.get("source_commit") or "")
            if observed_commit != expected_source_commit:
                raise DocumentationAgentError(
                    "external skill commit changed while documentation evidence was collected"
                )

        returned_start = int(result.get("start_line", start_line))
        if returned_start != start_line:
            raise DocumentationAgentError(
                f"MCP read returned the wrong start line for {path}: "
                f"expected {start_line}, got {returned_start}"
            )
        observed_path = str(result.get("path") or path)
        content = str(result.get("content") or "")
        encoded = content.encode("utf-8")
        separator_bytes = 1 if chunks else 0
        if len(encoded) + separator_bytes > remaining:
            raise DocumentationAgentError(f"MCP read exceeded configured byte budget: {path}")
        chunks.append(content)
        total_bytes += len(encoded) + separator_bytes
        evidence_ref = result.get("evidence_ref")
        if evidence_ref:
            evidence_refs.append(str(evidence_ref))

        next_start_line = result.get("next_start_line")
        reported_truncated = bool(result.get("truncated"))
        if next_start_line is None:
            if reported_truncated:
                raise DocumentationAgentError(
                    f"MCP read was truncated without a continuation line: {path}"
                )
            break
        next_start_line = int(next_start_line)
        if not reported_truncated:
            raise DocumentationAgentError(
                f"MCP read returned a continuation without marking truncation: {path}"
            )
        if next_start_line <= start_line:
            raise DocumentationAgentError(f"MCP read did not advance while paging: {path}")
        start_line = next_start_line

    content = "\n".join(chunks)
    return DocumentationEvidenceFile(
        path=observed_path,
        sha256=sha256_text(content),
        size_bytes=len(content.encode("utf-8")),
        truncated=False,
        chunk_count=len(chunks),
        evidence_refs=evidence_refs,
        evidence_ref=evidence_refs[0] if evidence_refs else None,
        content=content,
    )


def _list_all_tracked_paths(
    *,
    call_tool: DocumentationToolCaller,
    page_size: int,
) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    evidence_refs: list[str] = []
    start_after: str | None = None

    while True:
        arguments: dict[str, Any] = {"path": ".", "max_results": page_size}
        if start_after is not None:
            arguments["start_after"] = start_after
        result = call_tool("dev-workspace", "dev_git_tracked_files", arguments)
        page = [str(path) for path in result.get("files") or []]
        if len(page) > page_size:
            raise DocumentationAgentError("tracked-file listing exceeded the requested page size")
        if page != sorted(page):
            raise DocumentationAgentError("tracked-file listing is not ordered")
        if start_after is not None and any(path <= start_after for path in page):
            raise DocumentationAgentError("tracked-file pagination did not advance")
        paths.extend(page)
        evidence_ref = result.get("evidence_ref")
        if evidence_ref:
            evidence_refs.append(str(evidence_ref))

        next_start_after = result.get("next_start_after")
        reported_truncated = bool(result.get("truncated"))
        if next_start_after is None:
            if reported_truncated:
                raise DocumentationAgentError(
                    "tracked-file listing was truncated without a continuation cursor"
                )
            break
        next_start_after = str(next_start_after)
        if not page or next_start_after != page[-1]:
            raise DocumentationAgentError("tracked-file continuation cursor is invalid")
        if not reported_truncated:
            raise DocumentationAgentError(
                "tracked-file listing returned a continuation without truncation"
            )
        if start_after is not None and next_start_after <= start_after:
            raise DocumentationAgentError("tracked-file pagination cursor did not advance")
        start_after = next_start_after

    if len(paths) != len(set(paths)):
        raise DocumentationAgentError("tracked-file pagination returned duplicate paths")
    return paths, evidence_refs


def collect_documentation_evidence(
    *,
    stage: Literal["baseline", "final"],
    expected_source_commit: str,
    config: dict[str, Any],
    call_tool: DocumentationToolCaller,
) -> DocumentationEvidenceBundle:
    source_id = str(config.get("source_id") or "archdoc")
    skill_entrypoint = str(config.get("skill_entrypoint") or "SKILL.md")
    target_documents = [str(item) for item in config.get("target_document_paths") or DEFAULT_TARGET_DOCUMENTS]
    max_skill_files = int(config.get("max_skill_files", 12))
    max_skill_total_bytes = int(config.get("max_skill_total_bytes", 131072))
    max_skill_file_bytes = int(config.get("max_skill_file_bytes", 65536))
    read_page_lines = int(config.get("read_page_lines", 2000))
    tracked_file_page_size = int(config.get("tracked_file_page_size", 1000))
    max_repository_files = int(config.get("max_repository_files", 10000))
    max_repository_total_bytes = int(config.get("max_repository_total_bytes", 8388608))
    max_repository_file_bytes = int(config.get("max_repository_file_bytes", 1048576))
    require_complete_repository = bool(config.get("require_complete_repository_evidence", True))

    listed = call_tool(
        "dev-workspace",
        "dev_external_skill_list",
        {
            "source_id": source_id,
            "path": ".",
            "max_depth": 4,
            "max_entries": 500,
        },
    )
    listed_commit = str(listed.get("source_commit") or "")
    if bool(listed.get("truncated")):
        raise DocumentationAgentError("external skill listing was truncated")
    if not listed_commit or listed_commit != expected_source_commit:
        raise DocumentationAgentError(
            "external skill commit changed or does not match the prepared workspace"
        )
    available_skill_files = [
        str(item.get("path"))
        for item in listed.get("entries") or []
        if item.get("type") == "file" and str(item.get("path") or "").lower().endswith(".md")
    ]
    if skill_entrypoint not in available_skill_files:
        raise DocumentationAgentError(
            f"external skill entrypoint is missing: {skill_entrypoint}"
        )
    ordered_skill_files = [skill_entrypoint] + sorted(
        path for path in available_skill_files if path != skill_entrypoint
    )

    if len(ordered_skill_files) > max_skill_files:
        raise DocumentationAgentError(
            "external skill file budget was exhausted before all Markdown files were read"
        )

    skill_files: list[DocumentationEvidenceFile] = []
    skill_bytes = 0
    for path in ordered_skill_files:
        remaining = max_skill_total_bytes - skill_bytes
        if remaining <= 0:
            raise DocumentationAgentError(
                "external skill byte budget was exhausted before all Markdown files were read"
            )
        item = _read_tool_file(
            call_tool=call_tool,
            tool_name="dev_external_skill_read",
            path=path,
            max_bytes=min(max_skill_file_bytes, remaining),
            page_lines=read_page_lines,
            source_id=source_id,
            expected_source_commit=expected_source_commit,
        )
        skill_files.append(item)
        skill_bytes += item.size_bytes

    all_tracked_paths, tracked_evidence_refs = _list_all_tracked_paths(
        call_tool=call_tool,
        page_size=tracked_file_page_size,
    )
    tracked_paths = [
        path
        for path in all_tracked_paths
        if not is_sensitive_repository_path(path) and is_repository_text_path(path)
    ]
    skipped_paths = set(all_tracked_paths) - set(tracked_paths)
    tracked_set = set(tracked_paths)
    targets = set(target_documents)
    candidate_repository_paths = list(dict.fromkeys([*target_documents, *tracked_paths]))
    ordered_repository_paths = sorted(
        candidate_repository_paths,
        key=lambda path: _priority_for_repository_path(path, targets),
    )

    repository_files: list[DocumentationEvidenceFile] = []
    repository_bytes = 0
    for path in ordered_repository_paths:
        if len(repository_files) >= max_repository_files:
            if require_complete_repository:
                raise DocumentationAgentError(
                    "repository evidence file budget was exhausted before all tracked text files were read"
                )
            break
        remaining = max_repository_total_bytes - repository_bytes
        if remaining <= 0:
            if require_complete_repository:
                raise DocumentationAgentError(
                    "repository evidence byte budget was exhausted before all tracked text files were read"
                )
            break
        try:
            item = _read_tool_file(
                call_tool=call_tool,
                tool_name="dev_workspace_read",
                path=path,
                max_bytes=min(max_repository_file_bytes, remaining),
                page_lines=read_page_lines,
            )
        except Exception as exc:
            if path in targets and _is_missing_untracked_target(
                path,
                tracked_paths=tracked_set,
                error=exc,
            ):
                continue
            priority, _ = _priority_for_repository_path(path, targets)
            if (
                path not in targets
                and priority == 9
                and _is_oversized_single_line_read(exc)
            ):
                skipped_paths.add(path)
                tracked_set.discard(path)
                continue
            raise DocumentationAgentError(
                f"failed to read tracked repository evidence file {path}: {exc}"
            ) from exc
        if item.truncated and require_complete_repository:
            raise DocumentationAgentError(
                f"tracked repository evidence file exceeded its configured byte budget: {path}"
            )
        repository_files.append(item)
        repository_bytes += item.size_bytes

    read_tracked_paths = {item.path for item in repository_files if item.path in tracked_set}
    missing_tracked_paths = sorted(tracked_set - read_tracked_paths)
    repository_complete = not missing_tracked_paths and all(not item.truncated for item in repository_files)
    if require_complete_repository and not repository_complete:
        raise DocumentationAgentError(
            "repository evidence collection was incomplete: " + ", ".join(missing_tracked_paths[:20])
        )

    refs = {
        ref
        for item in [*skill_files, *repository_files]
        for ref in item.evidence_refs
        if ref
    }
    if listed.get("evidence_ref"):
        refs.add(str(listed["evidence_ref"]))
    refs.update(tracked_evidence_refs)

    return DocumentationEvidenceBundle(
        stage=stage,
        source_id=source_id,
        source_commit=expected_source_commit,
        skill_files=skill_files,
        repository_files=repository_files,
        repository_tracked_paths=sorted(tracked_set),
        repository_skipped_paths=sorted(skipped_paths),
        repository_complete=repository_complete,
        target_document_paths=target_documents,
        tool_evidence_refs=sorted(refs),
    )


def normalize_documentation_response_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Relocate top-level documentation metadata misplaced inside replacements.

    Some structured-output providers preserve the authored replacement text exactly
    but attach ``evidence_notes`` or ``uncertainties`` to the replacement object.
    Those fields are descriptive metadata, not file content or authorization. Safeplane
    may therefore move only those two known fields to their required top-level
    locations without changing paths, ``old_text``, or ``new_text``. Any other extra
    replacement field remains invalid and fails closed during Pydantic validation.
    """

    normalized = dict(raw)
    replacements_raw = normalized.get("replacements")
    if not isinstance(replacements_raw, list):
        return normalized

    relocated: dict[str, list[str]] = {
        "evidence_notes": [],
        "uncertainties": [],
    }
    changed = False
    normalized_replacements: list[Any] = []

    for replacement_raw in replacements_raw:
        if not isinstance(replacement_raw, dict):
            normalized_replacements.append(replacement_raw)
            continue

        replacement = dict(replacement_raw)
        for field_name in relocated:
            if field_name not in replacement:
                continue
            value = replacement.pop(field_name)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise DocumentationAgentError(
                    f"misplaced documentation {field_name} must be a list of strings"
                )
            relocated[field_name].extend(value)
            changed = True
        normalized_replacements.append(replacement)

    if not changed:
        return normalized

    normalized["replacements"] = normalized_replacements

    for field_name, moved_values in relocated.items():
        if not moved_values:
            continue
        existing = normalized.get(field_name)
        if existing is None:
            combined = moved_values
        elif isinstance(existing, list) and all(
            isinstance(item, str) for item in existing
        ):
            combined = [*existing, *moved_values]
        else:
            raise DocumentationAgentError(
                f"documentation {field_name} must be a list of strings"
            )

        deduplicated: list[str] = []
        seen: set[str] = set()
        for item in combined:
            if item in seen:
                continue
            seen.add(item)
            deduplicated.append(item)
        normalized[field_name] = deduplicated

    return normalized


def expand_documentation_placeholders(
    content: str,
    *,
    evidence: DocumentationEvidenceBundle,
    repository_profile: str,
    prompt_id: str,
    prompt_version: str,
) -> str:
    skill_digest = sha256_text(
        "\n".join(f"{item.path}:{item.sha256}" for item in evidence.skill_files)
    )
    replacements = {
        "${ARCHDOC_COMMIT}": evidence.source_commit,
        "${ARCHDOC_SKILL_SHA256}": skill_digest,
        "${REPOSITORY_PROFILE}": repository_profile,
        "${DOCUMENTATION_PROMPT}": f"{prompt_id}@{prompt_version}",
    }
    expanded = content
    for marker, value in replacements.items():
        expanded = expanded.replace(marker, value)
    return expanded


def build_documentation_patch_from_replacements(
    replacements_raw: Any,
    *,
    repository_root: Path,
    allowed_paths: list[str],
) -> str:
    """Build a Git patch from exact, uniquely matched text replacements.

    The model supplies authored old/new text, while Safeplane owns all unified-
    diff metadata. Existing text must match exactly once at each replacement
    step. This prevents the harness from guessing where an edit belongs.
    """

    try:
        replacements = TypeAdapter(list[DocumentationTextReplacement]).validate_python(
            replacements_raw
        )
    except Exception as exc:
        raise DocumentationAgentError(
            f"invalid documentation replacements: {exc}"
        ) from exc
    if not replacements:
        raise DocumentationAgentError(
            "changed documentation requires at least one exact text replacement"
        )

    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise DocumentationAgentError(
            f"target repository is unavailable for documentation replacement: {exc}"
        ) from exc
    if not root.is_dir():
        raise DocumentationAgentError(
            "target repository is not a directory for documentation replacement"
        )

    allowed = set(allowed_paths)
    original_by_path: dict[str, str] = {}
    current_by_path: dict[str, str] = {}
    existed_by_path: dict[str, bool] = {}
    ordered_paths: list[str] = []

    for replacement in replacements:
        if replacement.path not in allowed:
            raise DocumentationAgentError(
                "documentation replacement contains disallowed path: "
                f"{replacement.path}"
            )
        unresolved_candidate = root / replacement.path
        if unresolved_candidate.is_symlink():
            raise DocumentationAgentError(
                f"documentation replacement may not target a symlink: {replacement.path}"
            )
        candidate = unresolved_candidate.resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise DocumentationAgentError(
                f"documentation replacement escapes repository root: {replacement.path}"
            )

        if replacement.path not in current_by_path:
            existed = candidate.is_file()
            if candidate.exists() and not existed:
                raise DocumentationAgentError(
                    f"documentation replacement target is not a regular file: {replacement.path}"
                )
            original = candidate.read_text(encoding="utf-8") if existed else ""
            original_by_path[replacement.path] = original
            current_by_path[replacement.path] = original
            existed_by_path[replacement.path] = existed
            ordered_paths.append(replacement.path)

        current = current_by_path[replacement.path]
        if replacement.old_text == "":
            if existed_by_path[replacement.path] or current != "":
                raise DocumentationAgentError(
                    "empty old_text is allowed only when creating a missing documentation "
                    f"file: {replacement.path}"
                )
            updated = replacement.new_text
        else:
            occurrences = current.count(replacement.old_text)
            if occurrences != 1:
                raise DocumentationAgentError(
                    "documentation replacement old_text must match exactly once: "
                    f"{replacement.path} matched {occurrences} times"
                )
            updated = current.replace(
                replacement.old_text, replacement.new_text, 1
            )
        current_by_path[replacement.path] = updated

    patch_sections: list[str] = []
    for path in ordered_paths:
        old = original_by_path[path]
        new = current_by_path[path]
        if old == new:
            raise DocumentationAgentError(
                f"documentation replacements produced no change: {path}"
            )
        if not new:
            raise DocumentationAgentError(
                f"documentation replacements may not delete a primary document: {path}"
            )

        from_file = f"a/{path}" if existed_by_path[path] else "/dev/null"
        diff_lines = list(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=from_file,
                tofile=f"b/{path}",
                n=3,
                lineterm="",
            )
        )
        if not diff_lines:
            raise DocumentationAgentError(
                f"documentation replacements produced no diff: {path}"
            )
        section = [f"diff --git a/{path} b/{path}"]
        if not existed_by_path[path]:
            section.append("new file mode 100644")
        section.extend(diff_lines)
        patch_sections.append("\n".join(section) + "\n")

    return "".join(patch_sections)


HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? "
    r"@@(?P<section>.*)$"
)


def normalize_documentation_patch(patch: str) -> str:
    """Canonicalize derived diff metadata without changing authored content.

    Model-authored documentation diffs may contain stale hunk counts or explicit
    no-op replacements such as ``-line`` followed by ``+line``. Safeplane can
    deterministically remove those empty hunks and recalculate range counts. It
    never invents a line prefix or changes a retained hunk body; malformed
    content-bearing hunks still fail closed before proposal creation.
    """

    lines = patch.splitlines(keepends=True)
    file_starts = [
        index
        for index, raw_line in enumerate(lines)
        if raw_line.rstrip("\r\n").startswith("diff --git ")
    ]
    if not file_starts:
        return patch

    normalized: list[str] = lines[: file_starts[0]]
    file_starts.append(len(lines))
    for file_index in range(len(file_starts) - 1):
        section = lines[file_starts[file_index] : file_starts[file_index + 1]]
        hunk_starts = [
            index
            for index, raw_line in enumerate(section)
            if HUNK_HEADER_PATTERN.fullmatch(raw_line.rstrip("\r\n")) is not None
        ]
        if not hunk_starts:
            normalized.extend(section)
            continue

        section_output = section[: hunk_starts[0]]
        kept_hunks = 0
        hunk_starts.append(len(section))
        for hunk_index in range(len(hunk_starts) - 1):
            header_raw = section[hunk_starts[hunk_index]]
            header = header_raw.rstrip("\r\n")
            match = HUNK_HEADER_PATTERN.fullmatch(header)
            if match is None:  # pragma: no cover - selected only by the same pattern
                raise DocumentationAgentError(
                    f"invalid documentation hunk header: {header}"
                )
            body = section[
                hunk_starts[hunk_index] + 1 : hunk_starts[hunk_index + 1]
            ]
            removed = [
                line.rstrip("\r\n")[1:]
                for line in body
                if line.rstrip("\r\n").startswith("-")
            ]
            added = [
                line.rstrip("\r\n")[1:]
                for line in body
                if line.rstrip("\r\n").startswith("+")
            ]
            if removed == added:
                continue

            old_count = 0
            new_count = 0
            for body_raw in body:
                body_line = body_raw.rstrip("\r\n")
                if body_line == r"\ No newline at end of file":
                    continue
                if not body_line or body_line[0] not in {" ", "+", "-"}:
                    raise DocumentationAgentError(
                        "documentation unified_diff is malformed or does not apply "
                        "cleanly: invalid unprefixed hunk line "
                        f"{body_line!r}"
                    )
                if body_line[0] in {" ", "-"}:
                    old_count += 1
                if body_line[0] in {" ", "+"}:
                    new_count += 1

            def render_range(prefix: str, start: str, count: int) -> str:
                if count == 1:
                    return f"{prefix}{start}"
                return f"{prefix}{start},{count}"

            newline = header_raw[len(header) :]
            section_output.append(
                "@@ "
                + render_range("-", match.group("old_start"), old_count)
                + " "
                + render_range("+", match.group("new_start"), new_count)
                + " @@"
                + match.group("section")
                + newline
            )
            section_output.extend(body)
            kept_hunks += 1

        if kept_hunks:
            normalized.extend(section_output)

    return "".join(normalized)


def parse_documentation_patch(patch: str) -> list[DocumentationPatchFile]:
    stats: dict[str, dict[str, Any]] = {}
    current: str | None = None
    saw_header = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            saw_header = True
            try:
                parts = shlex.split(line)
            except ValueError as exc:
                raise DocumentationAgentError(f"invalid documentation diff header: {line}") from exc
            if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise DocumentationAgentError("documentation patch must use git-style a/ and b/ paths")
            current = parts[3][2:]
            stats[current] = {
                "operation": "modified",
                "changed_lines": 0,
                "hunks": 0,
            }
            continue
        if current is None:
            continue
        if line.startswith("new file mode ") or line == "--- /dev/null":
            stats[current]["operation"] = "created"
        elif line.startswith("deleted file mode ") or line == "+++ /dev/null":
            stats[current]["operation"] = "deleted"
        elif line.startswith("@@"):
            stats[current]["hunks"] += 1
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            stats[current]["changed_lines"] += 1
    if not saw_header or not stats:
        raise DocumentationAgentError("documentation patch does not contain file changes")
    return [
        DocumentationPatchFile(path=path, **values)
        for path, values in sorted(stats.items())
    ]


def validate_documentation_patch(
    patch: str,
    *,
    allowed_paths: list[str],
    source_commit: str,
    existing_documents: dict[str, str] | None = None,
) -> list[DocumentationPatchFile]:
    files = parse_documentation_patch(patch)
    allowed = set(allowed_paths)
    changed_paths = {item.path for item in files}
    unexpected = changed_paths - allowed
    if unexpected:
        raise DocumentationAgentError(
            "documentation patch contains disallowed paths: " + ", ".join(sorted(unexpected))
        )
    if any(item.operation == "deleted" for item in files):
        raise DocumentationAgentError("documentation agent may not delete primary documentation files")

    added_content = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    for marker in UNRESOLVED_PLACEHOLDER_PATTERNS:
        if marker in added_content:
            raise DocumentationAgentError(
                f"documentation patch contains unresolved template placeholder: {marker}"
            )
    for pattern in SECRET_CONTENT_PATTERNS:
        if pattern.search(added_content):
            raise DocumentationAgentError("documentation patch appears to contain a secret value")
    existing_documents = existing_documents or {}
    for item in files:
        existing = existing_documents.get(item.path, "")
        evidence_content = added_content if item.operation == "created" else existing + "\n" + added_content
        if source_commit not in evidence_content:
            raise DocumentationAgentError(
                f"changed documentation must record the exact external skill commit: {item.path}"
            )
        if "Generated with `ai-craftkit` skill: `archdoc`" not in evidence_content:
            raise DocumentationAgentError(
                f"changed documentation is missing the archdoc provenance block: {item.path}"
            )
        if "Doc Status:" not in evidence_content or "Source Basis:" not in evidence_content:
            raise DocumentationAgentError(
                "changed documentation is missing required literal status fields "
                f"`Doc Status:` and/or `Source Basis:`: {item.path}"
            )
    return files


def validate_documentation_response_patch(
    response: DocumentationAgentResponse,
    *,
    evidence: DocumentationEvidenceBundle,
) -> list[DocumentationPatchFile]:
    """Validate a documentation response before any patch proposal or apply step.

    Real models are allowed bounded retries. Keeping semantic patch validation at
    the model-attempt boundary lets Safeplane return a precise deterministic
    repair instruction without creating a proposal, approval, or workspace write
    for an invalid response.
    """

    if not response.changed:
        return []

    patch = str(response.unified_diff or "")
    existing_documents = {
        item.path: item.content
        for item in evidence.repository_files
        if item.path in set(evidence.target_document_paths)
    }
    patch_files = validate_documentation_patch(
        patch,
        allowed_paths=evidence.target_document_paths,
        source_commit=evidence.source_commit,
        existing_documents=existing_documents,
    )
    declared_paths = set(response.documentation_files)
    patch_paths = {item.path for item in patch_files}
    if declared_paths != patch_paths:
        raise DocumentationAgentError(
            "documentation_files must exactly match the documentation patch paths"
        )
    return patch_files


def validate_documentation_patch_applicability(
    patch: str,
    *,
    repository_root: Path,
    timeout_seconds: int = 15,
) -> None:
    """Verify that a model-authored documentation diff is valid Git syntax and applies.

    This check is read-only. It deliberately runs before patch proposal or approval
    creation so malformed or stale model output can consume a bounded model retry
    rather than failing later at the write boundary.
    """

    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise DocumentationAgentError(
            f"target repository is unavailable for documentation patch validation: {exc}"
        ) from exc
    if not root.is_dir():
        raise DocumentationAgentError(
            "target repository is not a directory for documentation patch validation"
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
        raise DocumentationAgentError(
            "Git is unavailable for documentation patch validation"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DocumentationAgentError(
            "documentation patch validation timed out"
        ) from exc

    if completed.returncode == 0:
        return

    detail = (completed.stderr or completed.stdout or "git apply --check failed").strip()
    detail = detail.replace(str(root), "<target-repository>")
    if len(detail) > 2000:
        detail = detail[:2000] + "..."
    raise DocumentationAgentError(
        "documentation unified_diff is malformed or does not apply cleanly: " + detail
    )


def documentation_plan_budget(
    files: list[DocumentationPatchFile],
    *,
    max_changed_lines: int,
    max_hunks: int,
) -> list[dict[str, Any]]:
    return [
        {
            "path": item.path,
            "operation": item.operation,
            "max_changed_lines": max(max_changed_lines, item.changed_lines),
            "max_hunks": max(max_hunks, item.hunks),
        }
        for item in files
    ]


def snapshot_documentation(
    *,
    paths: list[str],
    call_tool: DocumentationToolCaller,
    max_bytes_per_file: int = 262144,
) -> list[DocumentationDocumentSnapshot]:
    snapshots: list[DocumentationDocumentSnapshot] = []
    for path in paths:
        try:
            item = _read_tool_file(
                call_tool=call_tool,
                tool_name="dev_workspace_read",
                path=path,
                max_bytes=max_bytes_per_file,
                page_lines=2000,
            )
        except Exception:
            continue
        if item.truncated:
            raise DocumentationAgentError(
                f"documentation snapshot exceeded its configured byte budget: {path}"
            )
        snapshots.append(
            DocumentationDocumentSnapshot(
                path=path,
                sha256=item.sha256,
                content=item.content,
            )
        )
    return snapshots


def json_prompt_payload(evidence: DocumentationEvidenceBundle) -> str:
    return json.dumps(evidence.prompt_payload(), ensure_ascii=False, indent=2)
