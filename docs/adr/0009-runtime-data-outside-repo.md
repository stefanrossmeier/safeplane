# ADR 0009 — Runtime data outside repo

## Status

Accepted

## Context

Dynamic runtime data such as sessions, traces, artifacts, and outputs should not pollute the harness repository.

## Decision

Runtime data is written under `SAFEPLANE_HOME`.

Default:

    ~/.safeplane

Expected structure:

    ~/.safeplane/
      sessions/
      traces/

## Consequences

The repository remains clean. Tests should use a temporary `SAFEPLANE_HOME` to avoid writing into the developer's normal runtime directory.

