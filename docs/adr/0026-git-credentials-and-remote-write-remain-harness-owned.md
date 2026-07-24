# ADR 0026: Git credentials and remote write remain harness-owned

Status: Accepted

## Context

Agents can prepare code and PR text but must not receive repository credentials or issue remote GitHub operations.

## Decision

Only the harness receives the repository-scoped credential. It creates a deterministic branch and commit, pushes without force, and creates or reuses one draft pull request. Agents and MCP services never receive the secret.

## Consequences

Credential material stays out of prompts, traces, artifacts, Git configuration, and target workspaces. Remote operations are idempotent and Safeplane never merges.
