# ADR 0023: The developer workflow is fixed and single-pass

Status: Accepted

## Context

An autonomous review/rework loop would make authority, cost, and failure behavior harder to inspect.

## Decision

The harness owns a fixed stage sequence from repository preparation through documentation, planning, implementation, checks, review, and PR text. `REQUEST_CHANGES`, failed checks, or invalid stage output stop the run. There is no automatic post-application rework loop.

## Consequences

Candidate validation may return deterministic feedback before application, but once a patch is applied, later failure stops the run. A new operator-started run is required for rework.
