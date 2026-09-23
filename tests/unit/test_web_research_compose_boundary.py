from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_research_agent_has_no_network_in_common_with_harness() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    harness_networks = set(services["harness"]["networks"])
    gateway_networks = set(services["web-research-gateway"]["networks"])
    agent_networks = set(services["web-research-agent"]["networks"])

    assert harness_networks.isdisjoint(agent_networks)
    assert harness_networks & gateway_networks == {"research-gateway"}
    assert gateway_networks & agent_networks == {"research-control"}
    assert "research-egress" in agent_networks
    assert "research-egress" not in gateway_networks
    assert "research-egress" not in harness_networks


def test_online_research_agent_mounts_only_dedicated_research_credentials() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    agent = services["web-research-agent"]
    gateway = services["web-research-gateway"]

    volumes = agent.get("volumes") or []
    assert len(volumes) == 1
    assert "/run/secrets/web-research:ro" in volumes[0]
    assert "SAFEPLANE_HOME" not in volumes[0]
    env = agent.get("environment") or {}
    assert "BRAVE_API_KEY_FILE" not in env
    assert "OPENROUTER_API_KEY_FILE" not in env
    assert all("API_KEY" not in key and "TOKEN" not in key for key in env)
    assert gateway.get("volumes") in (None, [])
    assert "ports" not in agent
    assert "ports" not in gateway
