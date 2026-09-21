# Routing Advisor Experiment Results

Use this document after a recorded live run. The generated `reports/latest.md`, `latest.json`, and `latest.csv` are the evidence source; do not manually reconstruct metrics from terminal output.

## Run under review

- Safeplane commit:
- Git dirty state:
- Corpus version / SHA-256:
- Routing semantics SHA-256:
- Jev configured model:
- Observed model revision:
- Run timestamp:
- Total cost:
- Median latency:

## Executive finding

State what the experiment supports and what it does not support. Separate these questions:

1. Does Jev understand the current Safeplane route taxonomy?
2. Can a selective deterministic policy obtain sufficiently clean accepted routes?
3. Is performance stable on holdout rather than only calibration?
4. Are developer and ambiguity errors acceptable for moving to shadow mode?
5. Do cost and latency justify invoking the advisor when no explicit route was supplied?

Do not equate a perfect synthetic score with production safety.

## Raw routing quality

Record:

- overall raw accuracy;
- decisive accuracy;
- ambiguous/unclear recall;
- per-route precision and recall;
- dangerous authority escalations;
- calibration versus holdout gap.

Explain every developer false positive and every dangerous escalation individually.

## Boundary-family analysis

Review at least:

- `minimal_pair`;
- `route_spoofing`;
- `generic_coding` versus repository families;
- `missing_repository_profile`;
- `missing_artifact`;
- `vague_repository`;
- `vague_assistant`;
- `cross_workflow`.

For any weak family, determine whether the problem is the corpus label policy, routing semantics, Jev model behavior, or the deterministic acceptance policy. Do not silently relabel cases after seeing the output; create a new corpus version if the policy itself changes.

## Diagnostic probabilities

Discuss Brier scores for:

- ambiguity;
- repository-work intent;
- missing repository profile;
- assistant calendar/notification tool need.

Assess whether any of these independent signals materially improve safe selective routing beyond the raw route choice.

## Selective routing

From `candidate_operating_points`, choose the rows worth discussing. For each, record calibration and holdout:

- coverage;
- accepted decisive accuracy;
- ambiguous auto-route rate;
- dangerous escalations;
- developer precision.

If no candidate survives the strict calibration filter, say so directly. That is a valid experiment result.

## Failure analysis

Group misroutes by cause rather than listing only counts. Examples:

- keyword attraction;
- assistant/chat overlap;
- generic coding mistaken for repository work;
- missing context mistaken for a decisive route;
- user route-spoofing followed;
- probability distribution correct but deterministic threshold too permissive;
- provider/evaluation failure.

## Decision

Choose one evidence-based next step:

- stop the routing-advisor idea;
- revise semantics/corpus and repeat the isolated experiment;
- proceed to shadow-mode integration only;
- after separate shadow evidence, consider selective automatic default routing.

Document why. Keep explicit deterministic commands and harness authority out of scope for replacement.
