# API Surface

> Generated with `ai-craftkit` skill: `archdoc`  
> Source: `git@github-safeplane:stefanrossmeier/safeplane.git` at commit `f037db0a92226a56fb047cf2bfd43871e4dd0bd2`  
> Prompt: `Provide the documents for this repo`

Last Reviewed Scope: full review
Doc Status: DRAFT
Last API Surface Update: 2026-07-23T18:38:28Z
Updated By: agent
Source Basis: README scan; existing docs; code scan; deployment files; test scripts

## Purpose

This document inventories the repository's public and integration-relevant interfaces: operator CLIs, Telegram commands, internal HTTP endpoints, MCP tool contracts, and configuration contracts that materially affect integrations. These are mostly internal or operator-local interfaces rather than a general public web API.

## Evidence Legend

| Status | Meaning |
| --- | --- |
| verified | directly confirmed from code, config, tests, or docs |
| inferred | likely true, but not fully enumerated from implementation |
| missing | expected interface detail was searched for but not found |

## API Surface Summary

| Surface | Owner | Audience | Transport |
| --- | --- | --- | --- |
| operator CLI wrappers | `scripts/` | local operator | shell + HTTP |
| Telegram workflow commands | telegram connector | Telegram operator | Telegram Bot API + internal HTTP |
| harness control API | `services/harness` | CLI, connector, internal tooling | HTTP JSON |
| model gateway API | `services/model-gateway` | harness only | HTTP JSON |
| scheduler control API | `services/scheduler` | notification MCP and operators | HTTP JSON |
| MCP tool APIs | `mcp-servers/*` and harness MCP broker | harness only | HTTP JSON-RPC |
| workflow and repository config | YAML files | operators and harness | file contract |

## Interface Inventory

| Interface | Implementation | Primary change risk |
| --- | --- | --- |
| `safeplane` CLI command family | `scripts/safeplane`, `scripts/safeplane-chat`, `scripts/safeplane-calendar`, `scripts/safeplane-maintenance` | breaking operator flows or docs |
| Telegram command set | `connectors/telegram/src/telegram_connector/main.py`, `docs/connectors/telegram.md` | auth mistakes or wrong workflow exposure |
| harness routes | `services/harness/src/harness/main.py` | workflow ingress, approvals, MCP brokering |
| model `/chat` | `services/model-gateway/src/model_gateway/main.py` | model call failures or schema drift |
| scheduler `/reload` and `/status` | `services/scheduler/src/safeplane_scheduler/main.py` | stale notification schedules |
| calendar JSON-RPC tools | `mcp-servers/calendar-task/src/calendar_task_mcp/main.py` | assistant tool breakage |
| notification JSON-RPC tools | `mcp-servers/notification-task/src/notification_task_mcp/main.py` | scheduling or delivery drift |
| developer workspace MCP tools | `mcp-servers/dev-workspace/src/dev_workspace_mcp/main.py`, `services/harness/src/harness/dev_workspace_schemas.py` | safety boundary regressions |

## CLI Surface

### Top-level `safeplane`

| Command | Backing behavior | Notes |
| --- | --- | --- |
| `safeplane help` | prints command guide | shell-only help |
| `safeplane chat <message>` | POST `/connector/chat` | synchronous, session-capable |
| `safeplane assistant <message>` | POST `/connector/assistant` | synchronous, session-capable |
| `safeplane developer <message>` | POST `/connector/developer` | internal/developer-oriented entrypoint |
| `safeplane develop --repo <profile> <task>` | POST `/connector/develop` | asynchronous repo-changing flow |
| `safeplane run <entrypoint> <message>` | generic dispatcher through harness | exposed workflows only |
| `safeplane workflows` | GET `/workflows` | lists workflow registry entries |
| `safeplane runs` | GET `/runs` | list run records |
| `safeplane status <run-id>` | GET `/runs/{run_id}` plus local formatting | inspect one run |
| `safeplane approve-patch <run-id> <proposal-id>` | POST `/runs/{run_id}/patches/{proposal_id}/approve` | patch approval flow |
| `safeplane approve-pr <run-id>` | POST `/runs/{run_id}/remote/approve` | draft PR approval or retry |
| `safeplane evidence <run-id>` | local artifact collection script | filesystem-oriented, not harness HTTP |
| `safeplane case-study <run-id>` | sanitized publication artifact generation | separate from full evidence |
| `safeplane maintenance ...` | local maintenance CLI | storage and cleanup |
| `safeplane calendar ...` | local calendar admin CLI | direct Python module usage |

### Calendar admin CLI

Verified subcommands from `scripts/safeplane-calendar`:

- `create --title --start --end [--timezone] [--description] [--json]`
- `list --day <YYYY-MM-DD>` or `list --week <YYYY-MM-DD> [--timezone] [--include-cancelled] [--json]`
- `show <event_id> [--json]`
- `cancel <event_id> [--json]`
- `rebuild-index [--json]`
- `snapshot [--json]`
- `cleanup [--dry-run] [--json]`
- `reset [--dry-run] [--confirm RESET_CALENDAR] [--json]`

### Maintenance CLI

Verified families from `scripts/safeplane-maintenance` and docs:

- `storage [--json]`
- `clean [--dry-run] --older-than <duration>`
- `clean-all [--confirm DELETE]`

## Telegram Command Surface

| Command | Purpose | Auth or state rule |
| --- | --- | --- |
| `/start`, `/help` | full command reference | requires allowed Telegram user id |
| `/workflows` | list exposed workflows | only exposed registry entries |
| `/chat <message>` | run chat workflow | chat-specific session continuation |
| `/assistant <message>` | run assistant workflow | default plain-text workflow in standard config |
| `/develop <repository-profile> <task>` | run developer workflow | asynchronous; remote write depends on repo profile |
| `/run <entrypoint> <arguments>` | generic workflow dispatch | deterministic dispatch, not LLM routing |
| `/status [run-id]` | inspect latest or named run | latest defaults to chat mapping |
| `/approve_pr [run-id]` | authorize eligible draft PR publication | allowed only for remote-write-enabled `develop` runs |
| `/new` | clear chat-to-session mappings | local connector mapping reset |

Authorization uses `message.from.id` against the allowlist file, while session mapping uses `message.chat.id`. This is a deliberate contract and a likely regression point if changed.

## Harness HTTP API

This surface is internal and operator-local. In normal local mode it is published only on loopback.

| Method and path | Purpose | Request highlights | Response highlights |
| --- | --- | --- | --- |
| `GET /health` | health probe | none | `status`, `service` |
| `GET /workflows` | list workflows | optional `connector`, `exposed_only` query params | public workflow metadata array |
| `GET /workflows/{entrypoint_name}` | inspect one workflow | path `entrypoint_name` | one registry entry |
| `GET /runs` | list runs | none | run record array |
| `GET /runs/{run_id}` | inspect one run | path `run_id` | stored run record |
| `POST /runs/{run_id}/patches/{proposal_id}/approve` | approve a patch proposal | body `{ "approved": true }` | applied patch metadata |
| `POST /runs/{run_id}/remote/approve` | retry or approve remote publication | body includes `approved` and optional connector | remote write result |
| `POST /connector/{entrypoint_name}` | synchronous workflow ingress | connector id, message, optional session ref, optional repository profile | final message, run id, session ids, trace path |
| `POST /connector/{entrypoint_name}/start` | asynchronous workflow ingress | same as above | queued or running response |
| `POST /mcp/tools/call` | harness-side MCP broker call | workflow, server id, tool name, arguments, run metadata | structured tool result |

### Harness request and response conventions

- `ConnectorMessageRequest` requires `connector` in `{cli, telegram}`, `message`, and optionally `session_ref` and `repository_profile`.
- `ConnectorMessageResponse` includes `status`, `session_id`, `session_display_id`, `turn`, `run_id`, `final_message`, and `trace_path`.
- Error status codes are explicit in code: `404` unknown resources, `409` disabled workflow conflicts, `422` validation issues, `502` MCP broker failures, and `500` contract validation failures.

## Model Gateway HTTP API

| Method and path | Purpose | Contract |
| --- | --- | --- |
| `GET /health` | health and current mode | returns `status`, `service`, `mode` |
| `POST /chat` | perform one fake or real model call for a workflow stage | request includes `workflow_id`, `model_profile`, optional `stage_id`, ordered `messages`, `session_id`, `turn`, `timeout_seconds`; response includes assistant message, model metadata, usage, and finish reason |

### `POST /chat` request rules

Verified fields from `ChatRequest`:

- `workflow_id`: string
- `model_profile`: defaults to `default`
- `stage_id`: optional stage identifier
- `messages`: ordered `system`, `user`, or `assistant` role messages
- `session_id`: string
- `turn`: integer `>= 1`
- `timeout_seconds`: `1..3600`

### `POST /chat` response rules

Verified fields from `ChatResponse`:

- `status`: `completed`
- `message.role`: always `assistant`
- `model`: mode, configured model, actual model, actual provider, generation id, workflow id, model profile
- `usage`: optional provider usage block
- `finish_reason`: optional provider finish reason

## Scheduler HTTP API

| Method and path | Purpose | Contract |
| --- | --- | --- |
| `GET /health` | health probe | returns `status` |
| `POST /reload` | refresh scheduled jobs after notification changes | request includes `reason` and optional `schedule_id`; returns reload status and job counts |
| `GET /status` | current scheduler status | returns `StatusResponse` from runtime |

`notification-task-mcp` depends on `/reload` after create or cancel operations. A change here can silently affect notifications even if the notification tool contract itself stays stable.

## MCP JSON-RPC Surfaces

All current MCP services expose `POST /mcp` and expect JSON-RPC `method: tools/call`.

### Calendar MCP

| Tool | Input highlights | Output highlights |
| --- | --- | --- |
| `calendar_list` | `range_type` day or week, `date`, `timezone`, `include_cancelled` | list of calendar events |
| `calendar_create` | `title`, `start`, `end`, `timezone`, optional `description` | created event |
| `calendar_cancel` | `event_id` starting with `cal_evt_` | cancelled event |

### Notification MCP

| Tool | Input highlights | Output highlights |
| --- | --- | --- |
| `notification_schedule` | `message` or structured `payload`, required `schedule`, optional `targets`, optional `grace_seconds` | `notification_id`, status, next run time, scheduler reload info |
| `notification_list` | optional `include_cancelled` | notification records |
| `notification_cancel` | `notification_id` | cancel status and scheduler reload info |

Supported schedule types are verified in `notification_schemas.py`: `once`, `daily_time`, `weekly_time`, and `weekdays_time`. Payloads may be `static` or `calendar_digest`.

### Developer workspace MCP family

The developer tooling surface is broader and mostly internal to developer agents and the harness.

| Tool family | Verified tools |
| --- | --- |
| workspace readiness and listing | `dev_workspace_ready`, `dev_workspace_list`, `dev_workspace_find`, `dev_workspace_grep`, `dev_workspace_read` |
| Git inspection | `dev_git_metadata`, `dev_git_status`, `dev_git_diff`, `dev_git_log`, `dev_git_show`, `dev_git_tracked_files` |
| external skill inspection | `dev_external_skill_list`, `dev_external_skill_read` |
| repo mutation boundary | `dev_workspace_propose_patch`, `dev_workspace_apply_patch` |
| isolated declared checks | `dev_check_run` |

Important verified constraints:

- `run_id` and patch approval ids are format-validated.
- file paths must remain inside the workspace root.
- `dev_check_run` rejects shell operators in arguments and runs with network disabled.
- `dev_workspace_apply_patch` can require a declared per-file change budget.

## File-Based Contracts

| File contract | Owner | Why it matters |
| --- | --- | --- |
| `safeplane.yaml` | harness | entrypoints, connectors, workflow bindings, MCP registry, runtime modes |
| `workflows/*.yaml` | harness and model-gateway | supported entrypoints, model profiles, prompt ids, tool allowlists, developer stage graph |
| `config/repositories.example.yaml` | harness | target repository rules, GitHub credential profile, remote write policy |
| Compose overlays | runtime deployment layer | port exposure, secret mounts, internal networks, developer-only services |

## Authentication And Authorization

| Surface | Rule |
| --- | --- |
| harness HTTP | no app-layer auth found; safety comes from loopback or internal network placement |
| Telegram commands | Telegram `from.id` allowlist file; connector enforces before workflow dispatch |
| model-gateway real mode | OpenRouter secret mounted only into model-gateway |
| remote publication | GitHub token mounted only into harness; repo profile must explicitly enable remote write |
| MCP tools | deny-by-default, declared per workflow or agent; harness validates tool name, input, and output |

## Error And Response Conventions

| Surface | Convention |
| --- | --- |
| harness HTTP | FastAPI JSON errors via `detail`; status codes map to validation, missing resource, disabled workflow, or broker failure |
| model gateway | exceptions during chat processing become HTTP errors; successful responses always return a structured assistant message |
| MCP services | JSON-RPC response with `result` and `isError`, or explicit JSON-RPC `error` block for unsupported methods |
| notification reload bridge | schedule write may succeed even when scheduler reload fails; output carries reload warning |

## Versioning, Compatibility, And Change Notes

- Workflow contracts carry explicit `workflow_id` and `version` fields.
- Prompt contracts are versioned by filename and manifest.
- Connector command exposure is derived from the workflow registry and `safeplane.yaml`; changing either is a compatibility change for CLI or Telegram users.
- Developer workflow stages are fixed by `workflows/developer/workflow.yaml`; adding or reordering stages is a major behavioral change.
- Repository profiles are operator-owned config, but field names such as `remote_write_allowed`, `draft_pr_creation`, and `branch_prefix` are compatibility-sensitive.

## Smoke Checks

| Surface | Relevant check |
| --- | --- |
| docs and operator commands | `tests/scripts/accept-documentation` |
| local chat and assistant paths | `tests/acceptance/test_local_chat.py`, `tests/acceptance/test_assistant_workflow.py` |
| MCP foundation | `tests/acceptance/test_mcp_foundation.py` |
| Telegram commands | `tests/acceptance/test_telegram_workflow_commands.py`, `tests/scripts/accept-telegram-workflows` |
| developer tooling | `tests/unit/test_dev_workspace_mcp.py`, `tests/scripts/accept-developer-tools`, `tests/scripts/accept-developer-workspace` |
| draft PR publication | `tests/scripts/accept-draft-pr-workflow` |

## High-Risk Interface Changes

- Changing `ConnectorMessageRequest` or `ConnectorMessageResponse` breaks both CLI and Telegram paths.
- Changing workflow exposure rules or default entrypoints changes user-visible commands without touching connector code.
- Changing tool schemas in `mcp_schemas.py`, `notification_schemas.py`, or `dev_workspace_schemas.py` can break retry logic and developer safety checks.
- Changing `/reload` semantics can create notification drift that looks like scheduler bugs elsewhere.
- Changing repository profile fields can silently alter remote-write eligibility or target validation.

## Known Unknowns

- I did not enumerate every field of scheduler `StatusResponse` because the implementation detail was not required to map the main control surface.
- No public stable HTTP API intended for third-party external consumers was found; the meaningful interfaces are local operator, internal service, and controlled tool contracts.