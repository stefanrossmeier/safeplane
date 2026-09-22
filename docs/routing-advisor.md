# Routing advisor

Safeplane supports both explicit deterministic workflow selection and optional natural-language workflow routing.

The routing advisor is deliberately **advisory**. It selects a semantic workflow intent, but it does not grant tools, credentials, repository access, approvals, or any other authority. Those controls remain deterministic and harness-owned.

## Execution boundary

Automatic routing follows this path:

```text
connector `auto` request
        |
        v
      harness
        |
        v
model-gateway `/decisions`
        |
        v
       Jev
        |
        v
deterministic routing policy
        |
        v
existing workflow registry and execution path
```

Explicit entrypoints bypass the advisor and keep their existing deterministic meaning:

```text
safeplane chat ...
safeplane assistant ...
safeplane develop --repo <profile> ...
safeplane run <entrypoint> ...
```

Telegram slash commands are deterministic for the same reason. Plain Telegram messages use automatic routing when `connectors.telegram.routing_mode` is `automatic`.

## Semantic routes

The production V2 decision contract has a closed semantic route set:

| Semantic route | Safeplane entrypoint | Intended scope |
| --- | --- | --- |
| `chat` | `chat` | Conversation, writing, explanation, generic coding and other non-action general work |
| `assistant` | `assistant` | Calendar, reminders, notifications and personal planning |
| `developer` | `develop` | Work on a selected software repository |

Workflow-specific routing descriptions and positive/negative signals live beside the workflow contracts in `workflows/*/workflow.yaml`. The global decision questions, route mapping and thresholds live under `routing_advisor` in `safeplane.yaml`.

The advisor may only recommend one of the configured semantic routes. The harness resolves that recommendation through the normal workflow registry before anything executes.

## V2 selective-routing policy

Safeplane promotes the operating point selected by the frozen V2 routing evaluation:

| Gate | Production value |
| --- | ---: |
| Minimum top-route probability | `0.50` |
| Minimum route margin | `0.00` |
| Minimum route-identifiable probability | `0.80` |
| Maximum multiple-workflows probability | `0.50` |

A route is accepted only when all gates pass. Otherwise the advisor abstains.

`needs_clarification_before_execution` and `missing_repository_profile` remain diagnostic/execution-readiness signals rather than route-selection gates. For example, a request can clearly be developer work while still lacking the required repository profile.

## Fail-closed behavior

Automatic routing does not silently broaden authority or guess around missing infrastructure.

The harness refuses automatic dispatch when:

- Jev or the model gateway is unavailable;
- the decision payload is malformed;
- the semantic route is not in the configured closed set;
- the route-identifiable probability is too low;
- multiple workflows appear necessary;
- the selected workflow is not exposed/available through the existing registry; or
- deterministic execution prerequisites are absent, such as a repository profile for developer work.

An operator can always use an explicit deterministic entrypoint instead.

## Repository work

Jev can identify a request as `developer`, but that judgement does not authorize repository access. The normal developer contract still requires an explicit repository profile. Automatic developer routing without one returns a deterministic prerequisite error rather than selecting a less capable workflow or inventing repository context.

The CLI supports this directly:

```bash
./scripts/safeplane auto --repo <profile> "Fix the failing tests in this repository."
```

## Telegram session behavior

For a new plain-text Telegram conversation, the first message is routed automatically. Once accepted, Safeplane records the selected workflow and session. Follow-up plain-text messages continue that same workflow deterministically until `/new` resets the conversation.

This avoids reclassifying short follow-ups such as `yes`, `tomorrow`, or `use the first one` without the full conversational context. Explicit slash commands remain deterministic and do not depend on the advisor.

## Provider and secret boundary

The harness never calls OpenRouter directly. It sends a typed decision request to the model gateway, and the model gateway is the only service that reads the OpenRouter credential.

`MODEL_GATEWAY_MODE=fake` uses a small deterministic fake decision implementation for tests/local development. Real routing uses the OpenRouter Decisions endpoint with the configured Jev model.

## Evidence and traces

Every automatic decision has a routing id and records routing evidence, including:

- chosen semantic route and resolved Safeplane entrypoint;
- route probabilities and margin;
- independent semantic judgement probabilities;
- applied policy thresholds;
- model/provider metadata and reported usage/cost when available;
- decision latency;
- workflow/catalog metadata; and
- accepted, abstained, prerequisite-failed, or unavailable outcome.

Routing traces are stored under the normal Safeplane trace root. Accepted automatic decisions are also referenced from the resulting workflow run trace.

The evaluation evidence used to promote this design is summarized in [Routing advisor V2 evidence](evidence/routing-advisor-v2.md).

## Tests

Offline routing, gateway and harness tests run with the normal unit suite:

```bash
tests/scripts/test-unit -q
```

The live Jev smoke suite is opt-in because it performs real provider calls:

```bash
make test-routing-jev
```

It covers representative general-chat, reminder/assistant, repository/developer and compound multi-workflow requests. The live suite exercises the production decision transport and deterministic policy without invoking downstream workflow inference.
