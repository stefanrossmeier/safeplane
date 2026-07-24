# ADR 0006 — Model access through gateway

## Status

Accepted

## Context

Model provider access should be isolated from workflows and the harness.

## Decision

All model access goes through the model gateway container.

The chat workflow never calls OpenRouter or any other provider directly.

The harness never calls a model provider directly.

## Consequences

Provider secrets are isolated to the model gateway. Workflows remain provider-independent except for declarative model configuration in their workflow contract.

