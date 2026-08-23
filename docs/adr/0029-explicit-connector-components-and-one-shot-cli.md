# ADR 0029: Explicit connector components and one-shot CLI

Status: Accepted

## Context

Telegram is an explicit connector package and container, while the CLI used to
implement command parsing, payload construction, HTTP transport, rendering, and
control calls in a host shell script. That made the architecture description and
runtime topology inconsistent even though the harness remained authoritative.

## Decision

The CLI is an explicit Python connector component. Networked CLI commands run in
a short-lived Compose container attached only to `connector-harness`.
`scripts/safeplane` is a launcher/dispatcher and owns no harness endpoint,
payload, or response logic.

A shared Python connector client separates connector ingress calls from
operator-control calls in code. The migration preserves existing harness paths
before any API/authentication contract change.

The harness remains the sole authority for workflows, state, policy,
credentials, validation, repository/Git operations, approvals, evidence, and
remote-write enforcement.

No connector router, message bus, persistent CLI daemon, direct model access, or
direct MCP access is introduced.

## Consequences

CLI and Telegram are explicit runtime components with comparable connector
boundaries. The CLI no longer requires host Python or curl for harness calls.
The one-shot container has no runtime-state mounts, secrets, target repository,
Docker socket, model network, or MCP network.

Local-only operator utilities remain host-dispatched until corresponding control
APIs exist.
