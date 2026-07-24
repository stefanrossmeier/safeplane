# ADR 0008 — Prompts are versioned Markdown

## Status

Accepted

## Context

Prompts should not be hardcoded directly in source code.

They should be inspectable, versioned, and traceable.

## Decision

Prompts are stored as Markdown files with YAML frontmatter.

Example:

    prompts/chat/system.v1.md

Prompt manifests may be used to list available versions:

    prompts/chat/manifest.yaml

The workflow contract pins the prompt version used by the workflow.

## Consequences

Prompt changes become visible repository changes. Traces can reference prompt id, version, and file path.

