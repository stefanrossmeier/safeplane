# ADR 0022: Developer workspaces use harness-brokered MCP boundaries

Status: Accepted

## Context

Developer agents need broad repository inspection without host shell, Docker socket, credentials, or authority to mutate the target checkout.

## Decision

Each developer run receives an isolated workspace. Agents inspect it only through harness-authorized MCP tools. The authoritative target remains read-only at rest; deterministic harness operations prepare temporary writable copies for patch validation and application.

## Consequences

Agents can use bounded list, find, grep, read, and Git metadata tools but cannot execute arbitrary shell commands or access `.git` directly. Tool permissions remain deny-by-default and agent-specific.
