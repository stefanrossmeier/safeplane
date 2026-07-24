from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "tests" / "scripts" / "docker-smoke-external-repositories"


def test_container_owned_workspace_git_reads_trust_only_exact_repository() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert 'git -c "safe.directory=$repository" -C "$repository" "$@"' in text
    assert 'git config --global' not in text
    assert 'safe.directory=*' not in text
    assert 'safe.directory /' not in text


def test_all_host_side_workspace_git_reads_use_the_narrow_helper() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert text.count('workspace_git "$SAFEPLANE_HOME/workspaces/') == 3
    assert 'git -C "$SAFEPLANE_HOME/workspaces/' not in text
