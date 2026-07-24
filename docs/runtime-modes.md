# Runtime modes

Safeplane mode selection is explicit in the Compose wrapper. Fake mode is the
default for development and automated acceptance; every real external path is a
guarded operator action.

| Mode | Wrapper | Model | External systems | Host port |
| --- | --- | --- | --- | --- |
| fake local | `tests/scripts/compose-safeplane-fake` | fake | none | harness on loopback |
| real provider local | `tests/scripts/compose-safeplane-real` | OpenRouter | OpenRouter | harness on loopback |
| Telegram fake | `tests/scripts/compose-safeplane-telegram-fake` | fake | Telegram | none |
| Telegram real | `tests/scripts/compose-safeplane-telegram-real` | OpenRouter | OpenRouter and Telegram | none |
| developer fake | `tests/scripts/compose-safeplane-developer-fake` | fake | local or configured Git sources | harness on loopback |
| developer real | `tests/scripts/compose-safeplane-developer-real` | OpenRouter | OpenRouter and configured Git sources | harness on loopback |
| developer GitHub fake | `tests/scripts/compose-safeplane-developer-github-fake` | fake | GitHub | harness on loopback |
| developer GitHub real | `tests/scripts/compose-safeplane-developer-github-real` | OpenRouter | OpenRouter and GitHub | harness on loopback |

## Fake local

```bash
tests/scripts/compose-safeplane-fake up -d --build
tests/scripts/compose-safeplane-fake down
```

No provider secret is required.

## Real provider local

```bash
make secret-set-openrouter
tests/scripts/compose-safeplane-real up -d --build
```

Only `model-gateway` receives the OpenRouter secret.

## Telegram

```bash
make secret-set-telegram
make secret-set-telegram-users
tests/scripts/compose-safeplane-telegram-fake up -d --build
```

Replace the wrapper with `compose-safeplane-telegram-real` to add the real
provider overlay. Telegram always uses the real Telegram API and long polling;
"fake" refers only to model responses.

## Developer

```bash
SAFEPLANE_DEV_SOURCE=/absolute/path/to/repository \
  tests/scripts/compose-safeplane-developer-fake up -d --build
```

The developer overlay adds the read-only workspace MCP service, controlled apply
service, and networkless check service. Repository-profile runs prepare their
own isolated Git workspaces; `SAFEPLANE_DEV_SOURCE` is used by direct workspace
inspection and fixture validation.

Use `compose-safeplane-developer-real` for a real provider and the dedicated
GitHub wrappers only when GitHub publication is deliberately enabled.

## Inspect the active combination

```bash
tests/scripts/status-safeplane-mode
```

The status command reports the Compose project and recorded overlays, detects
mixed service combinations, shows fake or real model mode, lists workflow model
configuration, reports secret mount presence without values, shows connector
configuration and host publication, and checks service state and health.

After changing modes, recreate the intended services with the exact wrapper:

```bash
tests/scripts/compose-safeplane-fake up -d --build --force-recreate
```

Substitute the wrapper for the selected mode.

## Guarded real validations

Real validations are excluded from normal secret-free acceptance. Examples:

```bash
SAFEPLANE_CONFIRM_REAL_TELEGRAM_SMOKE=yes \
  tests/scripts/validate-real-assistant-telegram-reminder

SAFEPLANE_CONFIRM_REAL_EXTERNAL_REPOSITORY=yes \
  tests/scripts/validate-real-external-repository

SAFEPLANE_CONFIRM_REAL_GITHUB_DRAFT_PR=yes \
  tests/scripts/validate-real-draft-pr
```

Each script has additional required configuration and repository safety checks.
Read the script and the corresponding operations document before setting a
guard variable.

See [Operations](scripts.md), [Telegram](connectors/telegram.md), and
[External repository acceptance](external-repository-acceptance.md).
