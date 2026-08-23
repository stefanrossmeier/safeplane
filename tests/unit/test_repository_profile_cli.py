from __future__ import annotations

from pathlib import Path
import os
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cli_develop_repo_option_is_implemented_by_explicit_connector() -> None:
    cli = (REPO_ROOT / "connectors/cli/src/safeplane_cli/main.py").read_text(encoding="utf-8")
    legacy = (REPO_ROOT / "scripts/safeplane-chat").read_text(encoding="utf-8")
    assert 'parser.add_argument("--repo", dest="repository_profile")' in cli
    assert "repository_profile=repository_profile" in cli
    assert "curl" not in legacy
    assert "SAFEPLANE_HARNESS_URL" not in legacy
    completed = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "scripts/safeplane-chat")],
        check=False,
    )
    assert completed.returncode == 0


def test_real_github_clone_smoke_is_manual_and_checks_secret_boundaries() -> None:
    script_path = REPO_ROOT / "tests/scripts/validate-real-repository-clone"
    script = script_path.read_text(encoding="utf-8")
    assert "SAFEPLANE_CONFIRM_REAL_GITHUB_CLONE" in script
    assert "compose-safeplane-developer-github-fake" in script
    assert "/run/secrets/github_token" in script
    assert "model-gateway" in script
    assert "dev-workspace-mcp" in script
    result = subprocess.run(
        [str(script_path)],
        cwd=REPO_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "SAFEPLANE_CONFIRM_REAL_GITHUB_CLONE"
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "manual GitHub repository clone smoke" in result.stderr
