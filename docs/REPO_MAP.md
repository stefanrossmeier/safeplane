# Safeplane repository map

## Runtime services

- `services/harness/` — workflow/session/run authority, MCP brokering,
  validation, approvals, repository/Git operations, and evidence.
- `services/model-gateway/` — model-provider boundary.
- `services/scheduler/` — durable notification scheduling/delivery coordination.

## Connectors

- `connectors/common/` — shared typed connector/control HTTP client and error
  mapping.
- `connectors/cli/` — explicit one-shot Python CLI connector and container image.
- `connectors/telegram/` — long-running Telegram transport connector.

## Host operator scripts

- `scripts/safeplane` — launcher/dispatcher only. Networked commands execute
  `cli-connector`; local administration is delegated to focused scripts.
- `scripts/safeplane-chat` — deprecated compatibility alias to `scripts/safeplane`;
  it contains no HTTP implementation.
- `scripts/safeplane-vps` and `scripts/compose-safeplane-vps` — VPS lifecycle and
  production Compose selection.

## MCP services

- `mcp-servers/calendar-task/`
- `mcp-servers/notification-task/`
- `mcp-servers/dev-workspace/`

The harness is the MCP client/broker. MCP services do not grant workflow
permissions.

## Contracts and prompts

- `safeplane.yaml` — runtime registry/configuration.
- `workflows/` — workflow contracts.
- `prompts/` — versioned prompt content and manifests.

## Runtime composition

- `docker-compose.yml` — base services and internal networks, including the
  profiled `cli-connector` service.
- `docker-compose.local.yml` — loopback development exposure.
- `docker-compose.test.yml` — deterministic test exposure.
- `docker-compose.real.yml`, `docker-compose.telegram.yml`,
  `docker-compose.developer.yml`, and GitHub overlays — explicit capability
  additions.

## Tests

- `tests/unit/test_connector_client.py` — shared client contract/error tests.
- `tests/unit/test_cli_connector.py` — Python CLI parsing, request, rendering,
  JSON, and exit-code tests.
- `tests/unit/test_cli_launcher.py` — host launcher boundary tests.
- `tests/scripts/accept-cli-connector` — real Compose/container boundary proof.
- existing unit, acceptance, security, and workflow suites remain authoritative
  for unchanged behavior.
