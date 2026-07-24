from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests" / "scripts" / "remove-container-owned-tree"
DOCKER_SMOKES = (
    "docker-smoke-developer-workspace",
    "docker-smoke-patch-approval",
    "docker-smoke-developer-pipeline",
    "docker-smoke-external-repositories",
    "docker-smoke-developer-tools",
    "docker-smoke-documentation-agent",
    "docker-smoke-single-pass-developer",
    "docker-smoke-remote-draft-pr",
)


def test_cleanup_helper_removes_host_owned_tree_without_docker(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    nested = runtime / "workspaces" / "run_fixture" / "artifacts"
    nested.mkdir(parents=True)
    (nested / "result.json").write_text("{}\n", encoding="utf-8")

    subprocess.run([str(HELPER), str(runtime)], check=True)

    assert not runtime.exists()


def test_docker_smokes_use_shared_container_owned_cleanup() -> None:
    failures: list[str] = []
    for name in DOCKER_SMOKES:
        path = ROOT / "tests" / "scripts" / name
        text = path.read_text(encoding="utf-8")
        if '"$ROOT/tests/scripts/remove-container-owned-tree" "$HOME_DIR" "$cleanup_image"' not in text:
            failures.append(f"{name}: shared cleanup helper missing")
        if 'rm -rf "$HOME_DIR"' in text:
            failures.append(f"{name}: direct runtime cleanup remains")
    assert failures == []


def test_cleanup_fallback_is_narrow_and_networkless() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert "--network none" in text
    assert "--read-only" in text
    assert "--user 0:0" in text
    assert "--cap-drop ALL" in text
    assert "--cap-add DAC_OVERRIDE" in text
    assert "--mount \"type=bind,source=$path,target=/cleanup\"" in text
    assert "sudo" not in text
