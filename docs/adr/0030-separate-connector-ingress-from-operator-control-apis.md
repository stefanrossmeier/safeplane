# ADR 0030: Separate connector ingress from operator control APIs

Status: Proposed

## Context

The current harness exposes workflow ingress and operator-control operations
under pre-versioned paths. The explicit CLI already separates these concerns in
its shared client, but the HTTP namespace and authorization model do not yet
express that distinction.

## Proposed decision

A later migration should introduce distinct versioned namespaces for connector
ingress, operator control, and internal service operations. Route handlers should
share the same application services rather than duplicate workflow or policy
logic.

That migration should be paired with authenticated connector/operator principals
and capability checks. It should not be mixed into the shell-to-container CLI
replacement because doing so would change transport, API, identity, and runtime
topology simultaneously.

## Consequences

This ADR records direction only. The current deployment continues to use the
existing routes documented in `docs/API_SURFACE.md` until the versioned API and
authentication migration is implemented and accepted.
