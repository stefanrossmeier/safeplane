# ADR 0019: Telegram connector is isolated from the harness

> Superseded in part by ADR 0028 for host secret paths, mounts, and network boundaries.
## Status

Accepted

## Context

MVP 7 introduces Telegram as the first external connector.

Telegram long polling can hold an HTTP request open for many seconds.

The connector may hang, restart, or fail independently from the rest of the system.

Safeplane already established that connectors should stay dumb and that the harness owns sessions, runs, orchestration, and workflow selection.

## Decision

The Telegram connector runs as a separate Docker service.

It is optional and not part of the default `make up` stack.

The Telegram connector talks only to the harness HTTP API.

It does not call workflows directly.

It does not call the model gateway.

It does not own sessions or runs.

Plain Telegram text messages are sent to the assistant entrypoint.

The Telegram chat id maps to one Safeplane assistant session.

The connector stores its local mapping under:

    SAFEPLANE_HOME/connectors/telegram/sessions.json

The bot token is stored as a Docker secret:

    SAFEPLANE_HOME/secrets/telegram_bot_token

Only the telegram-connector service receives this secret.

Allowed Telegram user ids are required.

The allowlist uses Telegram message.from.id, not only message.chat.id.

The allowed user ids are stored as a Docker secret:

    SAFEPLANE_HOME/secrets/telegram_allowed_user_ids

If no user ids are configured, all Telegram users are rejected.

MVP 7 uses long polling.

Webhook mode is deferred.

## Consequences

Telegram polling cannot block or crash the harness.

Users can restart the Telegram connector independently.

The connector remains replaceable.

Safeplane keeps a clean boundary:

    connector -> harness -> workflow -> model gateway

Future connectors can follow the same pattern.

Future outbound notifications can reuse Telegram later, but MVP 7 only replies to inbound messages.
