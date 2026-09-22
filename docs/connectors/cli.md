# CLI connector

The CLI is an explicit Python connector that runs as one short-lived container
per networked operator command.

## Responsibilities

The CLI connector may:

- parse deterministic operator arguments;
- request the harness `auto` entrypoint without interpreting routing results itself;
- validate CLI-only constraints before network access;
- call the shared connector or control client;
- render terminal output;
- emit stable JSON output;
- map failures to stable process exit codes.

It does not own workflow stage order, run/session state, permissions, model
calls, MCP calls, repository writes, Git operations, approval validation, or
remote-write enforcement.

## Launch path

```text
operator
  -> scripts/safeplane
  -> docker compose run --rm --no-deps -T cli-connector ...
  -> connector-harness
  -> harness
```

`scripts/safeplane` contains no harness URL or request/payload logic. The
container receives `SAFEPLANE_HARNESS_URL=http://harness:8080` from Compose.

## Boundary

The service:

- runs as `10001:10001`;
- uses a read-only root filesystem;
- drops all Linux capabilities;
- enables `no-new-privileges`;
- has bounded tmpfs, PID, CPU, and memory limits;
- has `restart: "no"`;
- publishes no port;
- mounts no host/runtime path;
- receives no Docker secret;
- joins only `connector-harness`.

Consequently it cannot directly resolve services that exist only on model or
MCP networks.

## Commands

```text
workflows
runs
status <run-id>
approve-patch <run-id> <proposal-id>
approve-pr <run-id>
auto [--repo <profile>] [--session <ref>] <message>
chat [--session <ref>] <message>
assistant [--session <ref>] <message>
developer [--session <ref>] <message>
develop [--repo <profile>] [--session <ref>] <task>
run <entrypoint> [--repo <profile>] [--session <ref>] <message>
```

`--repo` is rejected before network access unless the selected entrypoint is
`develop` or `auto`. For `auto`, repository context is supplied to the routing
advisor and is still validated deterministically before the developer workflow
can run.

`auto` is optional. `chat`, `assistant`, `develop`, `developer`, and
`run <entrypoint>` remain deterministic explicit routing surfaces.

Use `--output json` for machine-readable output. A message beginning with `-`
can be passed after `--`.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | success |
| `2` | CLI usage/validation error |
| `3` | harness unavailable |
| `4` | authentication/authorization rejection |
| `5` | harness rejected the request |
| `6` | invalid harness protocol/response |
| `7` | workflow request returned a non-completed status |

## Compatibility alias

`scripts/safeplane-chat` remains temporarily as a deprecation wrapper to
`scripts/safeplane`. It performs no HTTP request itself.

## Validation

```bash
tests/scripts/test-unit -q
tests/scripts/accept-cli-connector
```
