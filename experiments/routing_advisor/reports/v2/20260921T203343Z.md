# Safeplane Jev Routing Advisor Evaluation — V2

> V2 separates workflow selection from execution clarification and multi-workflow composition. This is experiment evidence, not production routing policy.

## Run identity

- Timestamp (UTC): `2026-09-21T20:33:43.327184+00:00`
- Git commit: `7f05818d1ab3`
- Git dirty: `True`
- Configured model: `typesafe/jev-1.13`
- Observed model revision(s): `typesafe/jev-1.13-20260917`
- Corpus version / decision contract: `v2` / `v2`
- Corpus SHA-256: `c35617aa7ec19645e3a69703bed4dd611d502e97362136223504a4196d376fac`
- Cases: `600` (600 completed, 0 errors)
- Calibration / fresh holdout: `420` / `180`

## Core route-selection result

- Single-workflow route accuracy: **100.00%** over `450` cases
- Raw authority escalations among single-workflow cases: **0**
- Route-unidentifiable cases: `75`
- Multi-workflow cases: `75`
- Median route margin: `1.000`

### Calibration versus untouched holdout

| Split | Cases | Single-route cases | Route accuracy | Raw escalations |
|---|---:|---:|---:|---:|
| calibration | 420 | 315 | 100.00% | 0 |
| holdout | 180 | 135 | 100.00% | 0 |

### Per-route precision / recall

Precision and recall are measured only on cases where exactly one concrete workflow is expected. V2 abstention-test cases are evaluated separately through the semantic judgements and deterministic policy.

| Route | Support | Precision | Recall |
|---|---:|---:|---:|
| chat | 150 | 100.00% | 100.00% |
| assistant | 150 | 100.00% | 100.00% |
| developer | 150 | 100.00% | 100.00% |

### Single-workflow confusion matrix

Rows are expected routes; columns are Jev's forced three-way route choice. Route-unidentifiable and multi-workflow cases are excluded from this matrix because V2 evaluates their abstention through independent judgements and deterministic policy.

| Expected \ Predicted | chat | assistant | developer |
|---|---:|---:|---:|
| chat | 150 | 0 | 0 |
| assistant | 0 | 150 | 0 |
| developer | 0 | 0 | 150 |

## Independent semantic judgements

Metrics below use a descriptive 0.5 threshold. Brier score measures probability calibration (lower is better; 0 is perfect). Clarification is deliberately not used as a routing-abstention gate.

| Judgement | Support | Positives | Accuracy | Precision | Recall | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Route identifiable | 600 | 525 | 97.33% | 97.04% | 100.00% | 0.0297 |
| Needs clarification before execution | 450 | 75 | 66.44% | 33.19% | 100.00% | 0.2490 |
| Requires multiple workflows | 600 | 75 | 100.00% | 100.00% | 100.00% | 0.0387 |
| Repository work | 525 | 225 | 100.00% | 100.00% | 100.00% | 0.0015 |
| Missing repository profile | 525 | 88 | 99.81% | 98.88% | 100.00% | 0.0085 |
| Assistant calendar/notification action | 525 | 175 | 100.00% | 100.00% | 100.00% | 0.0007 |

## Candidate V2 selective-routing operating points

Candidates are chosen **only on calibration**. The strict filter requires >=99% accuracy on accepted single-workflow cases, <=1% auto-routing of route-unidentifiable cases, <=1% auto-routing of multi-workflow cases, zero dangerous escalations, and >=99% developer precision. Holdout columns are then calculated without retuning.

Clarification probability and missing repository-profile probability are intentionally not routing gates: those signals belong to execution readiness after the workflow intent has been identified.

| min top p | min margin | min identifiable p | max multi p | cal coverage | cal route acc | holdout coverage | holdout route acc | holdout unidentifiable auto-route | holdout multi auto-route | holdout policy accuracy | holdout escalations | holdout dev precision |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 0.00 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.50 | 0.10 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.50 | 0.20 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.50 | 0.30 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.50 | 0.40 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.50 | 0.50 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.60 | 0.00 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.60 | 0.10 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.60 | 0.20 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |
| 0.60 | 0.30 | 0.80 | 0.50 | 74.29% | 100.00% | 73.89% | 100.00% | 0.00% | 0.00% | 98.89% | 0 | 100.00% |

## Family-level results

| Family | Support | Single-route support | Single-route accuracy | Route-identifiable accuracy | Multi-workflow accuracy | Mean margin |
|---|---:|---:|---:|---:|---:|---:|
| calendar_action | 25 | 25 | 100.00% | 100.00% | 100.00% | 1.000 |
| conceptual_chat | 75 | 75 | 100.00% | 100.00% | 100.00% | 0.986 |
| generic_coding | 25 | 25 | 100.00% | 100.00% | 100.00% | 0.990 |
| missing_artifact_clear_route | 25 | 25 | 100.00% | 100.00% | 100.00% | 0.989 |
| missing_identifier_clear_route | 25 | 25 | 100.00% | 100.00% | 100.00% | 0.998 |
| missing_task_detail_clear_route | 25 | 25 | 100.00% | 100.00% | 100.00% | 1.000 |
| multi_workflow | 75 | 0 | n/a | 100.00% | 100.00% | 0.812 |
| personal_planning | 50 | 50 | 100.00% | 100.00% | 100.00% | 0.839 |
| reminder_action | 25 | 25 | 100.00% | 100.00% | 100.00% | 1.000 |
| repository_change | 25 | 25 | 100.00% | 100.00% | 100.00% | 1.000 |
| repository_docs | 25 | 25 | 100.00% | 100.00% | 100.00% | 1.000 |
| repository_inspection | 50 | 50 | 100.00% | 100.00% | 100.00% | 1.000 |
| route_spoofing | 75 | 75 | 100.00% | 100.00% | 100.00% | 0.988 |
| route_unidentifiable | 75 | 0 | n/a | 78.67% | 100.00% | 0.379 |

## Cost and latency

- Input tokens: `1101271`
- Output tokens: `92400`
- Estimated provider cost: **$0.046253**
- Median case duration: `292.8 ms`

## Errors and concrete-route misroutes

Provider/evaluation errors: `0`. Concrete-route misroutes: `0`.

## Interpretation guardrails

- V2's holdout is fresh at the topic level and must not be used to tune prompts, semantics, or thresholds after the first final V2 evaluation.
- A good synthetic result supports shadow-mode integration; it does not make Jev an authorization boundary.
- Explicit workflow commands remain deterministic and override semantic advice.
- Clarification, repository-profile readiness, permissions, approvals, and workflow capabilities remain deterministic harness/workflow concerns.
- Production integration should replace this direct OpenRouter transport with Safeplane's model gateway.
- Final confidence should include repeated frozen V2 runs and then reviewed shadow-mode traffic.

