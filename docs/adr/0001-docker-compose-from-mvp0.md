# ADR 0001 — Docker Compose from MVP 0

## Status

Accepted

## Context

Safeplane MVP 0 should already run as a docked local system. The harness, chat workflow, and model gateway are separate runtime components and should be exercised through Docker Compose from the beginning.

## Decision

Use Docker Compose in MVP 0.

The local runtime contains:

- harness container
- chat workflow container
- model gateway container

Only the harness exposes a host-facing port. The workflow and model gateway remain internal to the Docker network.

## Consequences

This adds setup complexity early, but keeps MVP 0 close to the intended architecture.

