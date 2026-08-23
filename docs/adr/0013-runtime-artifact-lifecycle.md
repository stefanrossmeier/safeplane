# ADR 0013: Runtime artifact lifecycle

Status: accepted

## Context

Safeplane writes sessions, traces, raw model responses, message artifacts, and output artifacts under `SAFEPLANE_HOME`.

Future workflows will add run records, MCP tool outputs, workspaces, checkouts, patches, command logs, calendar data, notes, and backups.

Without explicit lifecycle rules, runtime data will become hard to inspect and risky to clean manually.

## Decision

Safeplane classifies runtime data into:

- disposable/debug artifacts
- runtime state
- protected durable data
- maintenance state

MVP 2 introduces local maintenance commands:

    ./scripts/safeplane maintenance storage
    ./scripts/safeplane maintenance clean --dry-run --older-than 30d
    ./scripts/safeplane maintenance clean --older-than 30d
    ./scripts/safeplane maintenance clean-all

Safe cleanup deletes old trace directories only.

Sessions are not deleted by safe cleanup in MVP 2.

Protected durable directories are never deleted by cleanup:

    secrets
    data
    backups
    config

`clean-all` is available as an explicit destructive local reset command.

It deletes runtime state and disposable artifacts, but still keeps protected durable directories.

`clean-all` requires typed confirmation or `--confirm DELETE`.

Cleanup writes an audit JSONL file under:

    ~/.safeplane/maintenance/cleanup.audit.jsonl

## Consequences

Positive:

- Runtime storage can be inspected.
- Old traces can be removed safely.
- Dry-run cleanup exists before destructive cleanup.
- Secrets and durable user data are protected by default.
- The lifecycle model is ready for future runs, MCP artifacts, calendar data, and developer workspaces.

Tradeoffs:

- MVP 2 does not implement automatic scheduled cleanup.
- MVP 2 does not delete sessions through safe cleanup.
- `clean-all` is intentionally destructive for runtime state and must be used carefully.

## Rejected alternatives

### Delete sessions together with old traces

Rejected for MVP 2 because session continuation comes next and session lifecycle rules are not mature yet.

### Allow arbitrary cleanup paths

Rejected because cleanup should operate only on known Safeplane runtime directories.

### Delete secrets during clean-all

Rejected because secrets are configuration material, not disposable runtime artifacts.
