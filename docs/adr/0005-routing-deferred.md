# ADR 0005 — Routing deferred

## Status

Accepted

## Context

Routing only becomes useful when more than one workflow exists.

Phase 0 has exactly one workflow: `chat`.

## Decision

Do not implement routing in phase 0.

Instead, use a static entrypoint binding:

    safeplane chat "<message>" -> chat workflow

## Consequences

This avoids fake architecture. Deterministic routing can be added when there is more than one workflow. Any future LLM-based routing advisor must run outside the deterministic harness core and use the model gateway for model access.

