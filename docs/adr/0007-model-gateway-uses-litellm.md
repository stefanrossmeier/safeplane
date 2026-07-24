# ADR 0007 — Model gateway uses LiteLLM

## Status

Accepted

## Context

Safeplane should support model access through a small gateway rather than direct provider SDKs in each workflow.

## Decision

The model gateway uses LiteLLM for real model calls.

For phase 0, the intended real provider path is OpenRouter through LiteLLM.

Normal tests use fake mode and do not call real models.

## Consequences

The first real model can be changed through configuration. Workflows call the Safeplane model gateway API, not LiteLLM directly.

