# ADR 0021: Harness-owned MCP foundation

## Status

Accepted

## Context

Safeplane needs MCP tools, but tool access must be controlled centrally.

The assistant, chat workflow, Telegram connector, and future developer workflow should not call tools directly.

Tool calls may mutate durable user data, execute commands, or access files.

Therefore tool access requires workflow permissions, schema validation, logging, and root/path enforcement.

## Decision

The harness is the MCP client and broker.

Workflows may propose tool calls, but the harness decides whether they are allowed.

Workflow contracts declare allowed MCP servers and tools.

MCP access is deny-by-default.

Tool input schemas use Pydantic.

Tool output schemas use Pydantic.

Invalid model-produced tool-call schemas are retryable.

The default retry budget is:

    max_tool_call_retries: 5

This means an initial attempt plus five repair attempts.

MVP 9 implements the retry primitive.

MVP 10 will use it in the assistant tool-call loop.

MCP access is logged under:

    SAFEPLANE_HOME/logs/mcp/tool-access.jsonl

MCP server execution logs live under:

    SAFEPLANE_HOME/logs/mcp/

These are normal Safeplane logs and serve as the audit trail.

MCP Roots are not used as a required safety boundary in MVP 9.

Safeplane uses its own path/root enforcement.

For filesystem-like tools, the policy is:

    resolve paths as if the tool has cd'ed into its allowed root
    reject every relative or absolute path outside that root

## Consequences

Tool access is centrally visible.

Unauthorized workflow tool use is rejected by the harness.

Invalid tool input does not reach the MCP server.

Invalid tool output is detected before being returned to a workflow.

The calendar MCP service proves the broker boundary without enabling assistant calendar behavior yet.

Assistant calendar usage moves to MVP 10.

Future developer workspace MCP tools can reuse the same broker, schema, logging, retry, and path enforcement foundations.
