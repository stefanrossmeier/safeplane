# Routing advisor V2 promotion evidence

This document preserves the production-relevant result of the former `experiments/routing_advisor` evaluation after that experiment was promoted into Safeplane and removed from the repository.

## Evaluation identity

The frozen V2 evaluation completed on 2026-09-21 using:

- configured model: `typesafe/jev-1.13`;
- observed revision: `typesafe/jev-1.13-20260917`;
- corpus/decision contract: V2;
- 600 completed cases and 0 provider/evaluation errors;
- 420 calibration cases; and
- 180 untouched holdout cases.

The V2 contract explicitly separated workflow selection from execution clarification, repository-profile readiness, and multi-workflow composition.

## Core result

Across the 450 single-workflow cases, Jev selected the expected semantic route in 450/450 cases:

| Route | Support | Precision | Recall |
| --- | ---: | ---: | ---: |
| `chat` | 150 | 100.00% | 100.00% |
| `assistant` | 150 | 100.00% | 100.00% |
| `developer` | 150 | 100.00% | 100.00% |

The untouched holdout contained 135 single-route cases and retained 100.00% route accuracy with zero raw authority escalations.

Independent V2 judgements also identified all 75 multi-workflow cases correctly. Route-identifiability was intentionally harder: the evaluation contained 75 route-unidentifiable cases and used a probability threshold rather than treating the forced three-way route choice as sufficient evidence for dispatch.

## Promoted operating point

Threshold selection was performed on calibration only. The production integration promotes this selected point:

| Parameter | Value |
| --- | ---: |
| Minimum top-route probability | `0.50` |
| Minimum route margin | `0.00` |
| Minimum route-identifiable probability | `0.80` |
| Maximum multiple-workflows probability | `0.50` |

On the untouched holdout this produced:

- 73.89% automatic-routing coverage;
- 100.00% route accuracy among accepted single-workflow cases;
- 0.00% automatic routing of route-unidentifiable cases;
- 0.00% automatic routing of multi-workflow cases;
- zero dangerous authority escalations; and
- 100.00% developer precision among accepted routes.

The holdout policy accuracy was 98.89% when acceptance/abstention behavior was scored together.

## Representative families

The frozen corpus included both ordinary and adversarially useful routing families. Notable results included:

- reminder actions: 25/25 correct single-route selections;
- calendar actions: 25/25;
- conceptual chat: 75/75;
- generic coding: 25/25;
- repository changes: 25/25;
- repository documentation: 25/25;
- repository inspection: 50/50;
- route-spoofing cases: 75/75; and
- multi-workflow cases: 75/75 for the independent multiple-workflows judgement.

The evaluation used about 1.10 million input tokens and 92,400 output tokens, reported an estimated provider cost of approximately $0.0463, and had a median case duration of about 293 ms.

## Production interpretation

These results justified integrating an advisor; they did **not** justify transferring authority to a model. Production therefore keeps the following boundaries:

- explicit workflow commands are deterministic and override semantic advice;
- Jev chooses only from a closed semantic route set;
- the harness validates the decision and applies deterministic thresholds;
- ambiguous and multi-workflow requests abstain;
- clarification does not silently change an otherwise identifiable workflow;
- repository-profile readiness, permissions, approvals, workflow capabilities and tool access remain deterministic concerns; and
- provider/model failure fails closed rather than selecting a fallback workflow.

The original experiment implementation, generated reports and corpus were removed after promotion so Safeplane has one maintained production decision contract rather than parallel experimental and production copies. The production implementation is covered by offline tests plus an opt-in live Jev smoke suite.
