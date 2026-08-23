# ADR 0011 — Env secrets are temporary

## Status

Accepted

## Context

MVP 0 needs a pragmatic way to provide local provider credentials for manual real-model smoke tests.

Plaintext secrets are acceptable only as a temporary local development mechanism.

## Decision

For MVP 0, `.env` is used for local secrets and runtime mode.

The `.env` file is gitignored.

Only the model gateway container receives provider secrets such as `OPENROUTER_API_KEY`.

The harness and chat workflow containers must not receive provider API keys.

## Consequences

This is simple enough for MVP 0, but not the final secret-management design. Later, `.env` should be replaced by a secret provider without changing harness or workflow code.

