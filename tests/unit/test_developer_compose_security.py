from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dev_workspace_service_has_narrow_read_only_boundary() -> None:
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.developer.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["dev-workspace-mcp"]

    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service.get("secrets") in (None, [])
    assert service["networks"] == ["dev-workspace-internal"]
    assert compose["networks"]["dev-workspace-internal"]["internal"] is True

    harness_volumes = compose["services"]["harness"]["volumes"]
    assert any(
        volume.endswith("/workspaces:/data/safeplane/workspaces")
        for volume in harness_volumes
    )
    assert (
        "${SAFEPLANE_HOME:-${HOME}/.safeplane}/git-fixtures:"
        "/data/safeplane/git-fixtures:ro"
    ) in harness_volumes
    assert all("/secrets" not in volume for volume in harness_volumes)

    for service_name, developer_service in compose["services"].items():
        assert all(
            "/data/safeplane/publication-remotes" not in volume
            for volume in developer_service.get("volumes", [])
        )
        if service_name == "harness":
            continue
        assert all(
            "/data/safeplane/git-fixtures" not in volume
            for volume in developer_service.get("volumes", [])
        )

    volumes = service["volumes"]
    assert len(volumes) == 1
    assert volumes[0].endswith("/workspaces:/workspace:ro")
    assert "docker.sock" not in "\n".join(volumes)
    assert "/data/calendar" not in "\n".join(volumes)
    assert "/data/notifications" not in "\n".join(volumes)

    apply_service = compose["services"]["dev-workspace-apply-mcp"]
    assert apply_service["read_only"] is True
    assert apply_service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in apply_service["security_opt"]
    assert apply_service.get("secrets") in (None, [])
    assert apply_service["networks"] == ["dev-workspace-internal"]
    assert apply_service["environment"]["SAFEPLANE_WORKSPACE_MODE"] == "apply"
    assert apply_service["volumes"] == [
        "${SAFEPLANE_HOME:-${HOME}/.safeplane}/workspaces:/workspace"
    ]
    assert apply_service["healthcheck"] == service["healthcheck"]

    harness_dependencies = compose["services"]["harness"]["depends_on"]
    for dependency in ("dev-workspace-mcp", "dev-workspace-apply-mcp"):
        assert harness_dependencies[dependency]["condition"] == "service_healthy"
        assert "healthcheck" in compose["services"][dependency]


def test_developer_workspace_smoke_is_fake_mode_and_checks_read_only_evidence() -> None:
    import os

    script_path = REPO_ROOT / "tests/scripts/docker-smoke-developer-workspace"
    script = script_path.read_text(encoding="utf-8")

    assert os.access(script_path, os.X_OK)
    assert "compose-safeplane-developer-fake" in script
    assert "developer list ." in script
    assert "path escapes allowed root" in script
    assert "dev_workspace_propose_patch" in script
    assert "read-only workspace was modified" in script
    assert "tool-calls.jsonl" in script
    assert "MODEL_GATEWAY_MODE=real" not in script



def test_patch_approval_smoke_requires_explicit_approval_and_concurrency() -> None:
    import os

    script_path = REPO_ROOT / "tests/scripts/docker-smoke-patch-approval"
    script = script_path.read_text(encoding="utf-8")

    assert os.access(script_path, os.X_OK)
    assert "compose-safeplane-developer-fake" in script
    assert "dev-workspace-apply-mcp" in script
    assert "internal approval token" in script
    assert '/approve"' in script
    assert "assistant request" in script.lower()
    assert "duplicate approval" in script
    assert "host source fixture was modified" in script
    assert "MODEL_GATEWAY_MODE=real" not in script


def test_github_secret_overlay_mounts_only_into_harness() -> None:
    overlay = yaml.safe_load((REPO_ROOT / "docker-compose.github.yml").read_text())
    assert overlay["services"]["harness"]["secrets"] == ["github_token"]
    assert set(overlay["services"]) == {"harness"}
    secret_file = overlay["secrets"]["github_token"]["file"]
    assert "SAFEPLANE_GITHUB_TOKEN_FILE" in secret_file
    assert "SAFEPLANE_SECRET_ROOT" in secret_file
    assert ".config/safeplane/secrets" in secret_file
    assert "SAFEPLANE_HOME" not in secret_file


def test_dev_check_service_has_no_secret_or_external_network_boundary() -> None:
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.developer.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["dev-check-mcp"]
    assert service["environment"]["SAFEPLANE_WORKSPACE_MODE"] == "execute"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service.get("secrets") in (None, [])
    assert service.get("networks") is None
    assert service["network_mode"] == "none"
    assert service["volumes"] == [
        "${SAFEPLANE_HOME:-${HOME}/.safeplane}/workspaces:/workspace:ro",
        "dev-check-control:/run/safeplane-dev-check",
    ]
    assert "--uds /run/safeplane-dev-check/dev-check.sock" in service["command"][-1]
    assert service["pids_limit"] == 64
    assert service["mem_limit"] == "320m"
    assert service["cpus"] == "0.50"
    assert service["tmpfs"] == ["/tmp:size=256m,mode=1777"]
    assert compose["services"]["harness"]["volumes"][-1] == (
        "dev-check-control:/run/safeplane-dev-check"
    )
    assert "dev-check-control" in compose["volumes"]


def test_developer_tools_runtime_config_uses_unix_socket() -> None:
    config = yaml.safe_load((REPO_ROOT / "safeplane.yaml").read_text(encoding="utf-8"))
    server = config["mcp_servers"]["dev-check"]
    assert server["endpoint"] == "unix:///run/safeplane-dev-check/dev-check.sock"

    workflow = yaml.safe_load(
        (REPO_ROOT / "workflows" / "developer" / "workflow.yaml").read_text(encoding="utf-8")
    )
    model_tools = workflow["mcp"]["model_allowed_servers"]
    assert "dev-check" not in model_tools
    assert "dev_external_skill_read" not in model_tools["dev-workspace"]["tools"]
    assert workflow["agents"]["documentation"]["allowed_mcp_servers"]["dev-workspace"]["tools"]
    assert workflow["agents"]["pr"]["allowed_mcp_servers"] == {}
