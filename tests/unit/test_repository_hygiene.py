from __future__ import annotations

import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repository_hygiene_check_is_executable_and_green() -> None:
    script = REPO_ROOT / "tests" / "scripts" / "check-repository-hygiene"
    assert os.access(script, os.X_OK)
    completed = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "repository paths, fixtures, prompts" in completed.stdout


def test_generated_artifacts_are_ignored() -> None:
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for expected in ("__pycache__/", "*.py[cod]", "__MACOSX/", ".DS_Store", "*.patch"):
        assert expected in ignore


def test_live_backlog_is_documented_under_docs() -> None:
    backlog = REPO_ROOT / "docs" / "BACKLOG.md"
    assert backlog.is_file()
    content = backlog.read_text(encoding="utf-8")
    assert "# Backlog" in content
    assert "## Current priorities" in content
    assert "## Deferred candidates" in content

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/BACKLOG.md" in readme


def test_hygiene_normalizer_preserves_live_backlog() -> None:
    normalizer = (REPO_ROOT / "scripts" / "normalize-repository-hygiene").read_text(
        encoding="utf-8"
    )
    assert 'move_if_present("mvp-ladder.md"' not in normalizer
    assert 'move_if_present("docs/mvp/mvp-ladder.md", "docs/history/legacy-roadmap.md")' in normalizer
