# Safeplane local secrets

Status: enforced file-secret boundary

Safeplane credentials are stored outside the runtime root.

Default secret directory:

```text
~/.config/safeplane/secrets
```

Override the directory with `SAFEPLANE_SECRET_ROOT`, or use the supported
per-secret file variables:

- `SAFEPLANE_OPENROUTER_API_KEY_FILE`
- `SAFEPLANE_GITHUB_TOKEN_FILE`
- `SAFEPLANE_TELEGRAM_BOT_TOKEN_FILE`
- `SAFEPLANE_TELEGRAM_ALLOWED_USER_IDS_FILE`

`SAFEPLANE_SECRET_ROOT` must not be located beneath `SAFEPLANE_HOME`. No service
mounts the runtime root as a whole, and credentials are attached only as named
Docker secrets.

The secret directory must be private to the local user. Files use mode `0644`
inside that mode-`0700` directory so the fixed non-root container UID can read
only the file explicitly mounted as a Docker secret:

```bash
chmod 700 "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}"
chmod 644 "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}"/*
```

## Implemented secrets

| Secret name | Default local file | Mounted into | Container path |
| --- | --- | --- | --- |
| `openrouter_api_key` | `~/.config/safeplane/secrets/openrouter_api_key` | model-gateway only | `/run/secrets/openrouter_api_key` |
| `github_token` | `~/.config/safeplane/secrets/github_token` | harness only | `/run/secrets/github_token` |
| `telegram_bot_token` | `~/.config/safeplane/secrets/telegram_bot_token` | telegram-connector only | `/run/secrets/telegram_bot_token` |
| `telegram_allowed_user_ids` | `~/.config/safeplane/secrets/telegram_allowed_user_ids` | telegram-connector only | `/run/secrets/telegram_allowed_user_ids` |

## Prepare the split layout

```bash
./scripts/prepare-runtime-layout
```

If legacy files remain under `~/.safeplane/secrets`, the helper reports them.
Recreate or move each credential into the external secret root, verify the new
file, and then remove the legacy copy.

## Set and list secrets

```bash
make secret-set-openrouter
make secret-set-github
make secret-set-telegram
make secret-set-telegram-users
make secrets-list
```

The helper prompts without echoing the value and applies restrictive host
permissions. Listing prints names and paths only, never values.

## Secret boundary rules

- OpenRouter belongs only to model-gateway.
- GitHub belongs only to harness.
- Telegram credentials belong only to telegram-connector.
- MCP, scheduler, check, and GitHub-mock services receive no secret.
- No secret is passed as an environment variable or build argument.
- Fake mode requires no secret.
- Logs, traces, errors, evidence, Git configuration, and rendered Compose output
  must not contain secret values.

The complete mount and network matrices are documented in
[`runtime-boundaries.md`](runtime-boundaries.md).
