# Routing-advisor report artifacts

This directory contains the raw evidence produced by the Safeplane routing-advisor experiments.

For interpretation and conclusions, see the corresponding documents under `docs/runs/`.

## Current experiment status

### V1

V1 established that Jev could distinguish concrete Safeplane workflows very accurately, but it exposed a flaw in the original experiment design: routing ambiguity, missing execution details, and multi-workflow requests were partially conflated through one `unclear` label.

V1 is retained unchanged as historical evidence.

### V2

V2 separates:

- workflow selection;
- route identifiability;
- execution clarification;
- multi-workflow composition;
- repository context/readiness;
- assistant action requirements.

The first V2 run produced a strong positive result:

```text
450 / 450 single-workflow routes correct
135 / 135 fresh-holdout single-workflow routes correct
133 / 135 routable holdout requests automatically accepted
133 / 133 accepted holdout routes correct
0 / 22 route-unidentifiable holdout requests auto-routed
0 / 23 multi-workflow holdout requests auto-routed
0 dangerous holdout escalations
```

**Experiment decision:** good enough to proceed to repeatability testing and Safeplane shadow-mode integration.

**Not yet established:** production automatic-routing safety.

See the V2 run document under `docs/runs/` for the full evidence, limitations, and go/no-go decision.

## Directory layout

```text
reports/
├── README.md
├── v1/
│   ├── <timestamp>.json
│   ├── <timestamp>.csv
│   ├── <timestamp>.md
│   └── latest.*
└── v2/
    ├── <timestamp>.json
    ├── <timestamp>.csv
    ├── <timestamp>.md
    └── latest.*
```

Each experiment version has its own directory.

Do not move or rewrite historical timestamped evidence merely to make newer experiments look consistent.

## Canonical run artifacts

Each completed run writes:

- `<timestamp>.json`
- `<timestamp>.csv`
- `<timestamp>.md`

### JSON

The timestamped JSON is the canonical machine-readable record.

It contains:

- per-case model probabilities;
- expected labels;
- model/provider identity;
- observed model revision;
- workflow hashes;
- corpus and semantics hashes;
- token counts;
- cost;
- latency;
- aggregate metrics;
- calibration/holdout policy results.

### CSV

The timestamped CSV is the convenient per-case tabular representation.

### Markdown

The timestamped Markdown file is an automatically generated summary of the run.

It is evidence, not the final interpretation. Human-written interpretation belongs under `docs/runs/`.

## `latest.*`

Each version directory may also contain:

```text
latest.json
latest.csv
latest.md
```

These are convenience copies of the most recent run in that version.

They are not canonical historical identifiers and must not replace the timestamped artifacts.

## Checkpoints

Files such as:

```text
.checkpoint.jsonl
.checkpoint.meta.json
```

are local execution state.

They are ignored by Git and should not be published as benchmark evidence.

## Versioning rules

### Preserve completed experiments

Once an experiment run has been analyzed publicly:

- keep its corpus frozen;
- keep its semantic contract frozen;
- keep its timestamped reports;
- do not rewrite its historical result.

### Reproducibility runs

The exact same frozen experiment may be rerun against the same holdout to measure:

- decision stability;
- probability drift;
- model revision effects;
- provider/runtime effects.

Those are reproducibility runs, not new unseen evaluations.

### New design changes

If results are used to change:

- prompt/question wording;
- semantic definitions;
- corpus labels;
- routing policy;
- thresholds;
- experiment ontology;

create a new experiment version and a new unseen holdout.

Do not tune a version against a holdout after inspecting that holdout and then report it as fresh evidence.

## Interpretation rules

The routing advisor is not an authorization boundary.

A strong routing result does not allow the semantic model to:

- grant tools;
- change permissions;
- bypass approvals;
- create repository context;
- override explicit workflow selection.

Those remain deterministic Safeplane responsibilities.

The relevant production-oriented metric is:

> **safe automatic-routing coverage at zero observed dangerous escalations**

rather than raw classifier accuracy alone.
