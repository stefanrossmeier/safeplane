# Repository Map

> Generated with `ai-craftkit` skill: `archdoc`  
> Source: `git@github-safeplane:stefanrossmeier/safeplane.git` at commit `f037db0a92226a56fb047cf2bfd43871e4dd0bd2`  
> Prompt: `Provide the documents for this repo`

Last Reviewed Scope: full review
Doc Status: DRAFT
Last Repo Map Update: 2026-07-23T18:38:28Z
Updated By: agent
Source Basis: README scan; existing docs; code scan; deployment files; test scripts

## Overview

Safeplane is a local-first control plane for bounded AI-agent workflows. The repository is organized around one authority service (`harness`), one model isolation service (`model-gateway`), several narrow MCP servers, optional connectors, and versioned workflow and prompt contracts. The repository already contains extensive supporting documentation under `docs/`; the generated files in this set are an orientation layer over that material.

The dominant design pattern is: thin operator interface -> harness-owned orchestration -> model and tool access behind explicit boundaries -> evidence and controlled write or publication. This is described consistently in `README.md`, `docs/repo-layout.md`, `docs/developer-pipeline.md`, `docs/mcp.md`, and the Compose overlays.

## README Reality Check

| Topic | README says | Repository shows | Status | Gap / note |
| --- | --- | --- | --- | --- |
| Local setup | `python3 -m pip install -r requirements-dev.txt`, `make setup` | `requirements-dev.txt`, `Makefile` `setup`, `scripts/prepare-runtime-layout` exist | verified | Matches implementation |
| Local run | `make up`, then `./scripts/safeplane ...` | `Makefile` `up`, `down`, `wait`, `chat`; `scripts/safeplane` and `scripts/safeplane-chat` exist | verified | Matches implementation |
| Harness exposure | harness published only on `127.0.0.1:8787` | `docker-compose.local.yml` publishes `127.0.0.1:${SAFEPLANE_HARNESS_PORT:-8787}:8080` | verified | Test overlay publishes `127.0.0.1:18787` instead |
| Runtime data split | runtime under `SAFEPLANE_HOME`, secrets under `SAFEPLANE_SECRET_ROOT` | `scripts/prepare-runtime-layout`, `docs/security/secrets.md`, Compose secret mounts all follow this split | verified | Important boundary for all runtime work |
| Developer workflow | `./scripts/safeplane develop --repo <profile> ...` runs a single-pass bounded workflow | `safeplane.yaml`, `workflows/developer/workflow.yaml`, `docs/developer-pipeline.md`, `docker-compose.developer.yml` all support this | verified | Publication remains draft-PR only |
| Runtime modes | fake, real, Telegram, GitHub publication, VPS deployment | Mode-specific Compose overlays and `docs/runtime-modes.md` exist | verified | VPS operation is current; packaging and recovery documentation still need tightening |
| Production readiness | deployed on MacBook and VPS with assistant and developer usage | `docs/vps-operations.md` and README document active deployment, while backup or restore and recovery evidence remain follow-up work | verified | Distinguish active deployment from fully hardened recovery packaging |

## Top-Level Map

| Path | What it contains | Why it matters |
| --- | --- | --- |
| `README.md` | product and operator overview | best high-level entry point |
| `safeplane.yaml` | connector, entrypoint, workflow, model-gateway, and MCP registry | central runtime contract |
| `services/` | harness, model-gateway, scheduler | core runtime services |
| `mcp-servers/` | calendar, notification, dev-workspace MCP servers | tool boundary implementations |
| `connectors/telegram/` | optional Telegram transport adapter | external operator interface |
| `scripts/` | operator CLI wrappers and maintenance helpers | normal local entry points |
| `workflows/` | workflow contracts per capability | model/runtime behavior contracts |
| `prompts/` | versioned prompt bundles and fake responses | prompt-side contract surface |
| `config/` | sample operator-owned config | repository profile and runtime examples |
| `tests/` | unit, integration, acceptance, shell validation | confidence and smoke coverage |
| `docs/` | design, security, runtime, and acceptance notes | deeper subsystem reference |
| `docker-compose*.yml` | base stack and mode overlays | runtime shape and boundaries |

## Important File Index

| File | Role |
| --- | --- |
| `safeplane.yaml` | Registry of entrypoints, workflows, connectors, model gateway, and MCP services |
| `services/harness/src/harness/main.py` | Harness HTTP API and orchestration entrypoints |
| `services/harness/src/harness/agent_runtime.py` | Generic workflow runtime invoked by harness |
| `services/harness/src/harness/developer_pipeline.py` | Fixed developer workflow orchestration |
| `services/harness/src/harness/repository_workspace.py` | Target repo preparation and isolated workspace handling |
| `services/harness/src/harness/remote_write.py` | Harness-owned branch push and draft PR publication |
| `services/model-gateway/src/model_gateway/main.py` | Fake or real model mediation API |
| `services/scheduler/src/safeplane_scheduler/main.py` | Notification scheduling and delivery control API |
| `mcp-servers/calendar-task/src/calendar_task_mcp/main.py` | Calendar MCP JSON-RPC service |
| `mcp-servers/notification-task/src/notification_task_mcp/main.py` | Notification MCP JSON-RPC service |
| `mcp-servers/dev-workspace/src/dev_workspace_mcp/main.py` | Read-only, apply, and check service for developer runs |
| `connectors/telegram/src/telegram_connector/main.py` | Telegram long-polling connector |
| `scripts/safeplane` | top-level CLI dispatcher |
| `scripts/safeplane-chat` | HTTP CLI client for harness workflow commands |
| `scripts/safeplane-calendar` | local calendar admin CLI |
| `scripts/safeplane-maintenance` | runtime storage and cleanup CLI |
| `workflows/developer/workflow.yaml` | single-pass developer workflow contract |
| `docs/developer-pipeline.md` | best current explanation of the developer path |

## Main Entry Paths

| Entry path | Backing owner | Notes |
| --- | --- | --- |
| `./scripts/safeplane chat ...` | harness `POST /connector/chat` | synchronous chat workflow |
| `./scripts/safeplane assistant ...` | harness `POST /connector/assistant` | assistant workflow with calendar and notification tools |
| `./scripts/safeplane develop --repo <profile> ...` | harness `POST /connector/develop` | asynchronous developer workflow |
| Telegram commands | telegram connector -> harness | optional connector overlay only |
| `./scripts/safeplane calendar ...` | local Python CLI using harness calendar store module | bypasses harness HTTP; admin utility |
| `make up` / Compose wrappers | Docker Compose | normal local runtime startup |

## Commands and Runners

| Command | Purpose |
| --- | --- |
| `make setup` | prepare split runtime layout |
| `make up` / `make down` | start and stop default fake local stack |
| `make smoke-real MESSAGE="..."` | guarded real provider smoke |
| `make telegram-up` / `make telegram-down` | start or stop Telegram overlay |
| `./scripts/safeplane workflows` | list exposed workflows |
| `./scripts/safeplane runs` | list recorded runs |
| `./scripts/safeplane status <run-id>` | inspect one run |
| `./scripts/safeplane evidence <run-id>` | collect an evidence bundle |
| `./scripts/safeplane approve-pr <run-id>` | retry or authorize draft-PR publication |
| `./scripts/safeplane maintenance ...` | storage and cleanup operations |
| `tests/scripts/test-unit` | run unit tests |
| `tests/scripts/accept-documentation` | documentation contract checks |
| `tests/scripts/check-repository-hygiene` | repository naming and artifact hygiene checks |

## Test Suite Map

| Area | Location | Scope |
| --- | --- | --- |
| Unit tests | `tests/unit/` | core runtime modules, schemas, compose integrity, developer pipeline, remote write, maintenance |
| Acceptance tests | `tests/acceptance/` | workflow behavior, calendar tools, MCP boundary, runtime hardening, Telegram command behavior |
| Scripted acceptances | acceptance scripts under `tests/scripts/` | Docker-backed or multi-step validation paths |
| Integration tests | `tests/integration/` | present as a bucket, but not the main documented validation surface yet |
| Fixtures | `tests/fixtures/` | GitHub mock and local test assets |

## Module Overview

| Module area | Responsibility |
| --- | --- |
| `services/harness/src/harness/` | orchestration, session and run state, developer pipeline, MCP brokering, patch approval, remote write, repository workspace preparation |
| `services/model-gateway/src/model_gateway/` | fake and real model calls, workflow model profile loading, model trace recording |
| `services/scheduler/src/safeplane_scheduler/` | persisted notification scheduling and delivery orchestration |
| `mcp-servers/calendar-task/` | calendar CRUD through JSON-RPC tools |
| `mcp-servers/notification-task/` | notification scheduling, list, cancel, and scheduler reload bridge |
| `mcp-servers/dev-workspace/` | developer repository inspection, patch proposal, patch apply, and declared check execution |
| `connectors/telegram/src/telegram_connector/` | transport adapter for Telegram commands, chat mapping, outbound notification delivery |

## Configuration and Runtime Files

| Path | Notes |
| --- | --- |
| `config/repositories.example.yaml` | example repository profile and GitHub credential profile |
| `docker-compose.yml` | base stack: harness, model-gateway, calendar-task-mcp, notification-task-mcp, scheduler |
| `docker-compose.local.yml` | loopback harness port publication |
| `docker-compose.real.yml` | real model provider overlay and OpenRouter secret mount |
| `docker-compose.telegram.yml` | Telegram connector overlay and Telegram secret mounts |
| `docker-compose.developer.yml` | developer workspace, apply, and check services |
| `docker-compose.github.yml` | harness-only GitHub token mount |
| `docker-compose.github-mock.yml` | test-only GitHub API mock |
| `docker-compose.test.yml` | alternate local test harness port |

## Generated and Runtime Paths

The repo intentionally keeps runtime state out of source control.

| Path class | Default location | Notes |
| --- | --- | --- |
| runtime root | `${SAFEPLANE_HOME:-$HOME/.safeplane}` | sessions, runs, traces, workspaces, data, logs, config |
| secret root | `${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}` | outside runtime root by policy |
| evidence bundles | `${SAFEPLANE_HOME}/evidence-bundles/<run-id>` | collected run artifacts |
| developer workspaces | `${SAFEPLANE_HOME}/workspaces/<run-id>` | isolated repo snapshots and pipeline artifacts |

## Vocabulary

| Term | Meaning in this repo |
| --- | --- |
| harness | authority boundary for stage order, tools, validation, evidence, Git, and remote write |
| connector | transport adapter only; does not own workflow logic |
| workflow | versioned contract describing prompt, model profiles, concurrency, tools, and I/O |
| MCP service | tool implementation behind harness policy and validation |
| fake mode | no real provider secret or external model call |
| real mode | OpenRouter-backed model-gateway path |
| repository profile | operator-owned target-repository config for developer runs |
| remote write | harness-owned non-force push plus draft PR creation |

## Search Hints For Agents

- Search `connector_entrypoint` in `services/harness/src/harness/main.py` for workflow ingress.
- Search `developer_pipeline` in `services/harness/src/harness/` for staged repo-changing behavior.
- Search `allowed_servers` in `workflows/` for tool permissions.
- Search `SAFEPLANE_` across Compose files and `scripts/` for configuration flow.
- Search `notification_schedule` and `calendar_` in `services/harness/src/harness/notification_schemas.py` and `services/harness/src/harness/mcp_schemas.py` for tool contracts.
- Search `remote_write_allowed` and `draft_pr_creation` for publication policy.

## Recommended Reading Order

1. `README.md`
2. `safeplane.yaml`
3. `docs/repo-layout.md`
4. `docs/developer-pipeline.md`
5. `docs/mcp.md`
6. `docs/security/runtime-boundaries.md`
7. `workflows/developer/workflow.yaml`
8. `services/harness/src/harness/main.py`

## Agent Work Guide

Before changing code:

1. Identify whether the change belongs to a connector, harness orchestration path, MCP service, scheduler path, or workflow contract.
2. Read the closest workflow YAML and the closest tests before editing runtime logic.
3. If the task touches developer runs, inspect `docs/developer-pipeline.md`, `docs/repository-workspaces.md`, and `docs/remote-write.md` first.
4. If the task touches an interface, update `API_SURFACE.md` assumptions and verify the corresponding scripts or tests.
5. Prefer the narrowest change at the owning boundary; do not move policy from harness into connectors or MCP services.
6. Run the narrowest relevant check first, then broader shell or Docker acceptances only when necessary.

Rules:

- Do not invent a new control path when a workflow contract or existing script already defines one.
- Keep fake-mode and real-mode behavior distinct.
- Preserve the secret-root versus runtime-root boundary.
- Mark uncertain claims instead of assuming production behavior from local-only evidence.

## High-Risk Areas

| Area | Why it is risky | Inspect first |
| --- | --- | --- |
| `services/harness/src/harness/remote_write.py` and publication overlays | can push branches or create draft PRs | `docs/remote-write.md`, repository profile config, remote-write tests |
| developer workspace and patch-apply path | controls read-only versus writable repo copies | `docker-compose.developer.yml`, `mcp-servers/dev-workspace/`, developer pipeline docs |
| secret handling and Compose mounts | secret leakage would break the repo's core safety claim | `docs/security/secrets.md`, Compose secret sections |
| scheduler and notification bridge | reload failures can create delayed or stale notifications | `services/scheduler/`, `mcp-servers/notification-task/` |
| workflow YAML and prompt versions | changes alter model behavior and permissions across the system | `safeplane.yaml`, `workflows/`, `prompts/` |

## Current Repository Health

- Existing subsystem documentation is strong and internally consistent.
- The worktree is dirty and includes many untracked files in this checkout; generated docs should be treated as documentation for the current workspace snapshot, not a clean release state.
- The archdoc template files were not present in the repository. This generated set uses the structure required by the supplied skill.
- The docs now reflect active MacBook and VPS deployment, but backup or restore packaging and recovery evidence remain partial.

## Known Unknowns

- I did not run the full Docker stack during generation, so runtime behavior is grounded in code, Compose files, test scripts, and existing docs rather than live containers.
- `tests/integration/` exists, but its current intended coverage was not inspected in detail because the dominant validation surfaces are unit, acceptance, and shell acceptance scripts.