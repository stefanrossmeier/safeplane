# Safeplane repo layout

Safeplane separates core runtime services, connectors, MCP servers, and workflow definitions.

## Core services

    services/
      harness/
      model-gateway/

Core services are part of the Safeplane execution runtime.

- `harness` owns sessions, runs, workflow registry, agent runtime, MCP brokering, tool permission checks, traces, and artifacts.
- `model-gateway` owns model-provider access and isolates model API secrets.

## Connectors

    connectors/
      telegram/

Connectors are transport adapters. They should stay dumb.

A connector should:

- receive external input
- authenticate/authorize the sender if needed
- call the harness
- return the harness response

A connector should not own workflow logic, model calls, memory, tools, or business rules.

## MCP servers

    mcp-servers/
      calendar-task/

MCP servers implement tool behavior behind a clear boundary.

The harness is the MCP client/broker and is responsible for:

- deciding which workflow may call which server/tool
- validating tool inputs and outputs
- logging access decisions
- preserving trace evidence

MCP servers perform the tool operation but do not decide whether a workflow is allowed to call them.

## Workflows

    workflows/
      assistant/
      chat/
      slow/

Workflows are contracts, not long-running services.

A workflow defines:

- entrypoints
- prompt references
- model profiles
- session behavior
- concurrency behavior
- allowed MCP servers/tools
- deterministic tool adapters

The generic agent runtime lives in the harness.

## Prompts

    prompts/
      assistant/
      chat/

Prompts are workflow-owned text artifacts loaded by the harness at runtime.

## Removed legacy workflow services

Earlier iterations used separate workflow services.

Those services were removed after the harness-owned runtime became the only active execution path.

Current execution uses workflow contracts plus the generic harness agent runtime.
