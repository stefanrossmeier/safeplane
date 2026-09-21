# Routing Advisor Experiment — V1 Initial Run

**Run:** `20260921T194600Z`  
**Status:** completed baseline experiment  
**Model:** `typesafe/jev-1.13`  
**Observed model revision:** `typesafe/jev-1.13-20260917`  
**Corpus:** 420 frozen synthetic cases  
**Purpose:** determine whether Jev is promising as a semantic routing advisor for Safeplane.

> This document records the first run as historical experimental evidence. It should not be rewritten to make later experiments look better. Changes to the routing ontology, prompts, policy, or corpus belong in a new experiment version.

## 1. Question

Can a small semantic decision model recommend the appropriate Safeplane workflow from natural-language requests while leaving execution authority, permissions, prerequisites, and policy enforcement deterministic?

The V1 experiment evaluated four routing labels:

- `chat`
- `assistant`
- `developer`
- `unclear`

It also asked independent binary questions about:

- ambiguity;
- repository work;
- missing repository profile;
- assistant-tool need.

## 2. Corpus

The frozen V1 corpus contains 420 cases:

| Expected result | Cases |
|---|---:|
| `chat` | 120 |
| `assistant` | 120 |
| `developer` | 120 |
| `unclear` | 60 |
| **Total** | **420** |

A fixed split was created before evaluation:

| Split | Cases |
|---|---:|
| Calibration | 315 |
| Holdout | 105 |

The corpus includes straightforward examples, generic coding, repository work, calendar and notification actions, matched minimal pairs, route-spoofing cases, missing artifacts, vague requests, and cross-workflow requests.

## 3. Headline result

The full run completed all 420 cases with no provider/evaluation errors.

| Metric | Result |
|---|---:|
| Raw four-way accuracy | **94.05%** |
| Decisive-route accuracy | **99.44%** |
| Holdout decisive-route accuracy | **100.00%** |
| `unclear` recall | **61.67%** |
| Holdout `unclear` recall | **53.33%** |
| Raw dangerous escalations | **23** |
| Estimated provider cost | **$0.025696** |
| Median latency | **296 ms** |

The main result is therefore not that Jev struggled to distinguish Safeplane workflows. It did not.

Of the 360 cases with a concrete expected route, **358 were routed correctly**.

The weakness was the V1 definition and handling of `unclear`.

## 4. Confusion matrix

Rows are expected labels; columns are raw Jev route choices.

| Expected \ Predicted | `chat` | `assistant` | `developer` | `unclear` |
|---|---:|---:|---:|---:|
| `chat` | **120** | 0 | 0 | 0 |
| `assistant` | 1 | **119** | 0 | 0 |
| `developer` | 0 | 0 | **119** | 1 |
| `unclear` | 3 | 13 | 7 | **37** |

Concrete-route recall:

- `chat`: **100%**
- `assistant`: **99.17%**
- `developer`: **99.17%**

## 5. Strong boundary results

Several deliberately difficult families were perfect in the first run:

| Family | Cases | Accuracy |
|---|---:|---:|
| Matched minimal pairs | 90 | **100%** |
| Route spoofing | 20 | **100%** |
| Generic coding | 20 | **100%** |
| Repository changes | 25 | **100%** |
| Calendar actions | 30 | **100%** |
| Notification actions | 25 | **100%** |
| Repository testing | 15 | **100%** |

This is useful evidence that the result is not simply keyword matching.

## 6. Where V1 failed

The errors were concentrated in four intentionally difficult families:

| Family | Cases | Raw accuracy | Raw dangerous escalations |
|---|---:|---:|---:|
| Vague assistant | 10 | **10%** | 9 |
| Vague repository | 10 | **40%** | 6 |
| Cross-workflow | 10 | **50%** | 5 |
| Missing artifact | 15 | **80%** | 3 |

Only two concrete-route cases were wrong:

1. `assistant-113`  
   Expected `assistant`, predicted `chat`:

   > Create a quick checklist of things I should bring to my appointment tomorrow.

2. `developer-065`  
   Expected `developer`, predicted `unclear`:

   > Find the source of the developer workflow description and explain how it is used.

These are useful boundary examples for refining the routing contract.

## 7. Important diagnostic finding: the ambiguity Noul was stronger than the `unclear` Choice label

V1 asked Jev both:

1. to choose among `chat`, `assistant`, `developer`, and `unclear`; and
2. independently whether the request was ambiguous.

Those two signals behaved differently.

All **23 `unclear` cases that were raw-routed to a concrete workflow** still received an ambiguity probability above `0.5`.

Examples:

| Request | Raw route | Ambiguity probability |
|---|---|---:|
| “Please rewrite the following.” | `chat` | 0.83 |
| “Help me with safeplane and also put something on my calendar.” | `assistant` | 0.85 |
| “I have a problem in my repo.” | `developer` | 0.90 |
| “Remind me about that.” | `assistant` | 0.89 |
| “Move my meeting.” | `assistant` | 0.79 |

This is why deterministic composition performed much better than raw four-way classification.

A calibration-derived selective policy using the dedicated ambiguity signal achieved approximately **81% automatic coverage** with:

- **100% accepted decisive accuracy** on holdout;
- **0% ambiguous auto-routing** on holdout;
- **0 dangerous escalations** on holdout;
- **100% accepted developer precision** on holdout.

This strongly supports the architecture:

> Jev supplies narrow semantic judgments; Safeplane code composes them into the actual routing decision.

## 8. More important finding: V1 mixes routing ambiguity with execution incompleteness

Reviewing the V1 failures reveals a taxonomy issue.

Several cases labeled `unclear` do not actually have an unclear workflow destination. They are missing information needed to *complete* the task, but the appropriate workflow is still identifiable.

Examples:

> “Cancel my reminder.”

This is incomplete because the reminder is unspecified, but it is clearly an `assistant` request.

> “Schedule it for me.”

Again, execution requires context, but the workflow is clearly `assistant`.

> “Can you debug the snippet below?”

The snippet is missing, but this is still naturally a `chat` request under the V1 workflow semantics because no repository work is requested.

> “I need something changed in safeplane.”

The requested change is underspecified, but the request is clearly repository-scoped and therefore naturally belongs to `developer`.

V1 therefore conflates at least three separate questions:

1. **Which workflow should receive the request?**
2. **Is there enough information to execute the request?**
3. **Does the request require more than one workflow?**

That is likely the largest conceptual improvement available for V2.

## 9. What V1 establishes

The first run provides strong evidence for continuing the experiment.

It supports the following conclusions:

- Jev can distinguish `chat`, `assistant`, and `developer` very accurately on the current synthetic corpus.
- Matched boundary cases and route-spoofing cases did not cause meaningful failures.
- Direct four-way routing with `unclear` is weaker than deterministic composition of narrower semantic judgments.
- An abstaining routing policy can provide high safe coverage.
- The experiment is cheap enough to iterate repeatedly.
- The current `unclear` label policy needs redesign before the benchmark should be treated as a final routing evaluation.

It does **not** establish that semantic routing is production-safe.

## 10. V2 hypothesis

V2 should test a cleaner decomposition.

Instead of:

```text
Choice[chat, assistant, developer, unclear]
+
ambiguous?
```

use something closer to:

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

The deterministic policy can then distinguish:

- **clear route + enough execution context** → route normally;
- **clear route + missing task details** → route to the correct workflow, which can clarify;
- **no identifiable route** → abstain before workflow selection;
- **multiple workflows required** → abstain or invoke a future composition policy;
- **missing repository profile** → preserve the developer route but block execution until repository context is provided.

This design better matches what a routing advisor is actually supposed to decide.

## 11. V2 evaluation requirements

Because the V1 holdout has now been inspected, V2 must not claim unbiased validation by reusing it as the final test set.

Recommended V2 procedure:

1. Freeze V1 exactly as recorded here.
2. Version the routing semantics and corpus as V2.
3. Use V1 cases as development/calibration material where useful.
4. Add a substantial set of new cases.
5. Freeze a **new unseen holdout before the first V2 provider run**.
6. Tune question wording and deterministic thresholds only on development/calibration data.
7. Evaluate the final V2 contract once against the new holdout.
8. Repeat the final frozen benchmark several times to measure decision stability.

## 12. Reproducibility

Raw artifacts for this baseline run:

- `reports/20260921T194600Z.md`
- `reports/20260921T194600Z.json`
- `reports/20260921T194600Z.csv`

The run recorded:

- Git commit: `7f05818d1ab3`
- Git dirty: `true`
- configured model: `typesafe/jev-1.13`
- observed revision: `typesafe/jev-1.13-20260917`

Because the checkout was dirty, this run should remain the **initial baseline**, not the permanent canonical reproducibility run.

A clean-tree rerun of V1 is useful to verify reproducibility, but improvements to the question contract or label ontology should be recorded as V2 rather than silently replacing this result.

## 13. Initial conclusion

V1 produced a clear positive signal.

The concrete Safeplane workflows were distinguished with **99.44% accuracy**, while the experiment exposed a tractable weakness in how abstention and missing execution context were modeled.

The appropriate next step is therefore not production integration yet, and not simply prompt-tuning the old benchmark.

It is to build a better V2 decision contract, freeze a new holdout, and rerun the experiment.
