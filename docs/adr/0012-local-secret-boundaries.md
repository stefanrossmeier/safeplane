# ADR 0012: Local secret boundaries

> Superseded in part by ADR 0028 for host secret paths, mounts, and network boundaries.
Status: accepted

## Context

MVP 0 used temporary environment-variable based secret handling.

Safeplane will accumulate more secrets over time, including provider keys, connector tokens, calendar storage keys, and GitHub tokens.

Secrets must not become globally available to the harness, workflows, MCP servers, or future developer containers.

## Decision

Safeplane uses local secret files under `SAFEPLANE_HOME/secrets` as the source of truth for local development.

For Docker Compose real-mode provider access, Safeplane uses Compose secrets backed by those files.

For MVP 1, the implemented secret is:

    ~/.safeplane/secrets/openrouter_api_key

It is mounted only into:

    model-gateway

At container path:

    /run/secrets/openrouter_api_key

The base Compose stack does not mount provider secrets.

A separate real-mode override file is used:

    docker-compose.real.yml

Fake mode does not require provider secrets.

The model gateway reads the OpenRouter API key from `/run/secrets/openrouter_api_key` first.

`OPENROUTER_API_KEY` remains a temporary fallback for direct/manual execution compatibility, but `.env.example` no longer documents it as the primary local secret mechanism.

## Consequences

Positive:

- Fake mode works without real secrets.
- Real mode uses a standard `/run/secrets/...` path.
- OpenRouter API key is scoped to model-gateway.
- The same pattern can be extended to Telegram, calendar, GitHub, and MCP servers later.
- Secrets are not committed to the repository.

Tradeoffs:

- Local secrets are still plain files on disk.
- This is not Vault, KMS, or an enterprise secret manager.
- Local rotation is manual file replacement plus service restart.

## Rejected alternatives

### Put all secrets in `.env`

Rejected because `.env` makes it too easy to pass secrets broadly and accidentally treat them like normal configuration.

### Mount the whole secrets directory into every service

Rejected because this breaks service-specific secret boundaries.

### Add Vault or cloud KMS now

Rejected because it is too heavy for the current local-first MVP.
