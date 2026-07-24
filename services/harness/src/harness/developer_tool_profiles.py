from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from harness.path_policy import SafePathPolicy


class DeveloperCommandProfileError(ValueError):
    pass


def workflow_contract_path() -> Path:
    configured = os.environ.get("SAFEPLANE_DEVELOPER_WORKFLOW_CONTRACT")
    if configured:
        return Path(configured)
    candidates = [
        Path("/app/workflows/developer/workflow.yaml"),
        Path.cwd() / "workflows" / "developer" / "workflow.yaml",
    ]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "workflows" / "developer" / "workflow.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DeveloperCommandProfileError("developer workflow contract could not be located")


def load_command_profiles() -> dict[str, dict[str, Any]]:
    path = workflow_contract_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles = (raw.get("developer_tools") or {}).get("command_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise DeveloperCommandProfileError(
            f"developer command profiles are missing from workflow contract: {path}"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            raise DeveloperCommandProfileError(f"invalid command profile: {profile_id}")
        normalized[str(profile_id)] = profile
    return normalized


def _positive_int(profile: dict[str, Any], field: str, maximum: int) -> int:
    value = profile.get(field)
    if not isinstance(value, int) or value < 1 or value > maximum:
        raise DeveloperCommandProfileError(
            f"command profile field {field} must be between 1 and {maximum}"
        )
    return value


def resolve_command_profile(
    profile_id: str,
    arguments: list[str],
    *,
    repository_root: Path,
    timeout_seconds: int | None,
) -> tuple[list[str], dict[str, int]]:
    profile = load_command_profiles().get(profile_id)
    if profile is None:
        raise DeveloperCommandProfileError(f"undeclared command profile: {profile_id}")
    if profile.get("network") != "disabled":
        raise DeveloperCommandProfileError("developer command profiles must disable network access")

    executable = str(profile.get("executable") or "")
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", executable):
        raise DeveloperCommandProfileError("command profile executable must be a bare executable name")
    if not arguments:
        raise DeveloperCommandProfileError(f"command profile {profile_id!r} requires a script path")

    script = arguments[0]
    raw_path = Path(script)
    if raw_path.is_absolute() or ".." in raw_path.parts or script.startswith("-"):
        raise DeveloperCommandProfileError("command script path must stay inside the repository")
    allowed_roots = {str(item) for item in profile.get("allowed_roots") or []}
    if not raw_path.parts or raw_path.parts[0] not in allowed_roots:
        raise DeveloperCommandProfileError(
            f"command script must be below one of: {', '.join(sorted(allowed_roots))}"
        )
    allowed_suffixes = {str(item) for item in profile.get("allowed_suffixes") or []}
    if raw_path.suffix not in allowed_suffixes:
        raise DeveloperCommandProfileError("command script has a disallowed file extension")

    resolved = SafePathPolicy(repository_root).resolve(script)
    if not resolved.is_file() or resolved.is_symlink():
        raise DeveloperCommandProfileError(f"command script is not a regular file: {script}")

    configured_timeout = _positive_int(profile, "timeout_seconds", 60)
    effective_timeout = min(timeout_seconds or configured_timeout, configured_timeout, 60)
    limits = {
        "timeout_seconds": effective_timeout,
        "max_output_bytes": _positive_int(profile, "max_output_bytes", 1_048_576),
        "cpu_seconds": _positive_int(profile, "cpu_seconds", 60),
        "memory_bytes": _positive_int(profile, "memory_bytes", 1_073_741_824),
    }
    fixed_arguments = profile.get("fixed_arguments") or []
    if not isinstance(fixed_arguments, list) or any(not isinstance(item, str) for item in fixed_arguments):
        raise DeveloperCommandProfileError("command profile fixed_arguments must be a string list")
    return [executable, *fixed_arguments, *arguments], limits
