# ADR 0016: Assistant is a separate workflow service

> Superseded note: this ADR describes the phase 4 service-based workflow design.
> It was superseded by the harness-owned agent runtime introduced later.
> Current workflow definitions are contracts; chat, assistant, and slow execute through the harness runtime.


## Status

Accepted

## Context

Phase 4 introduced the assistant workflow as the second workflow after chat.

Although the assistant initially behaves similarly to chat, it is expected to diverge later.

The assistant may eventually need different prompts, contracts, tool permissions, calendar capabilities, timed tasks, MCP servers, and safety rules.

## Decision

The assistant is implemented as a separate workflow and service.

Chat and assistant do not share a workflow implementation.

Current mapping:

    chat      -> chat-workflow
    assistant -> assistant-workflow

The assistant has its own:

- workflow contract
- prompt directory
- Docker service
- trace component
- session workflow id

Assistant sessions store:

    workflow_id: assistant

Chat sessions cannot be continued with assistant, and assistant sessions cannot be continued with chat.

## Consequences

There is some duplication in early phases.

The separation keeps future evolution clean.

Assistant-specific capabilities can be added later without turning chat into a generic mixed-purpose workflow.
