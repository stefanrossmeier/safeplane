from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.path_policy import SafePathPolicy, SafePathPolicyError  # noqa: E402


def test_safe_path_policy_resolves_relative_path_inside_root(tmp_path: Path) -> None:
    policy = SafePathPolicy(tmp_path)

    resolved = policy.resolve("subdir/file.txt")

    assert resolved == (tmp_path / "subdir" / "file.txt").resolve(strict=False)


def test_safe_path_policy_allows_absolute_path_inside_root(tmp_path: Path) -> None:
    policy = SafePathPolicy(tmp_path)
    inside = tmp_path / "subdir" / "file.txt"

    assert policy.resolve(inside) == inside.resolve(strict=False)


def test_safe_path_policy_rejects_relative_escape(tmp_path: Path) -> None:
    policy = SafePathPolicy(tmp_path)

    with pytest.raises(SafePathPolicyError):
        policy.resolve("../outside.txt")


def test_safe_path_policy_rejects_absolute_escape(tmp_path: Path) -> None:
    policy = SafePathPolicy(tmp_path)

    with pytest.raises(SafePathPolicyError):
        policy.resolve(Path("/tmp/outside-safeplane-root.txt"))
