# ADR 0010 — Tests use fake model access

## Status

Accepted

## Context

Acceptance tests should run frequently and must not create model cost or depend on external model availability.

## Decision

Normal tests use fake model access through the model gateway.

The fake path still exercises:

- CLI connector
- harness
- session creation
- chat workflow
- prompt loading
- model gateway API
- trace writing

Only the actual provider call is fake.

## Consequences

Tests are deterministic, cheap, and fast. Real model access is tested separately through an explicit manual smoke test.

