# ADR 0031: Add advisory natural-language workflow routing

## Status

Accepted

## Context

Safeplane now has multiple operator-facing workflows and a deterministic workflow registry. Requiring the operator to name a workflow for every request is unnecessary friction, especially for conversational connectors such as Telegram.

A V2 Jev routing evaluation showed that a closed three-route decision contract can classify `chat`, `assistant`, and `developer` intent accurately while separately identifying route ambiguity and requests that require multiple workflows.

Routing must not become an authorization mechanism. Safeplane's core principles require deterministic ownership of workflow exposure, repository selection, credentials, tools, approvals and execution prerequisites.

## Decision

Safeplane adds an optional harness-owned `auto` entrypoint.

Automatic routing follows this sequence:

1. The harness builds a typed, closed-set decision request from versioned Safeplane routing metadata.
2. The model gateway sends that decision request to the configured Jev model.
3. The harness validates the response and applies deterministic selective-routing thresholds.
4. An accepted semantic route is mapped to an existing configured entrypoint and resolved through the normal workflow registry.
5. Normal deterministic workflow validation and execution continue unchanged.

Explicit workflow entrypoints remain deterministic and bypass the advisor.

Jev is advisory only. It cannot grant repository access, tools, credentials, approvals or capabilities. Developer work still requires an explicit repository profile. Requests that are insufficiently identifiable, require multiple workflows, fail prerequisites, or cannot obtain a valid advisor response fail closed.

Workflow-specific routing summaries and positive/negative signals live in each workflow contract. Global decision questions, route mappings and thresholds live in `safeplane.yaml`.

For Telegram, the first plain message in a new conversation may use automatic routing. Once a workflow/session is selected, follow-up plain messages remain pinned to that workflow until `/new` to avoid classifying context-dependent fragments in isolation. Slash commands remain deterministic.

Provider access remains behind the model gateway. Real routing uses Jev through the gateway; fake mode uses deterministic test behavior only.

## Consequences

Operators can use natural language without giving up explicit deterministic dispatch.

Routing decisions are inspectable and traceable.

The system can abstain instead of forcing a workflow for compound or ambiguous requests.

The workflow registry remains the executable source of truth, and routing cannot enlarge authority beyond what the selected workflow already permits.

Multi-workflow composition is still out of scope; compound requests intentionally abstain until a separate composition policy exists.
