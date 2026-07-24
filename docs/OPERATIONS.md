# Operations

> Generated with `ai-craftkit` skill: `archdoc`  
> Source: `git@github-safeplane:stefanrossmeier/safeplane.git` at commit `f037db0a92226a56fb047cf2bfd43871e4dd0bd2`  
> Prompt: `Provide the documents for this repo`

Last Reviewed Scope: full review
Doc Status: DRAFT
Last Operations Update: 2026-07-23T18:38:28Z
Updated By: agent
Source Basis: README scan; existing docs; code scan; deployment files; test scripts

## Purpose

This document describes how Safeplane runs locally and in its documented runtime modes: startup shape, configuration, secrets, runtime data, debugging, failure modes, cleanup, and operational verification. Endpoint and tool contract details are intentionally kept in `API_SURFACE.md`.

## Runtime Overview

The normal runtime is a Docker Compose stack. The base stack contains `harness`, `model-gateway`, `calendar-task-mcp`, `notification-task-mcp`, and `scheduler`. Overlays selectively add loopback host publication, real provider access, Telegram delivery, developer workspace services, or a GitHub mock.

The default validation posture is local and fake: no external model call, no public host exposure beyond loopback, and no secrets required unless a guarded real mode is selected.

## Local Development Quick Start

Requirements from repository docs and scripts:

- Docker Engine and Docker Compose plugin
- Python 3.11+
- `make`, `git`, `curl`

Minimal setup:

```bash
python3 -m pip install -r requirements-dev.txt
make setup
make up
./scripts/safeplane chat "Reply with a short confirmation."
make down
```

Equivalent fake-mode wrapper:

```bash
tests/scripts/compose-safeplane-fake up -d --build
tests/scripts/compose-safeplane-fake down
```

## Execution Model

| Runtime concern | Operational owner |
| --- | --- |
| workflow dispatch and session continuation | harness |
| model call execution | model-gateway |
| tool call policy and validation | harness |
| calendar mutation | calendar MCP and calendar store |
| notification schedule mutation | notification MCP |
| scheduled notification execution | scheduler |
| Telegram ingress and outbound delivery | telegram connector |
| repository preparation, patch validation, checks, publication | harness with developer MCP services |

Important operational constraint: the developer workflow is single-pass. A `REQUEST_CHANGES` review result does not automatically restart analysis or implementation; the operator starts a new run.

## Runtime Modes

| Mode | Compose shape | Secrets required | Host publication |
| --- | --- | --- | --- |
| fake local | base + local overlay | none | harness on `127.0.0.1:8787` |
| real provider local | base + local + real overlay | OpenRouter file secret | harness on `127.0.0.1:8787` |
| Telegram fake | base + local + Telegram overlay, fake model | Telegram bot token and allowlist | no app port |
| Telegram real | base + local + real + Telegram overlay | OpenRouter plus Telegram secrets | no app port |
| developer fake | base + local + developer overlay | optional repo config; no provider secret | harness on loopback |
| developer real | base + local + developer + real overlay | OpenRouter and repo config | harness on loopback |
| developer GitHub fake or real | developer mode plus GitHub or GitHub mock overlays | GitHub token for real publication | harness on loopback |

Operational source of truth for combinations is `tests/scripts/status-safeplane-mode` plus the Compose overlays.

## Environment And Secrets

Core filesystem roots:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAFEPLANE_HOME` | `$HOME/.safeplane` | runtime state, logs, workspaces, data, config |
| `SAFEPLANE_SECRET_ROOT` | `$HOME/.config/safeplane/secrets` | local secret files, always outside runtime root |

Per-secret file overrides documented in the repo:

- `SAFEPLANE_OPENROUTER_API_KEY_FILE`
- `SAFEPLANE_GITHUB_TOKEN_FILE`
- `SAFEPLANE_TELEGRAM_BOT_TOKEN_FILE`
- `SAFEPLANE_TELEGRAM_ALLOWED_USER_IDS_FILE`

Verified secret ownership:

- OpenRouter secret -> `model-gateway` only
- GitHub token -> `harness` only
- Telegram bot token and Telegram allowlist -> `telegram-connector` only
- MCP services, scheduler, GitHub mock, and developer check service receive no secrets

## Configuration Points

| Config file | Runtime role |
| --- | --- |
| `safeplane.yaml` | entrypoints, workflow registry, model gateway endpoint, MCP endpoints |
| `workflows/*.yaml` | model profiles, prompt contract, session and tool rules |
| `prompts/*` | prompt text and fake model responses |
| `config/repositories.example.yaml` | sample repository profiles for developer runs |
| Compose overlays | mode-specific wiring, networks, ports, and secret mounts |

Developer mode also honors:

- `SAFEPLANE_REPOSITORY_CONFIG`
- `SAFEPLANE_DEVELOPER_SOURCE_ROOT`
- `SAFEPLANE_ARCHDOC_REPOSITORY_URL`
- `SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES`

## Docker And Container Notes

Operationally important container policies visible in Compose files:

- all long-running services use UID and GID `10001:10001`;
- services use read-only root filesystems;
- Linux capabilities are dropped;
- `no-new-privileges` is enabled;
- services have health checks and bounded CPU, memory, PID, and tmpfs limits;
- service-to-service traffic primarily uses internal Docker networks;
- only the loopback harness port is published in normal local operation;
- `dev-check-mcp` runs with `network_mode: none` and a Unix socket control channel.

## Deployment Notes

Safeplane is already deployed on a MacBook and on a VPS, and those environments
are used for assistant and developer work. The repository includes
`scripts/safeplane-vps`, `scripts/prepare-vps-layout`, and
`docs/vps-operations.md` to support that operating model. The remaining gap is
not whether deployment exists, but how repeatable, recoverable, and fully
documented that deployment story is.

## Scheduling And Triggers

| Trigger | Runtime path |
| --- | --- |
| local CLI message | `scripts/safeplane*` -> harness |
| Telegram command or plain text | telegram connector long polling -> harness |
| assistant calendar tool | harness -> calendar MCP |
| assistant notification tool | harness -> notification MCP -> scheduler reload |
| scheduled notification due time | scheduler reconciles stored schedules and dispatches delivery |
| developer run start | harness prepares isolated repo workspace and stage artifacts |
| remote publication approval | harness validates bindings and performs non-force push plus draft PR |

## External Runtime Dependencies

| Dependency | When used | Owner |
| --- | --- | --- |
| OpenRouter | real model mode only | model-gateway |
| Telegram Bot API | Telegram modes and outbound Telegram notifications | telegram connector |
| Git and GitHub | developer repository preparation and optional draft PR publication | harness |
| GitHub mock | acceptance only | harness test overlay |

## One Real User Action Trace

### `safeplane develop --repo <profile> "Implement one bounded change"`

```text
operator command
-> scripts/safeplane
-> scripts/safeplane-chat generic connector client
-> harness POST /connector/develop
-> harness validates repo profile and prepares isolated workspace
-> developer pipeline stages run in fixed order
-> model-gateway serves stage model calls
-> dev-workspace MCP serves read-only repo inspection and patch proposal
-> dev-check service runs declared checks on disposable candidate copy
-> harness applies accepted result and records evidence
-> review and PR proposal stages complete
-> optional remote approval path performs non-force push and one draft PR
```

The critical operational property is that repo mutation and publication are both harness-owned. The model and MCP services never become authoritative writers on their own.

## Runtime Data And Persistence

| Directory class | Default location | Behavior |
| --- | --- | --- |
| sessions and runs | `${SAFEPLANE_HOME}/sessions`, `${SAFEPLANE_HOME}/runs` | preserved by normal cleanup |
| traces, artifacts, inactive workspaces, checkouts | under `${SAFEPLANE_HOME}` | eligible for age-based cleanup |
| application data | `${SAFEPLANE_HOME}/data` | protected |
| operator config | `${SAFEPLANE_HOME}/config` | protected |
| backups | `${SAFEPLANE_HOME}/backups` | protected, but not proof of full restore support |
| maintenance audit | `${SAFEPLANE_HOME}/maintenance` | cleanup records |

Evidence bundles are written under `${SAFEPLANE_HOME}/evidence-bundles/<run-id>`.

## Logging And Observability

| Artifact | Where it lives | Notes |
| --- | --- | --- |
| harness traces | `${SAFEPLANE_HOME}/traces/<session>/turn_*` | per-turn JSONL evidence |
| model gateway traces | same trace tree | model request and response metadata |
| MCP logs | `${SAFEPLANE_HOME}/logs/mcp` | capability-local JSONL |
| scheduler logs | `${SAFEPLANE_HOME}/logs/scheduler` | scheduler activity |
| Telegram connector logs and state | `${SAFEPLANE_HOME}/logs/connectors/telegram`, `${SAFEPLANE_HOME}/connectors/telegram` | local connector events and chat mapping |
| run evidence bundle | `${SAFEPLANE_HOME}/evidence-bundles/<run-id>` | copied artifacts plus manifest |

Useful inspection commands:

```bash
./scripts/safeplane runs
./scripts/safeplane status <run-id>
./scripts/safeplane evidence <run-id>
./scripts/safeplane maintenance storage --json
tests/scripts/status-safeplane-mode
```

## Debugging Guide

| Symptom | Inspect first |
| --- | --- |
| harness does not become healthy | `make logs`, harness health check, `docker-compose.local.yml` port binding |
| model calls fail in real mode | `MODEL_GATEWAY_MODE`, OpenRouter secret mount, model-gateway traces |
| Telegram commands rejected | Telegram allowlist file, connector logs, `from.id` versus `chat.id` confusion |
| assistant notification changes do not take effect immediately | notification MCP logs, scheduler `/reload`, scheduler status |
| developer run stalls or fails | `./scripts/safeplane status <run-id>`, developer workspace artifacts, check evidence |
| draft PR approval fails | repository profile fields, remote approval request artifact, GitHub credential mount, base branch movement |

## Failure Modes

| Failure mode | Likely symptom | Verified behavior |
| --- | --- | --- |
| missing secret in real mode | model or connector startup failure | docs and wrappers call this out explicitly |
| scheduler reload failure after notification write | notification saved but delivery state lags | notification output includes a reload warning |
| unknown or disabled workflow | connector call fails | harness returns HTTP error |
| changed workspace or moved base branch before publication | approve-pr fails | remote write revalidates immutable bindings |
| unauthorized Telegram user | command rejection | connector rejects before workflow dispatch |
| expired or missing workspace snapshot | developer MCP call failure | dev workspace tools validate `run_id` and visible repo state |

## Manual Recovery Notes

| Situation | Recovery path |
| --- | --- |
| stale inactive traces or workspaces | `./scripts/safeplane maintenance clean --dry-run --older-than 30d` then rerun without `--dry-run` |
| broken local runtime state but keep data and config | `./scripts/safeplane maintenance clean-all --confirm DELETE` |
| developer run needs publication retry | `./scripts/safeplane approve-pr <run-id>` |
| Telegram mapping confusion | `/new` in Telegram or inspect connector session map |
| calendar store consistency concerns | `./scripts/safeplane calendar cleanup` or `rebuild-index` |

## Backup And Persistent State

There is no complete runtime backup and restore package yet. The repo explicitly warns against inferring that from the presence of a `backups` directory. Verified safety interfaces are narrower:

- `./scripts/safeplane calendar snapshot`
- `./scripts/safeplane calendar reset --dry-run`
- `./scripts/safeplane calendar reset --confirm RESET_CALENDAR`

Calendar reset creates a calendar backup before reset. That is not equivalent to a full Safeplane runtime restore plan.

## Security Operations

- Keep `SAFEPLANE_SECRET_ROOT` outside `SAFEPLANE_HOME`.
- Never place secrets in `.env` files or tracked repository config.
- Prefer fake mode for ordinary validation.
- Use dedicated repositories for guarded real GitHub draft PR smokes.
- Treat any change to Compose secret mounts, internal networks, or dev-check isolation as a security-sensitive change.

## Validation

Focused validation entry points already provided by the repo:

| Check | Scope |
| --- | --- |
| `tests/scripts/test-unit -q` | unit coverage |
| `tests/scripts/accept-documentation` | docs, links, runtime layout, and command contract |
| `tests/scripts/check-repository-hygiene` | neutral naming and generated-artifact hygiene |
| `tests/scripts/accept-runtime-hardening` | running-container hardening and boundary checks |
| `tests/scripts/accept-telegram-workflows` | Telegram command path |
| `tests/scripts/accept-developer-workflow` | full developer workflow fixture |
| guarded real validation scripts under `tests/scripts/` | deliberate real-system smokes only |

## Safe Change Workflow

1. Pick the owning boundary first: connector, harness, model gateway, scheduler, MCP server, workflow contract, or script.
2. Validate the narrowest path that proves the change.
3. Keep fake and real mode expectations separate.
4. If the change affects repo mutation or publication, inspect remote-write and developer-workspace boundaries before editing.
5. Update docs when changing workflow exposure, runtime modes, or security assumptions.

## Operational Gaps And Known Unknowns

- A full backup, restore, rollback, and recovery drill package is not implemented.
- I did not run the live Docker stack during documentation generation, so runtime descriptions rely on code, Compose, test scripts, and existing docs rather than observed container logs.