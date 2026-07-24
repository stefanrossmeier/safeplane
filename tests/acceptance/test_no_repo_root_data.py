from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_command(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_calendar_cli_does_not_create_repo_root_data_directory() -> None:
    repo_data = REPO_ROOT / "data"
    shutil.rmtree(repo_data, ignore_errors=True)

    safeplane_home = Path(tempfile.mkdtemp(prefix="safeplane-no-repo-data-"))
    env = os.environ.copy()
    env["SAFEPLANE_HOME"] = str(safeplane_home)

    try:
        run_command(
            [
                "./scripts/safeplane",
                "calendar",
                "create",
                "--title",
                "Guard check",
                "--start",
                "2026-07-12T09:00:00+02:00",
                "--end",
                "2026-07-12T10:00:00+02:00",
            ],
            env=env,
        )

        assert (safeplane_home / "data" / "calendar" / "events.jsonl").exists()
        assert not repo_data.exists()

    finally:
        shutil.rmtree(safeplane_home, ignore_errors=True)
        shutil.rmtree(repo_data, ignore_errors=True)
