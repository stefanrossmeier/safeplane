# ADR 0003 — Harness owns session lifecycle

## Status

Accepted

## Context

Session lifecycle must be consistent across connectors and workflows.

## Decision

The harness owns session creation and session persistence.

For phase 0, every incoming connector message creates a new session.

Session continuation is explicitly out of scope for phase 0.

## Consequences

The CLI connector remains simple. Session behavior can later be extended in the harness without changing connector responsibilities.

