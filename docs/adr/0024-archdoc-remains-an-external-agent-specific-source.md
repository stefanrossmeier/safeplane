# ADR 0024: `archdoc` remains external and documentation-agent-only

Status: Accepted

## Context

The architecture documentation skill evolves in `ai-craftkit` and must not be copied or interpreted independently by every agent.

## Decision

Safeplane prepares the external repository, records one exact commit per run, and grants only the documentation agent read access to `skills/archdoc`. Later agents consume the generated target-repository documentation.

## Consequences

Runs remain reproducible, the skill can evolve independently, and persisted model artifacts redact live skill content.
