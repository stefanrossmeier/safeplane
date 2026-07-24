from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_production_overlay_rotates_every_long_running_service_log() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text())
    expected = {
        "harness",
        "model-gateway",
        "calendar-task-mcp",
        "notification-task-mcp",
        "scheduler",
        "telegram-connector",
        "dev-workspace-mcp",
        "dev-workspace-apply-mcp",
        "dev-check-mcp",
    }
    assert set(compose["services"]) == expected
    for service in compose["services"].values():
        logging = service["logging"]
        assert logging["driver"] == "json-file"
        assert "SAFEPLANE_LOG_MAX_SIZE" in logging["options"]["max-size"]
        assert "SAFEPLANE_LOG_MAX_FILES" in logging["options"]["max-file"]


def test_vps_compose_wrapper_is_portless_and_profile_bounded() -> None:
    text = (ROOT / "scripts/compose-safeplane-vps").read_text()
    assert "docker-compose.local.yml" not in text
    assert "docker-compose.production.yml" in text
    assert "SAFEPLANE_VPS_PROFILE" in text
    assert "assistant" in text and "developer" in text
    assert "docker-compose.github.yml" in text
    assert "docker-compose.github-mock.yml" not in text


def test_operator_surface_contains_required_commands_and_guards() -> None:
    text = (ROOT / "scripts/safeplane-vps").read_text()
    for command in (
        "preflight", "secrets", "config", "start", "stop", "restart",
        "status", "logs", "backup", "restore", "update", "rollback", "cleanup",
    ):
        assert f'"{command}"' in text
    assert '--confirm RESTORE' in text
    assert '--confirm ROLLBACK' in text
    assert 'git", "pull", "--ff-only"' in text
    assert 'docker", "port"' in text
    assert '"secrets", "workspaces", "git-fixtures"' in text
    assert "shell=True" not in text


def test_vps_layout_is_uid_aligned_and_not_world_writable() -> None:
    text = (ROOT / "scripts/prepare-vps-layout").read_text()
    assert "os.chown(path, 10001, operator_entry.pw_gid)" in text
    assert "path.chmod(0o2770)" in text
    assert "0o777" not in text
    assert "Run with sudo" in text


def test_secret_helper_writes_private_files() -> None:
    text = (ROOT / "scripts/safeplane-secret").read_text()
    assert "getpass.getpass" in text
    assert "SAFEPLANE_SECRET_UID" in text
    assert '"sudo",' in text
    assert '"install",' in text
    assert '"0600",' in text
    assert "path.chmod(0o644)" not in text


def test_operator_environment_example_uses_separate_absolute_roots() -> None:
    values = {}
    for line in (ROOT / "config/operator.env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    roots = {
        values["SAFEPLANE_HOME"],
        values["SAFEPLANE_SECRET_ROOT"],
        values["SAFEPLANE_BACKUP_ROOT"],
        values["SAFEPLANE_LOG_ROOT"],
    }
    assert len(roots) == 4
    assert all(value.startswith("/") for value in roots)


def test_vps_operator_loads_operator_env_without_overriding_shell():
    script = (ROOT / "scripts/safeplane-vps").read_text()
    assert 'SAFEPLANE_OPERATOR_ENV' in script
    assert '/etc/safeplane/operator.env' in script
    assert 'os.environ.setdefault(name, value)' in script
    assert 'load_operator_env()' in script


def test_vps_compose_wrapper_loads_operator_env_without_overriding_shell():
    script = (ROOT / "scripts/compose-safeplane-vps").read_text()
    assert 'SAFEPLANE_OPERATOR_ENV' in script
    assert '/etc/safeplane/operator.env' in script
    assert '[[ -z "${!name+x}" ]]' in script
    assert 'export "$name=$value"' in script


def test_developer_profile_reconciliation_is_profile_aware() -> None:
    text = (ROOT / "scripts/safeplane-vps").read_text()
    assert 'DEVELOPER_SERVICES = (' in text
    assert '"dev-workspace-mcp"' in text
    assert '"dev-workspace-apply-mcp"' in text
    assert '"dev-check-mcp"' in text
    assert 'def services_for_profile(' in text
    assert 'Switching VPS profile:' in text
    assert 'compose("down", "--remove-orphans", check=False)' in text
    assert 'removing stale project containers and retrying once' in text
    assert 'record_profile(profile)' in text


def test_production_logging_covers_developer_services() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text())
    for name in ("dev-workspace-mcp", "dev-workspace-apply-mcp", "dev-check-mcp"):
        logging = compose["services"][name]["logging"]
        assert logging["driver"] == "json-file"
        assert "SAFEPLANE_LOG_MAX_SIZE" in logging["options"]["max-size"]
        assert "SAFEPLANE_LOG_MAX_FILES" in logging["options"]["max-file"]


def test_readiness_accepts_running_service_without_healthcheck() -> None:
    text = (ROOT / "scripts/safeplane-vps").read_text()
    assert 'health in {"healthy", "none"}' in text
    assert 'health="no-healthcheck"' not in text
    assert '"no_healthcheck"' in text
    assert 'Overall status:' in text
    assert "expected={expected}" in text
    assert "present={present}" in text
    assert "running={running}" in text
    assert "healthy={healthy}" in text
    assert "unhealthy={unhealthy}" in text
    assert "missing={missing}" in text


def test_status_supports_machine_readable_json() -> None:
    text = (ROOT / "scripts/safeplane-vps").read_text()
    assert 'item.add_argument("--json", action="store_true")' in text
    assert 'json.dumps(summary, indent=2)' in text
    for field in (
        '"expected"', '"present"', '"running"', '"healthy"',
        '"no_healthcheck"', '"unhealthy"', '"missing"',
        '"portless"', '"ready"',
    ):
        assert field in text


def test_keyboard_interrupt_is_clean_and_nonfatal_to_shell() -> None:
    text = (ROOT / "scripts/safeplane-vps").read_text()
    assert "except KeyboardInterrupt:" in text
    assert "detached Safeplane containers continue running" in text
    assert "traceback" not in text.lower()


def test_developer_services_get_production_restart_policy() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text())
    for name in ("dev-workspace-mcp", "dev-workspace-apply-mcp", "dev-check-mcp"):
        assert compose["services"][name]["restart"] == "unless-stopped"
