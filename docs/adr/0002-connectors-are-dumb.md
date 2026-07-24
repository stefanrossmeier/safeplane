# ADR 0002 — Connectors are dumb

## Status

Accepted

## Context

Safeplane will eventually support multiple operator interfaces, starting with a CLI connector and later possibly Telegram or web connectors.

Connectors should not own product behavior.

## Decision

Connectors only translate operator input into harness input.

The CLI command:

    safeplane chat "<message>"

does not:

- create sessions
- resume sessions
- route
- call workflows directly
- call models directly
- write business state

It only sends a connector message to the harness and prints the result.

## Consequences

All stateful behavior remains in the harness. Future connectors can be added without duplicating orchestration logic.

