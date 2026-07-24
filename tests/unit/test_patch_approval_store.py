from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.patch_approval_store import (  # noqa: E402
    PatchApprovalConflictError,
    create_patch_approval,
    load_patch_proposal,
    prepare_patch_apply_workspace,
    publish_patch_apply_workspace,
    sha256_text,
    validate_patch_approval_token,
)


def create_proposal(home: Path) -> tuple[dict, dict]:
    run = {
        "run_id": "run_store",
        "workflow_id": "developer",
        "session_id": "sess_store",
        "turn": 1,
    }
    artifacts = home / "workspaces" / run["run_id"] / "artifacts"
    repo = home / "workspaces" / run["run_id"] / "repo"
    artifacts.mkdir(parents=True)
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("old\n", encoding="utf-8")
    proposal_id = "patch_proposal_store"
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    patch_ref = f"workspaces/{run['run_id']}/artifacts/{proposal_id}.patch"
    (home / patch_ref).write_text(patch, encoding="utf-8")
    metadata = {
        "version": 1,
        "run_id": run["run_id"],
        "workflow_id": run["workflow_id"],
        "session_id": run["session_id"],
        "turn": run["turn"],
        "proposal_id": proposal_id,
        "patch_ref": patch_ref,
        "patch_sha256": sha256_text(patch),
    }
    (artifacts / f"{proposal_id}.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return run, metadata


def test_patch_approval_token_and_controlled_publish(tmp_path: Path) -> None:
    home = tmp_path / "home"
    run, proposal_metadata = create_proposal(home)
    proposal = load_patch_proposal(
        home,
        run_id=run["run_id"],
        proposal_id=proposal_metadata["proposal_id"],
    )
    approval, token = create_patch_approval(
        home,
        run=run,
        proposal=proposal,
        connector="test",
    )

    validate_patch_approval_token(
        home,
        run_id=run["run_id"],
        approval_id=approval["approval_id"],
        approval_token=token,
        proposal_id=proposal["proposal_id"],
        patch_sha256=proposal["patch_sha256"],
        workflow_id="developer",
    )

    staged = prepare_patch_apply_workspace(
        home,
        run_id=run["run_id"],
        approval_id=approval["approval_id"],
    )
    (staged / "src" / "app.py").write_text("new\n", encoding="utf-8")
    publish_patch_apply_workspace(
        home,
        run_id=run["run_id"],
        approval_id=approval["approval_id"],
    )

    final = home / "workspaces" / run["run_id"] / "repo" / "src" / "app.py"
    assert final.read_text(encoding="utf-8") == "new\n"
    assert final.stat().st_mode & 0o222 == 0


def test_same_proposal_cannot_be_approved_twice(tmp_path: Path) -> None:
    home = tmp_path / "home"
    run, proposal_metadata = create_proposal(home)
    proposal = load_patch_proposal(
        home,
        run_id=run["run_id"],
        proposal_id=proposal_metadata["proposal_id"],
    )
    create_patch_approval(home, run=run, proposal=proposal, connector="test")

    with pytest.raises(PatchApprovalConflictError, match="already has approval"):
        create_patch_approval(home, run=run, proposal=proposal, connector="test")
