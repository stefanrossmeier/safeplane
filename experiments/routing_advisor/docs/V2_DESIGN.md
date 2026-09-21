# Routing Advisor V2 — Design and Evaluation Plan

## Status

V2 is a new frozen experiment contract built from lessons learned in V1. V1 remains intact and reproducible; V2 does not retroactively change V1 labels or results.

## What V1 established

V1 showed that Jev could distinguish concrete `chat`, `assistant`, and `developer` cases very accurately, but the single `unclear` route mixed several different concepts:

1. the workflow itself cannot be identified;
2. the workflow is identifiable but execution details are missing;
3. the request requires capabilities from more than one workflow;
4. repository work is clear but deterministic repository context is missing.

Those cases should not be scored as the same routing failure mode.

## V2 hypothesis

A better decision contract should improve usefulness and interpretability by asking narrow, orthogonal questions:

```text
route:
    Choice[chat, assistant, developer]

route_identifiable:
    Noul

needs_clarification_before_execution:
    Noul

requires_multiple_workflows:
    Noul

repository_work:
    Noul

missing_repository_profile:
    Noul

assistant_tool_need:
    Noul
```

The deterministic policy, not Jev, then decides whether to accept a route, abstain, or block execution on a prerequisite.

## Label policy

### Concrete single-workflow route

A case receives `expected_route = chat|assistant|developer` when one workflow is the best semantic destination, even if that workflow must ask for more information.

Examples:

```text
Rewrite the paragraph below so it is clearer.
```

Expected:

```text
route = chat
route_identifiable = true
needs_clarification_before_execution = true
```

The paragraph is missing, but the workflow is not ambiguous.

```text
Move my meeting.
```

Expected:

```text
route = assistant
route_identifiable = true
needs_clarification_before_execution = true
assistant_tool_need = true
```

```text
Fix the caching problem in the selected repository.
```

Expected:

```text
route = developer
route_identifiable = true
needs_clarification_before_execution = true
repository_work = true
```

### Missing repository profile

A missing repository profile is a deterministic prerequisite, not a semantic route label.

```text
route = developer
repository_work = true
missing_repository_profile = true
```

Safeplane may still refuse to execute until repository context exists.

### Route unidentifiable

Use `expected_route = null` and `decision_type = route_unidentifiable` only when even the relevant workflow intent cannot be determined.

Example:

```text
Can you help with this? The referenced material and requested outcome are not in the conversation yet.
```

Expected:

```text
route_identifiable = false
requires_multiple_workflows = false
```

The forced three-way `route` answer is not scored as a route error for this case. Deterministic policy must abstain based on `route_identifiable`.

### Multi-workflow request

Use `expected_route = null` and `decision_type = multi_workflow` when the user clearly asks for capabilities from multiple workflows.

Example:

```text
Fix the retry bug in the selected repository and remind me tomorrow to review the patch.
```

Expected:

```text
route_identifiable = true
requires_multiple_workflows = true
repository_work = true
assistant_tool_need = true
```

Again, the forced three-way `route` answer is not treated as a classification error. Until Safeplane has an explicit composition policy, the routing advisor should abstain from selecting one workflow.

## Fresh V2 corpus

V2 contains 600 frozen cases generated from 150 topic-level contrast sets:

- 150 chat;
- 150 assistant;
- 150 developer;
- 75 route-unidentifiable;
- 75 multi-workflow.

The split is topic-disjoint:

- 105 topics / 420 cases are calibration;
- 45 different topics / 180 cases are final holdout.

This matters because the V1 holdout has already been inspected and therefore cannot be treated as an unbiased final test set for the redesigned contract.

## Evaluation metrics

### Route selection

Measured only where exactly one expected workflow exists:

- route accuracy;
- per-route precision and recall;
- confusion matrix;
- route probability and margin;
- dangerous upward route errors.

### Independent judgements

Each binary judgement is evaluated with:

- accuracy at a descriptive 0.5 threshold;
- precision;
- recall;
- Brier score.

Clarification quality is reported independently. It is not used to reject an otherwise valid workflow route.

### Selective routing

A V2 candidate policy accepts a route only when:

```text
top route probability >= P
route margin >= M
route_identifiable probability >= I
requires_multiple_workflows probability <= W
```

Calibration-only candidate filtering requires:

- >=99% accepted single-workflow route accuracy;
- <=1% route-unidentifiable auto-route rate;
- <=1% multi-workflow auto-route rate;
- zero dangerous escalations;
- >=99% developer precision when accepted.

The chosen calibration candidates are then evaluated unchanged on holdout.

## Holdout discipline

The first final V2 holdout run is the important one.

After the holdout has been inspected:

- do not silently change V2 prompts and call the same holdout unbiased;
- any semantic/prompt/corpus redesign should become V3 or use a new holdout;
- repeated runs of the exact frozen V2 configuration are allowed and useful for stability analysis, but they are not additional independent holdouts.

## Repeatability

Because Jev evaluation is inexpensive, the final frozen V2 experiment should be run multiple times without changes.

Compare:

- route flip rate;
- threshold-crossing flips for every Noul judgement;
- probability drift;
- selective-policy decision flips;
- cost and latency distributions.

If the same frozen corpus produces unstable policy decisions, a strong single-run accuracy number is insufficient for integration.

## Integration criterion

V2 is successful enough for shadow-mode integration if the fresh holdout and repeated frozen runs show that a meaningful share of requests can be automatically advised while:

- accepted route accuracy remains very high;
- developer precision remains very high;
- route-unidentifiable and multi-workflow requests are reliably abstained;
- no dangerous authority escalations appear in the evaluated operating point;
- probabilities and resulting policy decisions are sufficiently stable across repeated runs.

Shadow mode should then collect reviewed real Safeplane traffic before semantic advice is allowed to influence default routing.
