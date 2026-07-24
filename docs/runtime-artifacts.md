# Runtime artifacts and cleanup

Safeplane stores runtime state under `SAFEPLANE_HOME` and credentials under the
separate `SAFEPLANE_SECRET_ROOT`.

Defaults:

```text
SAFEPLANE_HOME=$HOME/.safeplane
SAFEPLANE_SECRET_ROOT=$HOME/.config/safeplane/secrets
```

The maintenance command never creates or manages the external secret root.

## Runtime directory classes

| Class | Directories | Cleanup behavior |
| --- | --- | --- |
| run and session state | `sessions`, `runs` | preserved by normal cleanup |
| inspectable and disposable | `traces`, `artifacts`, inactive `workspaces`, `checkouts` | age-based cleanup |
| durable application data | `data` | protected |
| operator configuration | `config` | protected |
| backup area | `backups` | protected; not a complete backup package |
| logs and connector state | `logs`, `connectors` | capability-specific runtime mounts |
| maintenance audit | `maintenance` | recreated after `clean-all` |

A pre-existing `${SAFEPLANE_HOME}/secrets` directory is legacy data. It is not
mounted into services, is not recreated by maintenance, and is preserved so the
operator can migrate and remove it deliberately.

## Storage inspection

```bash
./scripts/safeplane maintenance storage
./scripts/safeplane maintenance storage --json
```

The report covers runtime directories. Use `make secrets-list` to inspect
configured secret names and paths without printing values.

## Safe cleanup

```bash
./scripts/safeplane maintenance clean --dry-run --older-than 30d
./scripts/safeplane maintenance clean --older-than 30d
```

Cleanup removes old inactive trace directories and completed run workspaces.
It preserves run and session records. Workspaces for active runs or runs still
waiting for, or eligible for, remote publication remain protected.

## Destructive runtime reset

```bash
./scripts/safeplane maintenance clean-all
```

The command requires typing `DELETE`. Non-interactive use requires:

```bash
./scripts/safeplane maintenance clean-all --confirm DELETE
```

It removes:

```text
sessions
runs
traces
artifacts
workspaces
checkouts
maintenance
```

It preserves:

```text
data
backups
config
```

It does not touch `SAFEPLANE_SECRET_ROOT`. Existing legacy
`${SAFEPLANE_HOME}/secrets` files are also preserved but are no longer part of
the supported runtime layout.

## Audit log

Cleanup writes JSON Lines records to:

```text
${SAFEPLANE_HOME}/maintenance/cleanup.audit.jsonl
```

Records include the command, timestamp, dry-run state, candidates, deletions,
skips, and errors.

## Evidence bundles

```bash
./scripts/safeplane evidence <run-id>
./scripts/safeplane evidence latest
```

The collector copies the run record and available pipeline, approval, evidence,
and trace directories into:

```text
${SAFEPLANE_HOME}/evidence-bundles/<run-id>
```

It writes a manifest with file hashes. This is complete local evidence and may
contain operational detail. `safeplane case-study` produces a separate,
deliberately sanitized publication artifact from eligible runs.

## Backup limitation

The protected `backups` directory is an interface boundary, not proof of a full
runtime backup and restore implementation. Calendar reset creates a local
calendar backup. A complete runtime manifest, restore procedure, update and
rollback workflow, and recovery drill remain operational hardening work.
