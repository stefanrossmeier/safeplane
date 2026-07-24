from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.developer_workspace import prepare_developer_workspace  # noqa: E402


def test_prepare_developer_workspace_creates_per_run_snapshot(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / ".git").mkdir()
    (source / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / ".git" / "config").write_text("secret-ish metadata\n", encoding="utf-8")
    monkeypatch.setenv("SAFEPLANE_DEVELOPER_SOURCE_ROOT", str(source))

    home = tmp_path / "home"
    result = prepare_developer_workspace(
        contract={
            "workspace": {
                "source_root_env": "SAFEPLANE_DEVELOPER_SOURCE_ROOT",
                "read_only": True,
                "exclude": [".git"],
            }
        },
        safeplane_home=home,
        run_id="run_snapshot",
    )

    assert result is not None
    repo = home / "workspaces" / "run_snapshot" / "repo"
    assert (repo / "src" / "main.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (repo / ".git").exists()
    assert (repo / "src" / "main.py").stat().st_mode & 0o222 == 0
    assert repo.stat().st_mode & 0o222 == 0

    manifest = json.loads(
        (home / "workspaces" / "run_snapshot" / "workspace.json").read_text(encoding="utf-8")
    )
    assert manifest["run_id"] == "run_snapshot"
    assert manifest["read_only"] is True
    assert manifest["container_logical_root"] == "/workspace"
