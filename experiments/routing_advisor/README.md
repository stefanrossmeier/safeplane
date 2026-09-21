# Safeplane Routing Advisor Experiment

This directory evaluates whether a small semantic model can advise Safeplane workflow routing while **all authority-bearing decisions remain deterministic**.

The experiment is isolated from production Safeplane. It reads the current `safeplane.yaml` and the real `chat`, `assistant`, and `developer` workflow contracts, layers experiment-only routing semantics over them, sends bounded Jev Decisions requests, and stores complete evidence under `reports/`.

## Experiment versions

Two frozen experiment versions are intentionally kept side by side.

| Version | Status | Corpus | Decision contract |
|---|---|---:|---|
| V1 | historical baseline | 420 cases | `Choice[chat, assistant, developer, unclear]` + ambiguity/repository/tool diagnostics |
| V2 | current experiment | 600 cases | `Choice[chat, assistant, developer]` + route-identifiable, clarification, multi-workflow, repository/tool diagnostics |

V1 is not rewritten or deleted. Its files remain:

- `data/corpus.v1.json`
- `data/routing_semantics.v1.yaml`
- `scripts/build_corpus.py`

V2 lives next to it:

- `data/corpus.v2.json`
- `data/routing_semantics.v2.yaml`
- `scripts/build_corpus_v2.py`
- `docs/V2_DESIGN.md`

This versioning matters because V1 exposed a taxonomy problem: requests such as “move my meeting” or “rewrite the paragraph below” can have a **clear workflow route** while still missing information needed to execute. V2 therefore separates routing from execution readiness instead of forcing those concepts into one `unclear` label.

## V2 decision contract

Each V2 request makes one Jev Decisions call with these questions:

1. `route`: `choice` over `chat`, `assistant`, and `developer` only;
2. `route_identifiable`: whether the workflow intent can be identified at all;
3. `needs_clarification_before_execution`: whether the route is known but task-specific execution details are missing;
4. `requires_multiple_workflows`: whether the request needs more than one Safeplane workflow, such as repository work plus a reminder;
5. `repository_work`: whether a selected repository/codebase is part of the requested work;
6. `missing_repository_profile`: whether repository work is required but no repository profile is supplied;
7. `assistant_tool_need`: whether the request needs a calendar/reminder/notification action.

Trusted Python composes those judgements. Jev never grants a capability, changes permissions, invents repository context, bypasses approvals, or overrides explicit workflow commands.

### Why clarification is not an abstention signal

V2 deliberately allows outcomes such as:

```text
route = assistant
needs_clarification_before_execution = true
```

for a request such as:

```text
Move my meeting.
```

The correct workflow is still identifiable. The selected workflow may then ask which meeting and what target time.

Likewise:

```text
route = developer
missing_repository_profile = true
```

means that semantic routing can still identify repository work while deterministic Safeplane code blocks execution until repository context is provided.

## V2 corpus

`data/corpus.v2.json` contains **600 frozen cases** built as 150 contrast sets. Every topic produces:

- one `chat` case;
- one `assistant` case;
- one `developer` case;
- either one truly route-unidentifiable case or one explicit multi-workflow case.

Counts:

| Category | Cases |
|---|---:|
| `chat` | 150 |
| `assistant` | 150 |
| `developer` | 150 |
| route unidentifiable | 75 |
| multi-workflow | 75 |
| **Total** | **600** |

The split is done **at topic level**, not case level:

- first 105 topics → **420 calibration cases**;
- final 45 entirely different topics → **180 untouched holdout cases**.

The holdout topics are not present in calibration. Do not tune V2 questions, semantics, or thresholds after inspecting the holdout results.

The corpus also deliberately contains:

- generic coding versus selected-repository coding;
- route-spoofing instructions embedded in user text;
- clear routes with missing task-specific artifacts or identifiers;
- developer routes with and without a repository profile;
- assistant requests that do and do not require calendar/reminder tools;
- repository-plus-assistant requests that require composition rather than a single route.

## Selective routing policy

V2 does not use clarification probability as a route gate. Candidate routing policies are composed from:

```text
top route probability >= P
route margin >= M
route_identifiable probability >= I
requires_multiple_workflows probability <= W
```

Otherwise the advisor abstains.

Candidate operating points are selected **only on calibration** with a strict descriptive filter:

- at least 99% accuracy on accepted single-workflow cases;
- at most 1% auto-routing of route-unidentifiable cases;
- at most 1% auto-routing of multi-workflow cases;
- zero dangerous authority escalations;
- at least 99% developer precision when developer is accepted.

The same candidate thresholds are then measured on the untouched V2 holdout without retuning.

## Local setup

From the repository root:

```bash
cd experiments/routing_advisor
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`, then load it:

```bash
set -a
source .env
set +a
```

## Offline validation

Run all tests and verify both frozen corpora regenerate byte-for-byte:

```bash
make test
make corpus-check
```

Validate V2 against the current Safeplane registry/workflow contracts:

```bash
make validate
```

or explicitly:

```bash
make validate-v2
```

V1 remains reproducible:

```bash
make validate-v1
make corpus-check-v1
```

## Live runs

The default experiment is V2:

```bash
make run
```

Equivalent command:

```bash
.venv/bin/safeplane-routing-advisor run \
  --repo-root ../.. \
  --version v2 \
  --output-dir reports/v2
```

V2 writes checkpoints and reports only below `reports/v2/`, so historical V1 artifacts already stored directly in `reports/` are not overwritten.

To rerun V1 with the preserved V1 contract:

```bash
make run-v1
```

which writes to `reports/v1/`.

The CLI also accepts explicit corpus/semantics overrides for forensic reproduction:

```bash
.venv/bin/safeplane-routing-advisor run \
  --repo-root ../.. \
  --version v1 \
  --corpus data/corpus.v1.json \
  --semantics data/routing_semantics.v1.yaml \
  --output-dir reports/v1
```

## Reports

Each versioned run writes:

```text
reports/<version>/<timestamp>.json
reports/<version>/<timestamp>.csv
reports/<version>/<timestamp>.md
reports/<version>/latest.json
reports/<version>/latest.csv
reports/<version>/latest.md
```

The JSON report contains the complete per-case probability evidence. CSV is convenient for manual failure analysis. Markdown contains the headline metrics, calibration/holdout comparison, diagnostic quality, family results, candidate operating points, cost, latency, and misroutes.

Checkpoint files are version-local and are invalidated automatically when the corpus, semantics, workflow contracts, Safeplane registry, or configured model changes.

## Docker

Docker remains available and defaults to V2 because the CLI defaults to `--version v2`:

```bash
cd experiments/routing_advisor
cp .env.example .env
# set OPENROUTER_API_KEY

docker compose build
docker compose run --rm routing-advisor validate --repo-root /repo --version v2
docker compose run --rm routing-advisor run --repo-root /repo --version v2 --output-dir /app/reports/v2
```

## Interpretation

Do not reduce the result to raw route accuracy. For V2, inspect at least:

- single-workflow route accuracy;
- route-identifiable precision/recall and Brier score;
- multi-workflow precision/recall and Brier score;
- clarification quality independently of routing;
- developer precision;
- dangerous authority escalations;
- route-unidentifiable auto-route rate;
- multi-workflow auto-route rate;
- calibration versus holdout gap;
- coverage of strict selective-routing candidates;
- behavior across repeated frozen runs.

A strong V2 result would justify the next step: **shadow-mode integration through Safeplane's model gateway**. It would not justify making Jev an authorization boundary or immediately replacing explicit deterministic routing.

See `docs/V2_DESIGN.md` for the rationale and exact hypotheses, `docs/INTEGRATION.md` for the intended production boundary, and the repository's recorded run documentation for historical results.
