# Routing advisor experiment: initial Jev evaluation

> **Status:** promising experimental result; not production routing policy.
>
> Safeplane's deterministic routing and authorization boundaries remain unchanged. This experiment asks whether a semantic advisor can recommend `chat`, `assistant`, `developer`, or `unclear` accurately enough to be useful alongside deterministic routing.

## Research question

Safeplane currently exposes distinct workflows with different capabilities:

- `chat` for general conversation, explanations, writing, and generic technical help;
- `assistant` for personal-assistant work, especially calendar and notification tasks;
- `developer` for repository-scoped software engineering;
- `unclear` as an experimental abstention label when the request does not contain enough information to route safely.

The experiment evaluates whether Jev can infer that semantic intent from natural-language requests without becoming an authorization boundary.

## Experiment setup

The benchmark contains **420 frozen synthetic cases**:

| Expected result | Cases |
|---|---:|
| `chat` | 120 |
| `assistant` | 120 |
| `developer` | 120 |
| `unclear` | 60 |
| **Total** | **420** |

The corpus includes straightforward cases, matched minimal pairs, route-spoofing cases, missing artifacts, missing repository context, vague requests, and cross-workflow requests.

A fixed split was declared before evaluation:

- **315 calibration cases**
- **105 untouched holdout cases**

Thresholds for selective routing were explored on calibration only. Holdout results were then calculated without retuning.

### Model

- Configured model: `typesafe/jev-1.13`
- Observed model revision: `typesafe/jev-1.13-20260917`
- Completed cases: **420 / 420**
- Provider/evaluation errors: **0**

Each request produced one route choice plus independent semantic judgments for ambiguity, repository work, missing repository context, and assistant-tool need.

## Headline results

| Metric | Result |
|---|---:|
| Raw accuracy | **94.05%** |
| Decisive-case accuracy | **99.44%** |
| Holdout decisive-case accuracy | **100.00%** |
| Ambiguous/unclear recall | **61.67%** |
| Holdout ambiguous/unclear recall | **53.33%** |
| Dangerous escalations in raw routing | **23** |
| Median route margin | **1.000** |
| Estimated total model cost | **$0.025696** |
| Median case latency | **296 ms** |

The raw accuracy understates how well the model distinguished the three concrete workflows. Of the **360 decisive cases, 358 were routed correctly**.

The main weakness was not choosing among `chat`, `assistant`, and `developer`. It was knowing when **not to choose**.

## Confusion matrix

Rows are expected labels; columns are Jev's raw route choices.

| Expected \ Predicted | `chat` | `assistant` | `developer` | `unclear` |
|---|---:|---:|---:|---:|
| `chat` | **120** | 0 | 0 | 0 |
| `assistant` | 1 | **119** | 0 | 0 |
| `developer` | 0 | 0 | **119** | 1 |
| `unclear` | 3 | 13 | 7 | **37** |

This yields:

- `chat`: **100% recall**
- `assistant`: **99.17% recall**
- `developer`: **99.17% recall**
- `unclear`: **61.67% recall**

The lower precision for `assistant` and `developer` is almost entirely caused by ambiguous requests being routed instead of abstained.

## Boundary tests

Several deliberately difficult families behaved very well:

| Family | Cases | Accuracy |
|---|---:|---:|
| Matched minimal pairs | 90 | **100%** |
| Route spoofing | 20 | **100%** |
| Generic coding | 20 | **100%** |
| Repository changes | 25 | **100%** |
| Calendar actions | 30 | **100%** |
| Notification actions | 25 | **100%** |
| Repository testing | 15 | **100%** |

The failure pattern is concentrated in intentionally underspecified requests:

| Family | Cases | Accuracy | Dangerous escalations |
|---|---:|---:|---:|
| Vague assistant requests | 10 | **10%** | 9 |
| Vague repository requests | 10 | **40%** | 6 |
| Cross-workflow requests | 10 | **50%** | 5 |
| Missing artifact | 15 | **80%** | 3 |

Examples include requests such as:

- “Remind me about that.”
- “Can you look at safeplane?”
- “I need to work on the repo tomorrow; can you handle both parts?”
- “Please rewrite the following.”

These requests are deliberately missing information that would be needed for a reliable routing decision.

## Selective routing changes the result

Raw routing always has to choose a label. A production routing advisor does not.

The experiment therefore evaluates policies that accept Jev's recommendation only when the semantic evidence is sufficiently strong and otherwise abstain.

One conservative calibration-derived candidate was:

```text
top route probability >= 0.50
route margin >= 0.10
ambiguity probability <= 0.50
```

Its results were:

| Metric | Calibration | Untouched holdout |
|---|---:|---:|
| Automatic-routing coverage | **80.63%** | **80.95%** |
| Accuracy on accepted decisive cases | **100.00%** | **100.00%** |
| Ambiguous cases auto-routed | **0.00%** | **0.00%** |
| Dangerous escalations | **0** | **0** |
| Developer precision when accepted | **100.00%** | **100.00%** |

This is the most important result of the experiment.

The model does **not** appear suitable as an unconditional “always choose a workflow” router. It does appear promising as a **selective routing advisor that is allowed to abstain**.

At this operating point, roughly four out of five benchmark requests could be routed automatically while the remaining requests would fall back to deterministic handling or clarification.

## Cost and latency

The full 420-case run used:

- **611,820 input tokens**
- **49,598 output tokens**
- **$0.025696 estimated provider cost**
- **296 ms median latency per case**

That is approximately **$0.000061 per evaluated request** in this run.

The cost is low enough that semantic routing can plausibly be evaluated as a default advisory step, subject to model-gateway integration and production latency requirements.

## What this result supports

The experiment provides evidence for the following architecture:

```text
explicit deterministic route
        |
        +------------------------------> Safeplane harness

natural-language request
        |
        v
semantic routing advisor
        |
        +-- high-confidence, low-ambiguity recommendation
        |          |
        |          v
        |   deterministic routing policy
        |
        +-- ambiguous / insufficient context
                   |
                   v
          abstain / clarify / fallback
```

The semantic advisor should recommend a route. It should **not**:

- change workflow permissions;
- grant tool or network access;
- create repository context that is not present;
- bypass approval requirements;
- override explicit workflow commands;
- become an authorization boundary.

Those decisions remain deterministic Safeplane responsibilities.

## Current interpretation

The experiment answers two different questions differently:

**Can Jev distinguish the current Safeplane workflows when the request is sufficiently specified?**

The result is very strong: **99.44% decisive accuracy overall and 100% on the untouched decisive holdout cases**.

**Can Jev raw-route every natural-language request without an abstention policy?**

No. The raw classifier routed too many intentionally ambiguous requests to concrete workflows.

The practical design therefore is not “replace deterministic routing with Jev.” It is:

> **Use Jev to advise deterministic routing, accept only well-supported recommendations, and abstain when the request is ambiguous.**

## Limitations

This is an experimental benchmark, not evidence of production safety.

Important limitations:

1. The corpus is synthetic, even though it contains adversarial, boundary, and minimal-pair cases.
2. This is one model revision and one benchmark run.
3. The holdout split protects against direct threshold tuning, but it comes from the same corpus construction process.
4. Real Safeplane traffic may contain ambiguity patterns not represented here.
5. The recorded run reports `git_dirty=true`; it should be rerun from a clean committed experiment revision before being treated as the canonical reproducible baseline.
6. A semantic routing advisor must remain separate from authorization and capability enforcement.

## Next step

The result is strong enough to justify a **shadow-mode integration experiment**.

A reasonable next phase is:

1. route Jev through Safeplane's model gateway;
2. keep explicit `/chat`, `/assistant`, and `/develop` routing deterministic;
3. run the advisor on natural-language requests without letting it control execution;
4. record the suggested route, probabilities, ambiguity judgment, deterministic/operator route, and final outcome;
5. build a second benchmark from reviewed real-world shadow traffic;
6. reevaluate thresholds before enabling any automatic routing.

The central production metric should be **safe automatic-routing coverage**, not raw classification accuracy.

## Reproducibility and raw evidence

The generated experiment artifacts for this run are kept under `reports/`.

Recommended files to retain for the benchmark:

- [`20260921T194600Z.md`](../reports/20260921T194600Z.md) — generated human-readable report
- [`20260921T194600Z.json`](../reports/20260921T194600Z.json) — complete structured result data and probabilities
- [`20260921T194600Z.csv`](../reports/20260921T194600Z.csv) — per-case tabular results

Checkpoint files are execution state and do not need to be part of the published benchmark evidence.
