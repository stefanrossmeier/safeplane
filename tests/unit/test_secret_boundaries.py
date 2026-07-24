from __future__ import annotations

from pathlib import Path

import yaml


def load_yaml(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def service_environment(compose: dict, service_name: str) -> dict:
    return compose["services"][service_name].get("environment", {})


def test_base_compose_does_not_inject_openrouter_api_key():
    compose = load_yaml("docker-compose.yml")

    for service_name in ["harness", "model-gateway"]:
        env = service_environment(compose, service_name)
        assert "OPENROUTER_API_KEY" not in env


def test_test_compose_does_not_inject_openrouter_api_key():
    compose = load_yaml("docker-compose.test.yml")

    for service_name in ["harness", "model-gateway"]:
        env = service_environment(compose, service_name)
        assert "OPENROUTER_API_KEY" not in env


def test_real_compose_mounts_openrouter_secret_only_into_model_gateway():
    compose = load_yaml("docker-compose.real.yml")

    assert "openrouter_api_key" in compose["secrets"]

    model_gateway = compose["services"]["model-gateway"]
    assert model_gateway.get("secrets") == ["openrouter_api_key"]

    assert "harness" not in compose.get("services", {})
    assert "chat-workflow" not in compose.get("services", {})
    assert "assistant-workflow" not in compose.get("services", {})
    assert "slow-workflow" not in compose.get("services", {})


def test_draft_pr_smoke_secret_is_readable_by_non_root_harness():
    script = Path("tests/scripts/docker-smoke-remote-draft-pr").read_text(
        encoding="utf-8"
    )

    assert 'SECRET_DIR="$(mktemp -d)"' in script
    assert 'chmod 0644 "$SAFEPLANE_GITHUB_TOKEN_FILE"' in script
    assert 'chmod 0600 "$SAFEPLANE_GITHUB_TOKEN_FILE"' not in script
