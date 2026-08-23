from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def volume_targets(service: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in service.get("volumes", []):
        if isinstance(entry, str):
            parts = entry.rsplit(":", 2)
            if len(parts) == 3 and parts[2] in {"ro", "rw"}:
                source, target, mode = parts
            else:
                source, target = entry.rsplit(":", 1)
                mode = "rw"
        else:
            source = str(entry.get("source", ""))
            target = str(entry["target"])
            mode = "ro" if entry.get("read_only") else "rw"
        result[target] = f"{source}:{mode}"
    return result


def assert_hardened(service: dict) -> None:
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["init"] is True
    assert int(service["pids_limit"]) > 0
    assert service["tmpfs"]
    assert service["cpus"]
    assert service["mem_limit"]


def test_base_services_use_narrow_runtime_mounts() -> None:
    compose = load("docker-compose.yml")
    expected = {
        "harness": {
            "/data/safeplane/sessions",
            "/data/safeplane/runs",
            "/data/safeplane/traces",
            "/data/safeplane/workspaces",
            "/data/safeplane/logs/mcp",
            "/data/safeplane/config",
            "/app/safeplane.yaml",
            "/app/workflows",
            "/app/prompts",
        },
        "model-gateway": {
            "/data/safeplane/traces",
            "/app/workflows",
            "/app/prompts",
        },
        "calendar-task-mcp": {
            "/data/safeplane/data/calendar",
            "/data/safeplane/logs/mcp",
        },
        "notification-task-mcp": {
            "/data/safeplane/data/notifications",
            "/data/safeplane/logs/mcp",
        },
        "scheduler": {
            "/data/safeplane/data/notifications",
            "/data/safeplane/data/calendar",
            "/data/safeplane/logs/scheduler",
        },
        "cli-connector": set(),
    }
    for name, targets in expected.items():
        mounted = volume_targets(compose["services"][name])
        assert set(mounted) == targets
        assert "/data/safeplane" not in mounted
        assert all("/secrets" not in value for value in mounted.values())

    assert volume_targets(compose["services"]["harness"])[
        "/data/safeplane/config"
    ].endswith(":ro")
    assert volume_targets(compose["services"]["scheduler"])[
        "/data/safeplane/data/calendar"
    ].endswith(":ro")


def test_local_git_fixtures_are_read_only_and_harness_only() -> None:
    developer = load("docker-compose.developer.yml")
    services = developer["services"]
    harness_mounts = volume_targets(services["harness"])

    assert harness_mounts["/data/safeplane/git-fixtures"].endswith(
        "/git-fixtures:ro"
    )
    assert services["harness"]["environment"][
        "SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES"
    ].endswith(":-no}")

    for name, service in services.items():
        if name == "harness":
            continue
        assert "/data/safeplane/git-fixtures" not in volume_targets(service), name


def test_optional_services_use_narrow_runtime_mounts() -> None:
    telegram = load("docker-compose.telegram.yml")["services"]["telegram-connector"]
    assert set(volume_targets(telegram)) == {
        "/data/safeplane/connectors/telegram",
        "/data/safeplane/logs/connectors/telegram",
    }
    github_compose = load("docker-compose.github-mock.yml")
    github_services = github_compose["services"]
    github_mock = github_services["github-mock"]
    assert set(volume_targets(github_mock)) == {"/data"}

    publication_mounts = volume_targets(github_services["harness"])
    assert publication_mounts["/data/safeplane/publication-remotes"] == (
        "publication-remotes:rw"
    )
    assert set(github_compose["volumes"]) == {"publication-remotes"}
    for name, service in github_services.items():
        if name == "harness":
            continue
        assert "/data/safeplane/publication-remotes" not in volume_targets(service), name


def test_long_running_services_have_container_hardening() -> None:
    base = load("docker-compose.yml")["services"]
    for name in (
        "harness",
        "model-gateway",
        "calendar-task-mcp",
        "notification-task-mcp",
        "scheduler",
    ):
        assert_hardened(base[name])
        assert "healthcheck" in base[name]

    assert_hardened(base["cli-connector"])
    assert base["cli-connector"]["restart"] == "no"
    assert base["cli-connector"]["profiles"] == ["cli"]
    assert "healthcheck" not in base["cli-connector"]

    assert_hardened(load("docker-compose.telegram.yml")["services"]["telegram-connector"])
    assert_hardened(load("docker-compose.github-mock.yml")["services"]["github-mock"])

    developer = load("docker-compose.developer.yml")["services"]
    for name in ("dev-workspace-mcp", "dev-workspace-apply-mcp"):
        assert_hardened(developer[name])
        assert "healthcheck" in developer[name]
    check = developer["dev-check-mcp"]
    assert check["network_mode"] == "none"
    assert check["read_only"] is True
    assert check["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in check["security_opt"]
    assert check["init"] is True


def test_harness_image_prepares_non_root_publication_volume_seed() -> None:
    dockerfile = (ROOT / "services/harness/Dockerfile").read_text(encoding="utf-8")
    assert "mkdir -p /data/safeplane/publication-remotes" in dockerfile
    assert 'chown -R "${SAFEPLANE_UID}:${SAFEPLANE_GID}" /data/safeplane' in dockerfile


def test_all_service_images_set_a_non_root_user() -> None:
    dockerfiles = (
        "services/harness/Dockerfile",
        "services/model-gateway/Dockerfile",
        "services/scheduler/Dockerfile",
        "mcp-servers/calendar-task/Dockerfile",
        "mcp-servers/notification-task/Dockerfile",
        "connectors/telegram/Dockerfile",
        "connectors/cli/Dockerfile",
        "mcp-servers/dev-workspace/Dockerfile",
        "tests/fixtures/github-mock/Dockerfile",
    )
    for name in dockerfiles:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "USER " in text, name
        assert "USER root" not in text, name


def test_networks_are_explicit_and_internal_where_required() -> None:
    compose = load("docker-compose.yml")
    networks = compose["networks"]
    assert networks["harness-model"]["internal"] is True
    assert networks["harness-tools"]["internal"] is True
    assert networks["notification-delivery"]["internal"] is True
    assert networks["connector-harness"]["internal"] is True
    assert networks["harness-egress"] is None
    assert networks["model-egress"] is None
    assert networks["telegram-egress"] is None

    services = compose["services"]
    assert set(services["harness"]["networks"]) == {
        "harness-egress",
        "harness-model",
        "harness-tools",
        "connector-harness",
    }
    assert set(services["model-gateway"]["networks"]) == {
        "model-egress",
        "harness-model",
    }
    assert services["calendar-task-mcp"]["networks"] == ["harness-tools"]
    assert set(services["notification-task-mcp"]["networks"]) == {
        "harness-tools",
        "notification-delivery",
    }
    assert services["scheduler"]["networks"] == ["notification-delivery"]
    assert services["cli-connector"]["networks"] == ["connector-harness"]
    assert not volume_targets(services["cli-connector"])
    assert "secrets" not in services["cli-connector"]
    assert "ports" not in services["cli-connector"]

    telegram = load("docker-compose.telegram.yml")["services"]
    assert set(telegram["telegram-connector"]["networks"]) == {
        "telegram-egress",
        "connector-harness",
        "notification-delivery",
    }


def test_only_loopback_harness_ports_are_published() -> None:
    local = load("docker-compose.local.yml")
    assert local["services"]["harness"]["ports"] == [
        "127.0.0.1:${SAFEPLANE_HARNESS_PORT:-8787}:8080"
    ]
    test = load("docker-compose.test.yml")
    assert test["services"]["harness"]["ports"] == ["127.0.0.1:18787:8080"]

    for name in (
        "docker-compose.yml",
        "docker-compose.real.yml",
        "docker-compose.telegram.yml",
        "docker-compose.github.yml",
        "docker-compose.developer.yml",
    ):
        for service in load(name).get("services", {}).values():
            assert "ports" not in service


def test_secret_files_are_external_and_mounted_only_to_intended_services() -> None:
    real = load("docker-compose.real.yml")
    assert real["services"]["model-gateway"]["secrets"] == ["openrouter_api_key"]
    assert "SAFEPLANE_HOME" not in real["secrets"]["openrouter_api_key"]["file"]

    github = load("docker-compose.github.yml")
    assert github["services"]["harness"]["secrets"] == ["github_token"]
    assert "SAFEPLANE_HOME" not in github["secrets"]["github_token"]["file"]

    telegram = load("docker-compose.telegram.yml")
    assert telegram["services"]["telegram-connector"]["secrets"] == [
        "telegram_bot_token",
        "telegram_allowed_user_ids",
    ]
    for secret in telegram["secrets"].values():
        assert "SAFEPLANE_HOME" not in secret["file"]

    base = load("docker-compose.yml")
    assert "secrets" not in base
    for service in base["services"].values():
        assert "secrets" not in service
        env = service.get("environment", {})
        assert all("TOKEN" not in key and "API_KEY" not in key for key in env)


def test_runtime_layout_rejects_secret_root_below_runtime_root() -> None:
    script = (ROOT / "scripts/prepare-runtime-layout").read_text(encoding="utf-8")
    assert "SAFEPLANE_SECRET_ROOT must be outside SAFEPLANE_HOME" in script
    assert 'runtime_root / "secrets"' in script  # legacy warning only
    assert "secret_root.mkdir" in script


def test_runtime_hardening_acceptance_waits_for_all_core_healthchecks() -> None:
    script = (ROOT / "tests/scripts/accept-runtime-hardening").read_text(
        encoding="utf-8"
    )
    assert "deadline = time.monotonic() + 90" in script
    assert 'item.get("container_status") == "running"' in script
    assert 'item.get("health_status") == "healthy"' in script
    assert "core services did not become healthy within 90 seconds" in script
    assert '"logs", "--no-color", "--tail", "100"' in script
