# Harness-brokered MCP boundary

Safeplane uses MCP as a narrow tool boundary. The harness is the broker and
policy authority; workflows and connectors do not call MCP services directly.

```text
agent proposes tool call
-> harness validates agent permission and Pydantic input
-> harness calls the configured MCP service
-> service enforces its data boundary
-> harness validates the Pydantic output
-> validated result returns to the agent
```

## Core rules

- Tool access is deny-by-default and declared per workflow or agent.
- A model sees only tools explicitly allowed for its current agent.
- The harness validates tool names, inputs, outputs, retry limits, and run
  bindings.
- MCP services do not receive model-provider or Git credentials.
- MCP services do not choose workflow stages or grant permissions.
- Filesystem services resolve paths beneath an explicit SafePathPolicy root.
- Tool calls and results are recorded as run evidence without secret values.

## Current services

| MCP service | Purpose | Data boundary | External egress | Model-selectable |
| --- | --- | --- | --- | --- |
| `calendar-task-mcp` | list, create, and cancel calendar entries | `data/calendar` only | none | assistant tools through harness |
| `notification-task-mcp` | schedule, list, and cancel notifications | `data/notifications` only | none; delegates delivery work to scheduler | assistant tools through harness |
| `dev-workspace-mcp` | read repository files and Git metadata; produce replacement proposals | per-run workspace mounted read-only | none | permitted developer agents only |
| `dev-workspace-apply-mcp` | apply one validated patch to a controlled staging workspace | per-run workspace mounted writable | none | no; approval-only harness call |
| `dev-check-mcp` | run declared command profiles against a disposable candidate | per-run workspace read-only plus tmpfs candidate | none (`network_mode: none`) | no; harness-only |

## Permission examples

The `assistant` workflow may use:

```text
calendar_list
calendar_create
calendar_cancel
notification_schedule
notification_list
notification_cancel
```

The `chat` workflow has no MCP servers.

Developer agents receive different subsets. Analysis and planning are read-only;
implementation may inspect and propose exact replacements; documentation alone
may read the resolved external `archdoc` source; review is read-only; PR writing
has no MCP service. Apply and check execution remain harness-owned.

## Validation and retries

MCP inputs and outputs use strict Pydantic schemas. Invalid model tool calls may
receive bounded deterministic repair feedback within the workflow's configured
retry limit. A malformed service response, unauthorized tool, expired run
binding, or path escape is rejected.

Retries do not expand authority. They repeat only the same declared operation
under the same agent, run, workspace, and policy bindings.

## Logs and evidence

MCP logs are written under the capability-specific runtime log mount. Run traces
record sanitized tool-call metadata and validated results. Credentials are not
included in MCP environments, request payloads, logs, or evidence.

See [Container interactions](security/runtime-boundaries.md), [Developer tool
boundary](developer-tools.md), and [Calendar](calendar.md).
