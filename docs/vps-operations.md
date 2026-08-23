# VPS operations

The supported first-release deployment target is Ubuntu Server 24.04 LTS on
amd64 with Docker Engine, the Docker Compose plugin, one trusted non-root
operator, Telegram long polling, and no published Safeplane application port.

## Host paths

```text
/var/code/safeplane       private Git checkout
/var/lib/safeplane        mutable runtime state
/etc/safeplane            operator configuration
/etc/safeplane/secrets    file secrets
/var/backups/safeplane    backup archives and manifests
/var/log/safeplane        deployment and validation logs
```

Copy `config/operator.env.example` to `/etc/safeplane/operator.env`, adjust the
operator name, then load it before every operator command:

```bash
set -a
. /etc/safeplane/operator.env
set +a
```

Prepare strict UID-aligned, operator-group-accessible setgid directories once:

```bash
sudo -E ./scripts/prepare-vps-layout
```

## Secrets

Set values interactively. Input is hidden and values are written with mode
`0600`; values are never command-line arguments.

```bash
./scripts/safeplane-vps secrets set openrouter_api_key
./scripts/safeplane-vps secrets set telegram_bot_token
./scripts/safeplane-vps secrets set telegram_allowed_user_ids
./scripts/safeplane-vps secrets set github_token
./scripts/safeplane-vps secrets list
```

The assistant profile requires the first three secrets. Set
`SAFEPLANE_VPS_PROFILE=developer` to add the developer MCP services and mount the
GitHub token only into the harness.

## Normal operation

```bash
./scripts/safeplane-vps preflight
./scripts/safeplane-vps config
./scripts/safeplane-vps start
./scripts/safeplane-vps status
./scripts/safeplane-vps logs --tail 200
./scripts/safeplane-vps restart
./scripts/safeplane-vps stop
```

`stop` preserves bind-mounted state. The production overlay applies bounded
`json-file` rotation to every long-running service. The operator status command
reports the exact Git revision, health, restart policy, and any published port.

## Backup and restore

Backups include sessions, runs, traces, calendar and notification data,
connector state, configuration, logs, deployment metadata, and evidence-bearing
runtime records. They exclude secrets, workspaces, Git fixtures, mocks, and
caches. Every archive has a JSON manifest and SHA-256 file.

```bash
./scripts/safeplane-vps backup
./scripts/safeplane-vps restore \
  --archive /var/backups/safeplane/safeplane-YYYYMMDDTHHMMSSZ-REV.tar.gz \
  --confirm RESTORE
sudo -E ./scripts/prepare-vps-layout
./scripts/safeplane-vps start
```

Restore stops the stack, verifies the archive hash and member paths, preserves
the old runtime beside the restored one, and never restores secrets.

## Update and rollback

The checkout must be clean. Update records the previous revision before a
fast-forward pull and healthy restart:

```bash
./scripts/safeplane-vps update --branch mvp-27
```

Rollback resets to the recorded previous commit and requires an explicit guard:

```bash
./scripts/safeplane-vps rollback --confirm ROLLBACK
```

A specific known commit may be selected with `--revision`. Runtime and secrets
remain outside the checkout and are not overwritten by either operation.

## Cleanup

```bash
./scripts/safeplane-vps cleanup --dry-run --older-than 30d
./scripts/safeplane-vps cleanup --older-than 30d
```

Cleanup uses the existing harness-owned maintenance policy, which preserves
active and approval-relevant runs.
