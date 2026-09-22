# Safeplane operations

The primary operator entry point is `./scripts/safeplane`. Networked workflow,
run, and approval commands execute inside the one-shot CLI connector; local
filesystem administration commands continue to dispatch to focused host tools.

## Local fake mode

```bash
make setup
make up
./scripts/safeplane chat "Reply with a short confirmation."
./scripts/safeplane auto "Remind me tomorrow morning to review the release notes."
./scripts/safeplane workflows
make down
```

`make up` builds the CLI connector image and starts the fake runtime. If an
operator invokes a connector command before that image exists, the launcher
builds it once before running the command.

The local overlay may publish the harness on loopback for development and direct
HTTP diagnostics, but the CLI itself always calls `http://harness:8080` over
`connector-harness`.

## JSON output

Networked connector/control commands accept `--output json` either before or
after the command arguments:

```bash
./scripts/safeplane workflows --output json
./scripts/safeplane status <run-id> --output json
```

JSON mode writes only JSON to stdout. Diagnostics remain on stderr.

## VPS deployment

Use the existing guarded VPS interface:

```bash
./scripts/safeplane-vps preflight
./scripts/safeplane-vps config
./scripts/safeplane-vps start
./scripts/safeplane-vps status
```

`safeplane-vps start` explicitly builds the profiled `cli-connector` image before
reconciling the long-running stack. The CLI service is not started by normal
Compose `up`; each operator invocation creates and removes one container.

After deployment, exercise at least:

```bash
./scripts/safeplane workflows
./scripts/safeplane chat "Reply with a short confirmation."
./scripts/safeplane runs
```

For the developer profile, also run a bounded fake or deliberately configured
real developer workflow before publication.

## Connector boundary validation

Static/unit checks:

```bash
tests/scripts/test-unit -q
```

Runtime connector boundary proof:

```bash
tests/scripts/accept-cli-connector
```

The runtime check proves harness reachability while denying runtime mounts,
secret mounts, Docker-socket access, model-service resolution, and MCP-service
resolution from the CLI container.

## Routing advisor validation

Automatic routing is covered by the normal offline unit suite. To exercise the
real Jev decision path through the production model-gateway transport, run:

```bash
make test-routing-jev
```

The live suite is opt-in, requires the normal OpenRouter secret, and performs
provider calls only for routing decisions. It does not run downstream workflow
model inference.

## CLI connector troubleshooting

- **Image missing or stale:** run `docker compose -f docker-compose.yml build cli-connector`.
  The launcher builds a missing image automatically; explicit rebuilds are appropriate after
  source changes and are already part of `make up` and `safeplane-vps start`.
- **Harness unavailable:** confirm the long-running stack is healthy with the mode-specific
  status command before retrying. `docker compose run --no-deps` deliberately does not start
  the harness implicitly.
- **Compose project mismatch:** invoke the launcher from the same checkout/project context used
  to start Safeplane, and preserve any explicit `COMPOSE_PROJECT_NAME`. The one-shot container
  must join the same `connector-harness` network as the running harness.
- **CI/non-TTY use:** the launcher always uses `-T`; no pseudo-TTY is required. Prefer
  `--output json` for machine consumers.
- **Offline host:** a missing connector image cannot be built without the required base/build
  image material. Pre-build or preload `safeplane-cli-connector:latest` before disconnecting.

## Detailed task guide

See [Safeplane operations](scripts.md), [runtime modes](runtime-modes.md), and
[VPS operations](vps-operations.md) for the existing mode-specific commands and
recovery procedures.
