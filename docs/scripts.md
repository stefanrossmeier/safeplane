# Safeplane operations

This guide is the current operator entry point. Commands are shown from the
repository root and are derived from the executable scripts and Compose files in
this repository.

## Install and prepare local state

Requirements:

- Docker Engine and Docker Compose plugin
- Python 3.11+
- `make`, `git`, and `curl`

Install local test dependencies and prepare the split runtime layout:

```bash
python3 -m pip install -r requirements-dev.txt
make setup
```

Defaults:

```text
SAFEPLANE_HOME=$HOME/.safeplane
SAFEPLANE_SECRET_ROOT=$HOME/.config/safeplane/secrets
```

Inspect or recreate the required directories without starting containers:

```bash
./scripts/prepare-runtime-layout
```

The secret root must remain outside the runtime root.

## Fake local mode

```bash
make up
./scripts/safeplane chat "Reply with a short confirmation."
./scripts/safeplane assistant "List my calendar entries for today."
./scripts/safeplane workflows
make down
```

Equivalent Compose wrapper:

```bash
tests/scripts/compose-safeplane-fake up -d --build
tests/scripts/compose-safeplane-fake down
```

Fake mode uses the fake model gateway and requires no provider secret. The local
overlay publishes the harness only on `127.0.0.1:8787`.

## Real-provider local mode

Provision the OpenRouter file secret, then start the guarded real model path:

```bash
make secret-set-openrouter
make smoke-real MESSAGE="Reply with a short confirmation."
```

Direct wrapper:

```bash
tests/scripts/compose-safeplane-real up -d --build
```

Only `model-gateway` receives `/run/secrets/openrouter_api_key`.

## Secret provisioning

```bash
make secret-set-openrouter
make secret-set-github
make secret-set-telegram
make secret-set-telegram-users
make secrets-list
```

Per-secret path overrides are supported through:

```text
SAFEPLANE_OPENROUTER_API_KEY_FILE
SAFEPLANE_GITHUB_TOKEN_FILE
SAFEPLANE_TELEGRAM_BOT_TOKEN_FILE
SAFEPLANE_TELEGRAM_ALLOWED_USER_IDS_FILE
```

See [Local secrets](security/secrets.md).

## Telegram fake and real modes

Telegram always uses the real Telegram transport, even when model responses are
fake. It uses long polling and publishes no application port.

```bash
make secret-set-telegram
make secret-set-telegram-users

tests/scripts/compose-safeplane-telegram-fake up -d --build
tests/scripts/compose-safeplane-telegram-fake down
```

Real OpenRouter plus Telegram:

```bash
tests/scripts/compose-safeplane-telegram-real up -d --build
tests/scripts/compose-safeplane-telegram-real down
```

Deterministic Telegram commands:

```text
/help
/workflows
/chat <message>
/assistant <message>
/develop <repository-profile> <task>
/run <entrypoint> <arguments>
/status [run-id]
/approve_pr [run-id]
/new
```

Plain text maps to the registry-configured default workflow. `/run` selects an
explicit registry entrypoint; it is not an LLM router. See
[Telegram connector](connectors/telegram.md).

## CLI workflows and sessions

```bash
./scripts/safeplane workflows
./scripts/safeplane chat "message"
./scripts/safeplane chat --session <session-id> "follow-up"
./scripts/safeplane assistant "message"
./scripts/safeplane assistant --session <session-id> "follow-up"
./scripts/safeplane runs
./scripts/safeplane status <run-id>
```

`chat` and `assistant` use separate workflow sessions. `assistant` may call its
allowed calendar and notification MCP tools; `chat` has no MCP tools.

## Developer runs and repository profiles

Prepare operator-owned repository configuration outside Git:

```bash
mkdir -p "${SAFEPLANE_HOME:-$HOME/.safeplane}/config"
cp config/repositories.example.yaml \
  "${SAFEPLANE_HOME:-$HOME/.safeplane}/config/repositories.yaml"
```

Edit the copied profile, enable it, and set the exact allowed repository,
credential policy, remote-write policy, branch prefix, and draft-PR mode.

Start the developer stack in fake mode:

```bash
tests/scripts/compose-safeplane-developer-fake up -d --build
./scripts/safeplane develop --repo <profile> "Implement one bounded change"
```

Real provider mode:

```bash
tests/scripts/compose-safeplane-developer-real up -d --build
```

A complete neutral local-Git proof is available as:

```bash
tests/scripts/accept-developer-workflow
```

Repository profiles use `draft_pr_creation: approval_required` by default.
Profiles may explicitly use `automatic`; both paths remain harness-owned and
require passing checks, `LGTM`, and `ALIGNED`.

## Draft-PR publication

Provision GitHub credentials only for a real publication path:

```bash
make secret-set-github
```

Manual approval or retry for an eligible run:

```bash
./scripts/safeplane approve-pr <run-id>
```

The harness revalidates immutable repository, workspace, patch, check, review,
and plan-alignment bindings before a non-force push. Approval and draft-PR
creation are idempotent. Safeplane never merges. See [Remote write](remote-write.md).

## Status and evidence

```bash
./scripts/safeplane runs
./scripts/safeplane status <run-id>
./scripts/safeplane evidence <run-id>
./scripts/safeplane evidence latest
```

Generate a deliberately sanitized case study only from an eligible completed
run:

```bash
./scripts/safeplane case-study <run-id> --help
```

Complete local evidence and sanitized publication evidence are different
artifacts. See [Runtime artifacts](runtime-artifacts.md).

## Calendar and notifications

Direct calendar administration:

```bash
./scripts/safeplane calendar create \
  --title "Planning block" \
  --start "2026-07-22T09:00:00+02:00" \
  --end "2026-07-22T10:00:00+02:00"
./scripts/safeplane calendar list --day "2026-07-22"
./scripts/safeplane calendar list --week "2026-07-20"
./scripts/safeplane calendar snapshot
```

The assistant can create, list, and cancel calendar entries and can schedule,
list, and cancel notifications through harness-brokered MCP tools. In the base
stack the scheduler records log delivery. With the Telegram overlay it routes
outbound notifications through `telegram-connector`, which alone owns Telegram
credentials.

Inspect notification state:

```bash
tests/scripts/inspect-notifications
```

See [Calendar](calendar.md) and [Telegram notification delivery](connectors/telegram.md#outbound-notification-delivery).

## Cleanup

Inspect storage:

```bash
./scripts/safeplane maintenance storage
./scripts/safeplane maintenance storage --json
```

Preview and remove old inactive traces and workspaces:

```bash
./scripts/safeplane maintenance clean --dry-run --older-than 30d
./scripts/safeplane maintenance clean --older-than 30d
```

Destructive runtime reset:

```bash
./scripts/safeplane maintenance clean-all
```

`clean-all` requires typing `DELETE` or `--confirm DELETE`. It preserves
`data`, `backups`, and `config`, and it does not create, move, or delete the
external secret root. Old workspaces that are active or still eligible for
remote approval remain protected.

## Backup and restore interface

There is no complete runtime backup-and-restore package yet. That is part of the
remaining operational hardening work and must not be inferred from the presence of a
`backups` directory.

Current safety interfaces are limited to:

```bash
./scripts/safeplane calendar snapshot
./scripts/safeplane calendar reset --dry-run
./scripts/safeplane calendar reset --confirm RESET
```

Calendar reset creates a backup of the current event log and index before
resetting. A full runtime backup manifest, restore procedure, update path, and
rollback drill are not implemented or proven.

## Runtime inspection

```bash
tests/scripts/status-safeplane-mode
```

The command reports the Compose file combination, fake or real model mode,
workflow model configuration, secret mount presence without values, published
harness port, service state, and health.

## Validation

Focused secret-free checks:

```bash
tests/scripts/test-unit -q
tests/scripts/accept-repository-cleanup
tests/scripts/check-repository-hygiene
tests/scripts/accept-telegram-workflows
```

Capability acceptances:

```bash
tests/scripts/accept-runtime-hardening
tests/scripts/accept-notification-stack
tests/scripts/accept-developer-workspace
tests/scripts/accept-patch-approval
tests/scripts/accept-developer-contract
tests/scripts/accept-repository-workspaces
tests/scripts/accept-developer-tools
tests/scripts/accept-external-documentation
tests/scripts/accept-developer-workflow
tests/scripts/accept-publication-path
```

Real provider, Telegram, external-repository, and GitHub scripts are guarded
manual validations. Do not run them merely as part of normal local validation.

## Troubleshooting

1. Run `./scripts/prepare-runtime-layout` and correct any warning about legacy
   secrets below `SAFEPLANE_HOME`.
2. Run `tests/scripts/status-safeplane-mode` to detect mixed Compose overlays,
   missing mounts, stopped services, and failed health checks.
3. Recreate the intended mode with its exact wrapper and `up -d --build
   --force-recreate`.
4. Inspect `docker compose ... ps` and the relevant wrapper's `logs` output.
5. Confirm secret files are non-empty with `make secrets-list`; never print a
   token into diagnostics.
6. Inspect `./scripts/safeplane status <run-id>` before collecting an evidence
   bundle.
