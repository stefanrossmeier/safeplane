# ADR 0017: Add deterministic workflow registry before routing

## Status

Accepted

## Context

After phase 4, Safeplane had more than one workflow.

The system needed a structured way to list and resolve workflows without introducing probabilistic routing too early.

Routing is still intentionally deferred.

## Decision

Phase 5 adds a deterministic workflow registry owned by the harness.

Resolution flow:

    entrypoint -> workflow registry -> workflow endpoint

The registry is built from:

- safeplane.yaml
- workflows/<workflow>/workflow.yaml

The registry validates workflow contracts before resolving workflows.

Workflow contracts include:

- workflow id
- version
- description
- supported entrypoints
- prompt reference
- model profile
- session behavior
- concurrency placeholder
- MCP policy
- tool/function policy
- input/output shape

The CLI supports listing workflows:

    safeplane workflows

The CLI also supports explicit generic execution:

    safeplane run <entrypoint> "message"

There is no LLM router, fuzzy matching, or advisor in phase 5.

## Consequences

Workflow discovery is explicit and inspectable.

Unknown entrypoints fail clearly.

Disabled workflows can be represented in configuration.

Future routing or advisor workflows can build on a validated registry instead of hardcoded workflow knowledge.
