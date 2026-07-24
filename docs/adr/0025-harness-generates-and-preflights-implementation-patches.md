# ADR 0025: The harness generates and preflights implementation patches

Status: Accepted

## Context

Model-authored Git patches were malformed or based on guessed context. Accepting them directly weakened determinism.

## Decision

The implementation agent returns exact replacements copied from MCP evidence. Safeplane matches `old_text` exactly once, constructs the Git diff deterministically, validates planned paths and budgets, applies the candidate only in an isolated check copy, and accepts it only when declared checks pass.

## Consequences

Valid tool calls do not consume validation retries. Failed candidates never mutate the authoritative workspace. There is still no post-application rework loop.
