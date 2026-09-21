# Integration Path if the Experiment Succeeds

## Intended production boundary

The routing advisor remains advisory after integration. Safeplane's trusted code owns the final transition from semantic evidence to a workflow entrypoint.

Recommended precedence:

```text
1. explicit /chat, /assistant, /develop or CLI command
   -> deterministic current behavior

2. no explicit workflow
   -> ask routing advisor
   -> deterministic policy accepts one route or abstains

3. accepted route
   -> normal workflow prerequisites/capabilities/approvals
   -> workflow may still clarify missing task details

4. multi-workflow / route-unidentifiable / advisor failure
   -> deterministic fallback, clarification, or future composition policy
```

No Jev output should directly instantiate an agent, attach MCP servers, select credentials, modify repository permissions, approve a patch, publish a PR, or bypass prerequisites.

## Why V2 maps better to production

V2 separates routing from execution readiness:

```text
route: Choice[chat, assistant, developer]
route_identifiable: Noul
needs_clarification_before_execution: Noul
requires_multiple_workflows: Noul
repository_work: Noul
missing_repository_profile: Noul
assistant_tool_need: Noul
```

Trusted code can therefore distinguish these outcomes:

```text
route=assistant + needs_clarification=true
    -> enter assistant, ask which meeting/reminder

route=developer + missing_repository_profile=true
    -> preserve developer intent, block execution until repo context exists

route_identifiable=false
    -> abstain before selecting a workflow

requires_multiple_workflows=true
    -> abstain or invoke a future explicit composition policy
```

This keeps semantic classification narrow and keeps authority/prerequisite handling deterministic.

## Components already shaped for transfer

### Workflow catalog

`safeplane_routing_advisor.catalog` resolves the real registry and workflow definitions and turns them into a bounded route catalog. Integration can move this code into the appropriate harness/registry package with minimal conceptual change.

The experiment-only routing metadata should later become versioned Safeplane-owned configuration, for example:

- explicit `routing` metadata inside workflow contracts;
- a versioned routing registry owned by the harness;
- a small schema-backed metadata file beside `safeplane.yaml`.

Do not hide routing semantics only inside prompts. They are policy inputs and should remain reviewable/versioned.

### Jev decision contract

`safeplane_routing_advisor.jev` constructs one Decisions request with a fixed typed question set. Production should preserve the bounded decision contract but replace direct OpenRouter transport.

### Deterministic policy

`safeplane_routing_advisor.policy` consumes probabilities and returns a route or abstention. Clarification and missing-repository-profile signals remain separate from route acceptance. The policy module has no provider dependency and is the shape to retain.

### Evaluation/reporting

The frozen V1/V2 corpora, runner, and reporting should remain under `experiments/` after integration as regression benchmarks. Production changes to workflow semantics, route policy, or model revision should be evaluated before release.

## Model-gateway transfer

The experiment directly calls:

```text
POST https://openrouter.ai/api/alpha/decisions
```

using `OPENROUTER_API_KEY` from the experiment `.env`.

Production Safeplane should route that operation through the model gateway so provider credentials and provider network access remain inside the existing model boundary.

A provider-neutral gateway request should carry approximately:

```json
{
  "model_profile": "routing_advisor",
  "state": {
    "request": "...",
    "supplied_context": {}
  },
  "questions": {
    "route": {},
    "route_identifiable": {},
    "needs_clarification_before_execution": {},
    "requires_multiple_workflows": {}
  }
}
```

and return validated typed answers. The harness should not know OpenRouter's URL or authentication details.

## Suggested rollout

### Phase 0: experiment

Current directory only. No production effect.

### Phase 1: shadow mode

For requests without an explicit route, call the advisor and persist:

- deterministic/operator route if one exists;
- advised route and full route probabilities;
- route-identifiable probability;
- clarification probability;
- multi-workflow probability;
- repository/tool diagnostic probabilities;
- policy accept/abstain result;
- workflow/catalog revision;
- model revision, cost, and latency.

Never alter execution.

### Phase 2: reviewed suggestion mode

For cases accepted by the frozen policy, surface or log the proposed route while still requiring deterministic/operator confirmation. Review disagreements and build a separately labeled real-traffic corpus.

### Phase 3: selective default routing

Only if shadow evidence supports it, allow deterministic policy to accept a subset of advisor decisions. Explicit commands still override. Route-unidentifiable or multi-workflow cases abstain.

Developer advice should remain conservative because it leads into repository-scoped capabilities, even though the developer workflow itself remains bounded by normal Safeplane controls.

## Conversation context

The synthetic corpora judge a request plus a small explicit context object. Production routing may need bounded recent context for follow-ups such as "move it to 3" or "apply that to the repo."

Do not send arbitrary full history by default. Define a typed routing-context contract and evaluate it separately. The advisor should receive only information needed to identify the workflow, not secrets or unrelated conversation state.

## Failure behavior

A provider timeout, invalid response, unsupported workflow set, stale catalog, policy abstention, or model-gateway failure must never broaden authority. The safe behavior is deterministic fallback or clarification.

The routing advisor should be observable but non-essential: Safeplane must remain usable through explicit workflow commands when Jev or the model gateway is unavailable.
