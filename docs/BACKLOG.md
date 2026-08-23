# Safeplane backlog

This file is the current backlog for deferred improvements. Implemented runtime
behavior belongs in current architecture and operations documentation instead.

## Connector and API follow-up

- Introduce versioned `/v1/connector`, `/v1/control`, and `/v1/internal` API
  namespaces without duplicating harness business logic.
- Authenticate connector and operator principals outside request-body identity
  fields and enforce explicit capabilities in the harness.
- Migrate Telegram's private harness HTTP implementation to
  `connectors/common` after the versioned/authenticated contract is stable.
- Remove legacy pre-versioned route aliases and the `scripts/safeplane-chat`
  compatibility alias after all deployments and external callers have migrated.
- Move normal local harness host exposure to an explicit diagnostic overlay once
  direct-host acceptance and troubleshooting paths no longer depend on it.

## Operational follow-up

- Continue clean-host deployment and recovery drills.
- Strengthen backup/restore evidence and documented rollback exercises.
- Continue private soak evidence for restart, persistence, resource use, storage
  growth, and cleanup behavior.
- Complete the public-release audit and clean-room validation before changing
  repository visibility.

## Product candidates

Candidates such as bounded developer rework, deterministic routing advice,
persistent notes, a web operator interface, additional connectors, external
calendar synchronization, broader GitHub integration, end-to-end cancellation,
browser automation, multi-user operation, and orchestration scaling require a
separate evidence-based design before promotion.

See [Future improvements](future-improvements.md) for the broader selection
principles and guardrails that remain applicable.
