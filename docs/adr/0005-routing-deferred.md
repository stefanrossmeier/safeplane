# ADR 0005 — Routing deferred

## Status

Superseded by [ADR 0031](0031-advisory-natural-language-routing.md)

## Context

Routing only becomes useful when more than one workflow exists.

MVP 0 has exactly one workflow: `chat`.

## Decision

Do not implement routing in MVP 0.

Instead, use a static entrypoint binding:

    safeplane chat "<message>" -> chat workflow

## Consequences

This avoided fake architecture while Safeplane had only one workflow. The later workflow registry established deterministic resolution, and ADR 0031 now adds advisory natural-language routing without changing the authority boundary: explicit dispatch remains deterministic and model access remains behind the model gateway.

