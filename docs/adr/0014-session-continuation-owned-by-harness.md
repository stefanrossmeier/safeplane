# ADR 0014: Session continuation is owned by the harness

## Status

Accepted

## Context

Phase 3 added continuation of existing chat sessions.

A user can start a session and later continue it by passing either the short display id or the full sess_<uuid> id.

The system needed a clear owner for:

- resolving session references
- detecting unknown or ambiguous session ids
- incrementing turn numbers
- loading prior turns
- assembling history
- persisting session state
- writing trace paths

## Decision

The harness owns session continuation.

Connectors remain dumb and only pass:

- connector name
- message
- optional session reference

Workflows do not resolve sessions and do not decide turn numbers.

The harness loads prior turns from SAFEPLANE_HOME/sessions, assembles the prior user/assistant messages, appends the new user message, and calls the selected workflow.

Sessions are stored as one JSON file per session:

    SAFEPLANE_HOME/sessions/<session_id>.json

Turn traces are stored under:

    SAFEPLANE_HOME/traces/<session_id>/turn_<nnn>

## Consequences

Session continuation is deterministic and testable.

The CLI can remain simple.

Workflows receive a prepared message history and can focus on prompt handling and model calls.

Future workflows can share the same continuation mechanism without duplicating session logic.
