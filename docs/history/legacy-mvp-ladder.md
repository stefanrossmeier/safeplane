# Safeplane MVP Ladder

> Replanned after completion of MVP 22.
>
> This roadmap contains the work required to turn Safeplane into a credible
> public portfolio project without publishing an unproven deployment.
>
> **The repository must remain private until Safeplane has been deployed to a
> real VPS, exercised there, recovered there, and hardened from the issues that
> deployment reveals.**

Status date: 2026-07-21

Roadmap provenance:

- reconstructed from the complete post-MVP-22 roadmap;
- reconciled with the accepted MVP 23 Telegram milestone;
- updated with the accepted MVP 24 cleanup implementation and full
  validation evidence;
- preserves the full MVP 25–30 publication path and the deliberately postponed
  extensions from earlier approved ladder versions.

The root `/mvp-ladder.md` is the authoritative live planning document. Git
history and `docs/history/` may retain superseded versions.

---

# Current position

Current completed milestone:

- MVP 24 — MVP cleanup, neutral fixtures, and capability-oriented naming

Current recommended next milestone:

- MVP 25 — Secret, mount, network, and container hardening

Active path:

1. MVP 25 — Secret, mount, network, and container hardening
2. MVP 26 — Public-facing documentation and operator experience
3. MVP 27 — Reproducible VPS deployment package
4. MVP 28 — Private VPS deployment, recovery, and soak
5. MVP 29 — Public release candidate audit and clean-room verification
6. MVP 30 — Public portfolio release

Hard publication gate:

```text
MVP 28 must be complete before MVP 29 may be accepted.
MVP 29 must be complete before the repository is made public.
```

The VPS is not merely a documentation exercise. It is an evidence-producing
stage intended to reveal operational, security, persistence, recovery, resource,
and usability defects while the repository is still private.

Not part of the active publication path:

- automatic developer rework loops
- natural-language workflow routing
- LLM-assisted routing
- persistent semantic memory
- web UI
- additional connectors
- browser automation
- automatic merge
- automatic release
- automatic deployment of target repositories
- Safeplane developing Safeplane
- multi-user support
- Kubernetes, autoscaling, or high availability

These items may be reconsidered after the public portfolio release.

---

# Primary project goal

Safeplane should be publishable as a local-first, VPS-capable agent harness that
shows disciplined engineering rather than an unconstrained autonomous-agent
demo.

A public visitor should be able to understand and verify that:

1. connectors translate operator input but do not own orchestration;
2. the harness owns workflow state, permissions, retries, artifacts, and policy;
3. workflows are explicit, versioned contracts;
4. model access is isolated behind a model gateway;
5. tool access crosses harness-brokered MCP boundaries;
6. Pydantic schemas validate tool calls, workflow artifacts, and model outputs;
7. target repositories are prepared in isolated per-run workspaces;
8. agents do not receive Git credentials;
9. implementation proposals are validated against an approved plan before
   authoritative application;
10. checks run in a constrained container without inherited secrets or network
    access by default;
11. review is independent and explicit about plan alignment;
12. branch push and draft-PR creation remain harness-owned;
13. merge remains a human decision;
14. evidence is inspectable and sanitized;
15. the same system has been operated successfully on a real VPS before public
    release.

The target operator journey is:

```text
Telegram or CLI command
-> deterministic workflow selection
-> harness-owned run
-> isolated repositories and artifacts
-> bounded agents and MCP tools
-> deterministic checks and review
-> optional harness-owned draft PR
-> human inspection and merge decision
```

Safeplane remains single-pass. It does not automatically loop from review back
into implementation.

---

# Non-negotiable architecture boundaries

## Harness-owned authority

The harness owns:

- workflow selection and stage order
- run, session, and workspace lifecycle
- retries and terminal-state decisions
- MCP authorization
- deterministic validation
- patch generation and controlled application
- check execution authorization
- credentials
- Git operations
- draft-PR creation
- evidence collection
- cleanup and recovery boundaries

Agents may analyze, plan, inspect allowed evidence, propose exact replacements,
write documentation proposals, review changes, and prepare PR text.

Agents may not mutate authoritative repository state directly, own credentials,
push branches, create or merge PRs directly, bypass checks, or grant themselves
permissions.

## Remote write and merge

Repository profiles may opt into automatic draft-PR creation after all immutable
bindings, checks, review, and plan-alignment requirements pass.

Profiles that do not opt in require an explicit operator retry or approval.

In both cases:

- Git credentials remain harness-only;
- pushes are non-force;
- draft PR creation is idempotent;
- Safeplane never merges;
- release and deployment of target repositories remain out of scope.

## Fake mode and real mode

Fake mode remains the default for unit tests, public CI, and normal acceptance.

Real OpenRouter, Telegram, GitHub, external-repository, and VPS paths remain
explicit and guarded. Public CI must require no secret and perform no real remote
write.

## Naming after cleanup

MVP numbers are planning and historical identifiers, not product concepts.

After MVP 24:

- runtime commands, Compose files, current capability documentation, fixtures,
  and tests use behavior-oriented names;
- old MVP wrappers are removed rather than retained indefinitely;
- superseded roadmap copies and implementation chronology belong under
  `docs/history/` or in Git history;
- the live roadmap is deliberately retained as `/mvp-ladder.md` at the
  repository root because it is an operator planning artifact, not a runtime or
  product capability name;
- current operator help describes the product as it exists now.

---

# Completed foundation

The following milestones are complete:

- MVP 0 — Local chat loop
- MVP 0.1 — Initial cleanup and trace polish
- MVP 1 — Secret handling and configuration boundaries
- MVP 2 — Runtime artifact lifecycle and cleanup
- MVP 3 — Session continuation
- MVP 4 — Assistant workflow as second workflow
- MVP 5 — Workflow registry and explicit workflow selection
- MVP 6 — Concurrent runs and asynchronous run manager
- MVP 7 — Telegram connector
- MVP 8 — Safe calendar data store
- MVP 9 — Harness-owned MCP foundation
- MVP 10 — Harness-owned agent runtime and assistant calendar tools
- MVP 11 — Assistant tool-call evaluations and OpenRouter resilience
- MVP 12 — Notification scheduler and real Telegram delivery
- MVP 13 — Runtime-mode clarity and assistant reliability
- MVP 14 — Read-only developer workspace and MCP inspection tools
- MVP 15 — Explicit patch approval inside the per-run workspace
- MVP 16 — Developer workflow contract, agents, models, and versioned prompts
- MVP 17 — External repositories, multi-repository workspace, and Git secrets
- MVP 18 — Complete developer MCP toolset
- MVP 19 — External `archdoc` documentation agent
- MVP 20 — Single-pass developer workflow
- MVP 21 — Branch push and draft pull request
- MVP 22 — Real external-repository developer proof and hardening
- MVP 23 — Deterministic Telegram commands for every workflow
- MVP 24 — MVP cleanup, neutral fixtures, and capability-oriented naming

The implementation artifacts, ADRs, capability tests, run evidence, and Git
history are the authoritative record for completed behavior. This ladder should
not duplicate every old implementation detail.

---

# MVP 22 — Real external-repository developer proof and hardening

Status: Complete / green

## Result

A bounded real developer run against the configured external target repository:

- prepared the target and external `archdoc` repositories;
- ran baseline documentation, analysis, planning, implementation, checks, final
  documentation, review, and PR-writing stages;
- converged through bounded implementation validation;
- passed controlled checks;
- returned `LGTM` with explicit `plan_alignment: ALIGNED`;
- created a draft pull request through the opted-in automatic publication path;
- left merge control with the operator;
- produced inspectable evidence;
- kept the Safeplane source checkout unchanged;
- was manually inspected by the operator and judged to be high quality.

The hardening completed during MVP 22 includes:

- strict adherence to the approved implementation mechanism;
- explicit review plan alignment;
- self-contained isolated check planning;
- four bounded implementation final-validation attempts;
- deterministic repair feedback for malformed patches, invalid checks, and
  physical line budgets;
- automatic draft-PR creation only for explicitly opted-in profiles;
- idempotent manual publication retry;
- evidence-bundle generation with hashes;
- protected cleanup of old inactive workspaces;
- resilient run-status polling;
- ADR catch-up for the developer workflow boundaries;
- capability-oriented acceptance aliases.

Accepted validation state at milestone completion:

```text
292 unit tests
full fake-mode hardening acceptance green
one successful real external-repository run
one inspected draft pull request
no automatic merge
```

## Deferred findings from the real run

The real run showed that documentation stages are the dominant model-token and
cost consumers. That may be optimized after public release unless VPS operation
shows it to be a practical blocker.

---

# Repository inspection findings driving the next milestones

The repository archive inspected on 2026-07-21 is functionally substantial but
not yet suitable for public presentation or VPS deployment without cleanup.

These findings define the active roadmap.

## Product and documentation drift

- `README.md` still presents MVP 0 as the current product and describes several
  implemented capabilities as missing.
- The README is long, internally chronological, and not optimized for a new
  visitor or job interviewer.
- Current architecture is spread across many incremental documents instead of a
  short public entry point.
- Telegram help still identifies itself as an old MVP rather than the current
  connector.
- Several documents describe superseded limitations as if they were current.

## MVP scaffolding in the product surface

The repository contains milestone-named:

- Compose overlays;
- validation and runtime scripts;
- acceptance tests;
- fixtures;
- documentation paths;
- case-study tooling;
- help text and status messages.

Some of this contains valuable evidence. It must be converted into current
artifacts rather than deleted blindly:

```text
architectural decision -> ADR
supported operator behavior -> current operations documentation
capability proof -> capability-oriented acceptance test
historical result -> Git history, release note, or sanitized case study
obsolete implementation note -> delete
```

## Generated and platform-specific files

The supplied archive contains:

- Python `__pycache__` directories;
- compiled `.pyc` files;
- a macOS `__MACOSX` directory and AppleDouble metadata.

No repository-level `.gitignore` was present in the supplied archive.

## Public repository baseline files

The supplied archive did not contain:

- a license;
- `CONTRIBUTING.md`;
- `SECURITY.md` at repository root;
- public CI configuration;
- a dependency lock or constraints strategy.

These are release-candidate requirements, not optional polish.

## Prompt and fixture neutrality

The inspected production developer system prompts do not contain `Silver` or
`DailyDash`.

However, at least one fake model-response fixture contains the Silver task, and
DailyDash-specific assumptions remain in case-study tooling, examples, tests,
and guarded real-run scripts.

Before public release:

- no production prompt or fake prompt-response fixture may contain `Silver` or
  `DailyDash`;
- generic acceptance must use neutral fixture repositories and tasks;
- a sanitized external-repository case study may name DailyDash only when this
  is deliberate, legally acceptable, and contains no private source content;
- real repository configuration must remain operator-owned.

## Secret-mount boundary mismatch

The base Compose configuration mounts the complete `SAFEPLANE_HOME` into
multiple services. That directory also contains secret files.

This means a service may be able to read secrets that were not declared as its
Docker secret, even when documentation says otherwise.

This is a release and deployment blocker.

The runtime storage layout and mounts must be split so every service receives
only the exact state and secrets it requires.

## Container and network hardening gaps

- Most long-running services currently run as root; the developer MCP container
  is the notable hardened exception.
- Most services do not yet have a read-only root filesystem, dropped
  capabilities, or `no-new-privileges` policy.
- The base network is comparatively flat outside the developer-tool boundary.
- The local harness port is published without an explicit loopback host binding.
- No production VPS Compose profile, production health policy, resource budget,
  log rotation, backup procedure, or rollback procedure exists yet.

## Reproducibility and maintenance gaps

- Python base versions are mixed.
- most dependency declarations use broad lower bounds rather than a reproducible
  lock or constraints file;
- there is no public dependency and license inventory;
- the supplied source archive has no `.git` metadata, so Git history, milestone
  tag, and historical secret auditing must be performed in the real repository,
  not inferred from this archive.

---

# Release gates

## Gate A — Connector completeness

Status: Complete through MVP 23.

Every enabled operator-facing workflow can be started deterministically through
Telegram and CLI without an LLM router.

Required milestone: MVP 23.

## Gate B — Repository clarity

Status: Complete through MVP 24.

MVP scaffolding, generated junk, target-task overfitting, and stale product text
are removed from the current product surface.

Required milestone: MVP 24.

## Gate C — Security claims match runtime reality

Status: Next active gate.

Secret visibility, mounts, network access, users, ports, and container policies
are enforced and tested rather than merely documented.

Required milestone: MVP 25.

## Gate D — A new visitor can understand the system

The README and current documentation explain architecture, containers,
developer-agent data flow, operation, limitations, and quickstart accurately.

Required milestone: MVP 26.

## Gate E — Reproducible deployment exists

A clean supported Linux host can be prepared and can deploy Safeplane from the
private repository using documented, deterministic steps.

Required milestone: MVP 27.

## Gate F — Real private operation is proven

The actual VPS survives reboot, update, rollback, persistence, backup/restore,
notifications, and a real developer workflow during a private soak period.

Required milestone: MVP 28.

## Gate G — Public release candidate is clean

Tracked files, Git history, documentation, dependencies, prompts, CI, examples,
and clean-clone behavior pass the release audit.

Required milestone: MVP 29.

Only then may MVP 30 make the repository public.

---

# MVP 23 — Deterministic Telegram commands for every workflow

Status: Complete / accepted

## Goal

Make Telegram a complete deterministic operator connector.

Every enabled operator-facing workflow must have a documented Telegram command
that starts it without natural-language routing.

The developer workflow must be startable from Telegram using an explicit
repository profile and task.

## Scope

Add a registry-backed command surface, conceptually:

```text
/workflows
/run <entrypoint> <arguments>
```

The exact syntax may differ, but it must support at least:

```text
/run chat <message>
/run assistant <message>
/run develop --repo <repository-profile> <task>
```

Existing convenient aliases may remain when they are thin deterministic
translations:

```text
/develop <repository-profile> <task>
/approve_pr <run-id>
/status [run-id]
```

Requirements:

- `/workflows` is derived from the harness workflow registry;
- connector exposure is explicit in workflow metadata;
- disabled or internal-only workflows are not accidentally exposed;
- unknown entrypoints fail clearly;
- workflow-specific arguments are validated deterministically;
- Telegram does not decide stage order or permissions;
- plain text may continue to map to one configured default workflow, but that
  behavior must be explicit and documented;
- developer progress, terminal status, and draft-PR URL remain visible;
- remote-write approval remains a separate command and policy boundary;
- no LLM classifier or confidence score is introduced.

## Implementation direction

Prefer one shared harness request contract over adding unrelated Telegram HTTP
paths for every future workflow.

Workflow metadata should describe at least:

- whether the workflow is connector-exposed;
- its command name or entrypoint;
- required structured arguments;
- usage text;
- whether session continuation is supported.

The Telegram connector should parse commands and forward validated intent. The
harness remains the source of truth.

## Acceptance criteria

MVP 23 is accepted when:

- Telegram can list all enabled operator-facing workflows;
- each listed workflow has a deterministic start command;
- chat and assistant can be started explicitly;
- developer can be started with repository profile and task;
- unknown, disabled, and malformed commands are rejected clearly;
- command parsing does not call a model;
- connector tests use a fake Telegram boundary and fake harness responses;
- one real Telegram smoke starts the developer workflow and receives progress;
- `/approve_pr` or its replacement remains explicit and idempotent;
- CLI behavior remains green;
- the complete fake-mode developer acceptance remains green.

## Acceptance result

MVP 23 is complete by operator acceptance.

The accepted implementation and validation verified:

- registry-backed Telegram exposure for `assistant`, `chat`, and `develop`;
- `/workflows` lists enabled connector-facing workflows;
- `/help` prints the complete Telegram command reference;
- direct `/assistant`, `/chat`, and `/develop` commands are available;
- generic `/run` remains an advanced deterministic dispatcher;
- unknown, disabled, and malformed commands fail clearly without model routing;
- the harness independently rejects non-exposed Telegram entrypoints;
- chat and assistant retain separate Telegram session mappings;
- command-processing failures are reported to the authorized Telegram user;
- fake-boundary connector acceptance passes;
- the complete unit suite passes with 304 tests;
- a real Telegram primary smoke passed for `/help`, `/assistant`, and `/chat`
  without developer services;
- the real developer-start smoke was deliberately deferred by the operator.

The deferred `/develop` real smoke remains available as a secondary diagnostic.
Its absence is recorded explicitly and is not represented as passed. The
developer workflow itself was already proven end to end in MVP 22, while MVP 23
acceptance focuses on the deterministic Telegram connector surface.

## Out of scope

MVP 23 does not include:

- natural-language routing;
- fuzzy workflow selection;
- LLM classification;
- Slack, email, or web connectors;
- automatic approval or merge.

---

# MVP 24 — MVP cleanup, neutral fixtures, and capability-oriented naming

Status: Complete / green / accepted

## Goal

Remove development-stage scaffolding from the current product surface and make
the repository read like one coherent system.

Preserve valuable evidence by moving it into the correct implementation
artifact instead of retaining milestone-specific wrappers and documents.

## Scope

### Inventory and classification

Create a deterministic inventory of every tracked path and text occurrence that
contains:

```text
mvp
MVP
DailyDash
Silver
```

Classify each occurrence as:

- current product behavior;
- architecture history;
- capability acceptance;
- sanitized case-study evidence;
- operator-owned configuration example;
- obsolete scaffolding;
- overfitted fixture or prompt content.

### Replace MVP-named runtime and test surfaces

Rename or remove milestone-oriented items such as:

- `docker-compose.mvp*.yml`;
- `compose-mvp*` helpers;
- `validate-mvp*` wrappers;
- `test_mvp*` acceptance modules;
- smoke output that announces an MVP number;
- operator help that identifies a connector by an old milestone.

Use capability-oriented names such as:

```text
compose-safeplane-github-mock
accept-developer-workflow
accept-draft-pr-workflow
accept-external-repository
accept-telegram-notifications
accept-publication-path
```

Do not retain compatibility wrappers unless an external consumer actually
requires them. This is a pre-public project, so unnecessary compatibility debt
should be removed now.

### Consolidate documentation

For every milestone-specific document:

- move lasting architecture rationale into an ADR;
- move current commands into operations documentation;
- move proof into an acceptance test or sanitized case study;
- remove obsolete setup notes;
- update or retire ADRs whose current text describes superseded behavior;
- archive superseded ladder versions under `docs/history/` while keeping this
  single live roadmap as `/mvp-ladder.md` in the repository root.

After cleanup, MVP terminology should remain only in deliberate history and in
this explicit root-level planning roadmap.

### Remove generated junk

Remove:

- `__pycache__`;
- `.pyc` and `.pyo` files;
- `.DS_Store`;
- `__MACOSX` and AppleDouble metadata;
- temporary archives and patches;
- runtime state and evidence bundles not intended as sanitized examples.

Add a repository-level `.gitignore` that covers local secrets, runtime data,
Python caches, editor files, Compose overrides, test output, evidence output,
and temporary repositories.

### Remove prompt and fixture overfitting

All files under `prompts/`, including fake model-response fixtures, must be free
of:

```text
Silver
DailyDash
```

Replace the real-task wording with neutral fixture behavior that tests the same
mechanism, for example removing a generic configured item while preserving the
rest.

Generic workflow tests must not rely on target-specific labels as behavioral
switches.

Generalize case-study generation so it can sanitize any completed external
repository run. A DailyDash case study may be one output, not a hard-coded
product assumption.

### Normalize examples

Replace the committed example repository profile with a neutral example name and
placeholder owner/repository.

Keep the real repository profile in operator-owned runtime configuration only.

## Deterministic checks

Add checks that fail when:

- generated junk is tracked;
- current product paths use forbidden MVP naming outside the explicit
  `/mvp-ladder.md` and `docs/history/` planning/history allowlist;
- prompts or fake model outputs contain `Silver` or `DailyDash`;
- private repository identifiers appear outside an explicit sanitized allowlist;
- obsolete compatibility wrappers are reintroduced.

## Acceptance criteria

MVP 24 is accepted when:

- all tracked MVP occurrences have been reviewed and classified;
- current runtime, Compose, CLI, help, and capability-test names are
  behavior-oriented;
- obsolete MVP wrappers are deleted;
- lasting decisions are represented by current ADRs;
- current commands are represented by current operations documentation;
- proof is represented by capability acceptance;
- prompts and fake model-response fixtures contain neither `Silver` nor
  `DailyDash`;
- generic tests use neutral repository and task fixtures;
- case-study tooling is repository-agnostic;
- no Python cache or macOS archive metadata is tracked;
- `.gitignore` protects all known local and runtime artifacts;
- the live roadmap exists as `/mvp-ladder.md` and superseded roadmap copies are
  confined to deliberate history;
- all references and executable bits remain correct after renames;
- unit and capability acceptance remain green.

## Acceptance result

MVP 24 is complete by operator acceptance.

The accepted implementation:

- replaced milestone-oriented runtime, Compose, validation, fixture, and current
  documentation names with capability-oriented names;
- removed obsolete milestone wrappers instead of retaining compatibility debt;
- removed tracked Python caches, compiled bytecode, macOS archive metadata, and
  other generated artifacts from the repository surface;
- added a repository-level `.gitignore`, an idempotent hygiene normalizer, and a
  deterministic repository-hygiene acceptance check;
- replaced target-specific fake repositories, prompts, examples, and behavior
  switches with neutral fixtures;
- generalized external-repository case-study and real-run tooling;
- replaced the obsolete early-project README with a concise current-state entry
  point;
- repaired neutral fake repositories so every file declared by the default fake
  developer plan exists;
- repaired developer-tool acceptance so it verifies the exact deliberate dirty
  Git status produced by the fake workflow instead of incorrectly expecting a
  pristine workspace;
- retained `/mvp-ladder.md` as the single live planning roadmap while keeping
  superseded planning records under `docs/history/`;
- kept current runtime commands, tests, fixtures, and capability documentation
  free of milestone-oriented product naming;
- kept prompts and fake model responses free of `Silver` and `DailyDash`.

The final validation matrix ran from the active repository virtual environment
with `set -euo pipefail` and completed successfully. Accepted evidence:

```text
307 unit tests passed
32 repository-cleanup tests passed
27 notification tests passed
Telegram fake-boundary acceptance passed
repository hygiene passed
git diff --check passed
notification stack acceptance passed
developer workspace acceptance passed
patch approval acceptance passed
developer workflow contract acceptance passed
repository workspace preparation acceptance passed
developer MCP toolset acceptance passed
external documentation acceptance passed
single-pass developer workflow acceptance passed
draft-PR publication acceptance passed
OK: complete MVP 24 validation matrix passed
```

The Compose warning about an already-running orphan Telegram connector was
non-fatal and did not affect any acceptance result. Historical notification
records printed during the tests came from operator runtime data, not tracked
repository fixtures, and therefore were not repository-hygiene failures.

MVP 24 closes Release Gate B. The next deployment-blocking work is MVP 25.

## Out of scope

MVP 24 does not yet perform the complete public Git-history audit or select the
final license. Those belong to MVP 29.

---

# MVP 25 — Secret, mount, network, and container hardening

Status: Planned / deployment blocker

## Goal

Make Safeplane's security claims true at the Docker mount, process, and network
levels before it is placed on a VPS.

No service should be able to read a secret merely because it shares the same
runtime root.

## Scope

### Split runtime storage from secrets

Define an explicit host and container data layout, conceptually:

```text
runtime/
  sessions/
  runs/
  traces/
  workspaces/
  artifacts/
  calendar/
  notifications/
  evidence/
config/
secrets/
backups/
```

A service receives only the directories it needs.

Requirements:

- secret files are not located beneath a directory broadly mounted into
  services;
- OpenRouter credentials are mounted only into model-gateway;
- GitHub credentials are mounted only into harness;
- Telegram bot token and allowed-user configuration are mounted only into the
  Telegram connector;
- check and MCP containers receive no secret directory;
- calendar, notification, and scheduler services cannot read provider, GitHub,
  or Telegram secrets;
- model-gateway cannot read GitHub or Telegram secrets;
- Telegram cannot read GitHub or OpenRouter secrets;
- mounts are read-only unless the service must write that exact data.

### Harden service processes

For every long-running service, apply where technically possible:

- a dedicated non-root user;
- read-only root filesystem;
- `no-new-privileges`;
- dropped Linux capabilities;
- bounded writable `tmpfs`;
- explicit writable data mounts;
- health checks;
- graceful shutdown behavior;
- bounded CPU, memory, and process count for the VPS profile.

Exceptions must be documented with evidence and a narrower compensating
control.

### Segment networks

Design explicit networks for the required communication paths.

The intended direction is:

```text
Telegram connector -> harness
harness -> model-gateway
harness -> MCP services
notification MCP -> scheduler
scheduler -> Telegram connector
harness -> GitHub and Git remotes
model-gateway -> OpenRouter
check container -> no network by default
```

Services must not gain unrelated reachability simply because they share the
Compose project.

### Remove accidental public exposure

- local development ports bind to `127.0.0.1`, not all host interfaces;
- the production VPS profile publishes no Safeplane application port;
- Telegram uses long polling;
- internal health and MCP endpoints remain Docker-internal;
- SSH and explicitly chosen host administration remain the only expected inbound
  paths for the first VPS deployment.

### Verify redaction and API output

Ensure status, health, logs, traces, errors, evidence, and Compose diagnostics do
not reveal:

- secret values;
- authenticated repository URLs;
- local absolute secret paths when not necessary;
- Telegram user identifiers in public evidence;
- raw private repository content in public evidence.

## Required security tests

Add deterministic tests that inspect rendered Compose configuration and running
containers.

Tests must prove both positive and negative access, including:

- intended service can read its mounted secret;
- every unintended service cannot see the path or value;
- no secret exists in environment variables;
- no secret exists in image layers or Git configuration;
- no service mounts the entire secret parent directory;
- only expected host ports are published;
- check execution has no network and no inherited secret;
- non-root and hardening flags are active.

## Acceptance criteria

MVP 25 is accepted when:

- the broad `SAFEPLANE_HOME` secret exposure is eliminated;
- a documented service-to-data mount matrix matches rendered Compose output;
- a documented service-to-secret matrix matches running-container evidence;
- all long-running services run non-root or have a documented justified
  exception;
- internal services are not exposed on the host;
- local host bindings are loopback-only;
- production publishes no application port;
- networks enforce only required communication paths;
- check execution remains networkless and secretless;
- health endpoints expose no sensitive state;
- secret scanning of traces and evidence passes;
- existing developer, assistant, calendar, notification, and remote-write
  acceptance remains green.

## Out of scope

MVP 25 does not include:

- Vault or enterprise secret management;
- multi-tenant isolation;
- Kubernetes network policies;
- a public HTTP API.

---

# MVP 26 — Public-facing documentation and operator experience

Status: Planned

## Goal

Make the private repository understandable enough that the README and current
architecture can later be published with minimal change.

Keep the README short and high-signal. Move detail into focused current-state
documents.

## README

Rewrite `README.md` for a new visitor.

It should contain:

1. one-paragraph description of Safeplane;
2. current project status;
3. a compact architecture diagram;
4. the strongest architecture highlights;
5. a five-minute fake-mode quickstart;
6. one developer-workflow example using a neutral fixture;
7. how to inspect run status and evidence;
8. how local, real-provider, Telegram, GitHub, and VPS modes differ;
9. security boundaries and human merge control;
10. explicit known limitations;
11. links to focused documentation.

Architecture highlights should include:

- connectors remain thin;
- harness-owned orchestration and authority;
- Pydantic-validated inputs and artifacts;
- versioned workflow and prompt contracts;
- model-gateway isolation;
- harness-brokered MCP permissions;
- container separation and network boundaries;
- file-secret scoping;
- per-run repository isolation;
- exact replacement proposals and harness-generated patches;
- controlled checks;
- independent review and plan alignment;
- evidence bundles;
- harness-only Git credentials;
- optional automatic draft PR for explicitly opted-in profiles;
- human-only merge.

The README must not narrate MVP history or claim implemented features are
missing.

## Container interaction document

Add a concise current-state document explaining how containers work together.

It should show:

- each service;
- which service calls which;
- network membership;
- writable mounts;
- read-only mounts;
- secret mounts;
- external egress;
- why agents and MCP services do not receive credentials;
- why the harness is the authority boundary.

Prefer a small Mermaid diagram plus one service matrix.

## Developer workflow document

Add a focused document explaining the complete developer workflow and artifact
flow.

It must identify each agent and exactly what it receives and produces:

### Documentation agent — baseline

Reads:

- target repository evidence;
- external `archdoc` source at the resolved commit;
- existing target documentation.

Produces:

- validated documentation replacements;
- baseline documentation result;
- target documentation consumed by later agents.

### Analysis agent

Reads:

- operator request;
- repository context;
- target documentation.

Produces:

- requirements;
- architecture impact;
- granular tasks;
- assumptions and risks.

### Planning agent

Reads:

- request;
- analysis artifacts;
- repository documentation and evidence.

Produces:

- exact file plan;
- expected change mechanism per file;
- size and operation budgets;
- isolated check plan;
- documentation impact;
- proposed commit message.

### Implementation agent

Reads:

- approved plan;
- allowed repository evidence;
- deterministic repair feedback when required.

Produces:

- exact old/new file replacements within the plan.

The harness validates the candidate, generates the patch, runs candidate checks,
and applies the accepted result through the controlled write boundary.

### Documentation agent — final reconciliation

Reads:

- final changed repository;
- check evidence;
- the same resolved `archdoc` commit.

Produces:

- final documentation replacements or a validated no-change result.

### Review agent

Reads:

- request;
- requirements;
- plan;
- final diff;
- checks;
- documentation result.

Produces:

- `LGTM` or `REQUEST_CHANGES`;
- `ALIGNED` or `DEVIATION` plan alignment;
- findings and residual risks.

### PR agent

Reads only validated run artifacts needed to prepare public-facing PR text.

Produces:

- title;
- body;
- checks, risks, documentation, and human-review summary.

The document must clearly distinguish agent-authored proposals from
harness-owned authoritative actions.

## Current operations documentation

Consolidate current operator documentation for:

- installation and local setup;
- runtime modes;
- Telegram commands;
- developer runs;
- status and evidence;
- calendar and notifications;
- secrets;
- cleanup;
- backup and restore interface;
- draft-PR behavior;
- troubleshooting.

## Documentation drift checks

Add lightweight tests that verify:

- documented commands exist;
- workflow and agent names match the workflow contract;
- prompt versions referenced in docs exist;
- service names match Compose;
- no stale MVP status appears in current docs;
- README links resolve.

## Acceptance criteria

MVP 26 is accepted when:

- README is concise, accurate, and useful to a first-time visitor;
- architecture highlights reflect actual enforced behavior;
- container interaction is explained in one diagram and one matrix;
- the developer workflow document maps every agent to its input and output
  artifacts;
- current operations documentation replaces milestone setup notes;
- commands in README work from a clean clone in fake mode;
- current docs contain no stale statements that implemented capabilities are
  missing;
- known limitations are explicit;
- documentation drift tests pass;
- all capability acceptance remains green.

## Out of scope

MVP 26 does not yet claim VPS deployment success. Deployment sections describe
the package being built next and must be reconciled with real evidence in MVP
29.

---

# MVP 27 — Reproducible VPS deployment package

Status: Planned / must remain private

## Goal

Create a production-oriented deployment package that can bring up Safeplane on
a clean supported Linux VPS without exposing application ports or relying on
undocumented local state.

This milestone prepares and validates the deployment mechanics. MVP 28 performs
the real deployment and soak.

## Supported deployment target

Choose and document one primary target, for example:

```text
Ubuntu or Debian VPS
Docker Engine
Docker Compose plugin
single non-root operator
single Safeplane instance
Telegram long polling
```

Do not attempt to support every Linux distribution before release.

## Host layout

Define an explicit host layout, conceptually:

```text
/srv/safeplane/
  app/
  runtime/
  config/
  secrets/
  backups/
  logs/
```

Requirements:

- repository checkout and runtime state are separate;
- secret directories use restrictive ownership and modes;
- backups do not include unnecessary caches or target repository credentials in
  plaintext archives;
- update and rollback do not overwrite runtime state;
- the deployment user does not require routine root login.

## Production Compose profile

Add a production Compose file or deployment wrapper with:

- only required services;
- no public application ports;
- restart policies;
- health checks;
- service dependencies based on health where useful;
- non-root and read-only policies from MVP 25;
- persistent data mounts;
- bounded resource limits appropriate for a small VPS;
- log rotation;
- explicit networks;
- explicit outbound dependencies;
- no development fixtures or GitHub mock;
- no host Docker socket in any container.

## Bootstrap and configuration

Provide deterministic commands or scripts for:

- host prerequisite checks;
- creating the deployment user and directories;
- installing or verifying Docker and Compose;
- cloning or updating the private repository;
- creating example configuration from placeholders;
- provisioning OpenRouter, Telegram, and GitHub file secrets without printing
  them;
- configuring repository profiles outside Git;
- validating rendered Compose configuration;
- starting, stopping, restarting, and inspecting the stack;
- checking active mode without exposing secret values.

Avoid an opaque all-powerful install script. Each privileged action must be
small, inspectable, and documented.

## VPS security guidance

Document and test where possible:

- SSH key authentication;
- disabled password login where appropriate;
- firewall allowing only SSH and explicitly required administration;
- automatic security updates or a documented patch cadence;
- time synchronization;
- disk-space monitoring;
- outbound destinations required by Telegram, OpenRouter, GitHub, and Git;
- no inbound Safeplane HTTP endpoint;
- backup permissions and retention.

## Persistence and recovery package

Provide:

- backup command;
- backup manifest and hashes;
- restore command or deterministic procedure;
- update procedure;
- rollback procedure;
- runtime cleanup procedure;
- evidence preservation procedure;
- documented behavior for runs interrupted by restart.

## Pre-deployment validation

Validate the package on a clean Linux VM or equivalent environment before using
the real VPS.

The validation must prove:

- bootstrap has no hidden dependency on the developer machine;
- Compose renders without secrets being printed;
- services become healthy;
- no application port is public;
- fake-mode assistant and developer fixture work;
- runtime state survives stack restart;
- backup and restore work in the clean environment.

## Acceptance criteria

MVP 27 is accepted when:

- one supported Linux target is explicit;
- a clean host can be prepared using documented steps;
- production Compose passes policy checks;
- no application port is exposed;
- all services become healthy;
- secrets are scoped according to the MVP 25 matrix;
- runtime data is persistent and separate from the checkout;
- resource and log limits are defined;
- fake Telegram, assistant, notification, and developer smokes pass in the
  deployment profile;
- backup creation and restore are tested;
- update and rollback procedures are executable and documented;
- the package is ready for a real private VPS deployment.

## Out of scope

MVP 27 does not include:

- public repository publication;
- Kubernetes;
- high availability;
- public reverse proxy;
- multi-user hosting;
- unattended target-repository deployment.

---

# MVP 28 — Private VPS deployment, recovery, and soak

Status: Planned / hard publication prerequisite

## Goal

Deploy the private Safeplane repository to a real VPS and operate it long enough
to discover defects that local and CI environments do not reveal.

No public release work may be accepted merely because deployment documentation
looks complete.

## First private bring-up

Deploy the real production profile with:

- Telegram connector;
- real model gateway;
- assistant calendar and notifications;
- developer workflow;
- external repository preparation;
- GitHub draft-PR capability;
- persistent runtime and evidence storage;
- cleanup and backup configuration.

Record sanitized deployment evidence without storing secret values or private
repository content in the Safeplane Git repository.

## Required real proofs

The VPS acceptance must prove:

1. the stack starts cleanly from the documented deployment procedure;
2. all services report healthy;
3. only intended host ports are reachable;
4. Telegram can list and start every connector-exposed workflow;
5. the assistant can read and write calendar data through MCP;
6. a scheduled Telegram notification is delivered at the expected time;
7. runtime data survives a full stack restart;
8. the stack starts after a VPS reboot;
9. an external repository can be prepared with the correct credential boundary;
10. one bounded developer task reaches an inspectable draft PR;
11. Safeplane does not merge the PR;
12. a run waiting for remote approval remains inspectable after restart;
13. evidence collection works on the VPS;
14. cleanup preserves active and approval-relevant runs;
15. a backup can be created and restored;
16. one update and one rollback drill succeed;
17. status, logs, diagnostics, and backups contain no secret values.

## Soak period

Keep the repository private during an operator-observed soak period.

Minimum evidence should include:

- at least 72 hours of normal operation;
- multiple Telegram interactions on different days;
- at least one scheduled notification crossing a restart or day boundary;
- one VPS reboot;
- one application update;
- one rollback or restore drill;
- one real external developer workflow;
- storage, memory, CPU, and log-growth observations;
- cleanup of old inactive runtime artifacts;
- no unexplained service restart loop.

A longer soak is acceptable when issues continue to emerge.

## Defect handling

Every material issue found during deployment or soak must be classified:

- security boundary defect;
- persistence or recovery defect;
- deployment reproducibility defect;
- connector or workflow defect;
- resource or performance defect;
- observability or operator-experience defect;
- documentation defect;
- non-blocking future improvement.

Release blockers must be fixed while the repository is private.

After every fix:

- run focused tests;
- run the full unit suite;
- run relevant capability acceptance;
- run `git diff --check`;
- redeploy through the documented update path;
- repeat the affected real proof;
- record sanitized evidence.

Do not weaken deterministic validation or secret boundaries to make VPS
acceptance pass.

## Acceptance criteria

MVP 28 is accepted when:

- Safeplane is running on the real VPS from the production deployment package;
- the required real proofs pass;
- restart and reboot recovery pass;
- backup and restore pass;
- update and rollback pass;
- one real developer run reaches a draft PR from the VPS;
- Telegram workflow commands and notifications work reliably;
- resource use is acceptable for the selected VPS size;
- runtime cleanup prevents uncontrolled storage growth;
- logs and evidence remain secret-free;
- the minimum soak evidence exists;
- every discovered release blocker is fixed and revalidated;
- remaining limitations are explicit and acceptable for a portfolio release.

## Out of scope

MVP 28 does not include:

- making the repository public;
- high availability;
- zero-downtime deployment;
- multi-region operation;
- 24/7 commercial service-level guarantees.

---

# MVP 29 — Public release candidate audit and clean-room verification

Status: Planned / begins only after MVP 28

## Goal

Convert the privately deployed and hardened repository into a release candidate
that is safe, reproducible, legally clear, and understandable to an anonymous
GitHub visitor.

Deployment evidence is reconciled into the documentation before release.

## Repository baseline

Add or finalize:

- `.gitignore`;
- selected open-source license;
- `CONTRIBUTING.md`;
- root `SECURITY.md`;
- code of conduct if desired;
- example configuration without secrets;
- public CI workflows;
- dependency constraints or lock strategy;
- dependency and license inventory;
- release checklist;
- changelog or release notes;
- known-limitations document.

## Git and private-data audit

Run the audit against the actual Git repository, not a source archive.

Inspect:

- all tracked files;
- all reachable Git history;
- tags and branches intended for publication;
- deleted historical files;
- large objects;
- patches and archives;
- runtime paths;
- credentials and token patterns;
- Telegram identifiers;
- email addresses and personal paths;
- private repository names and URLs;
- private source snippets;
- model transcripts and raw prompts;
- evidence bundles.

Any real secret discovered in history requires credential rotation and history
repair before publication.

## Prompt and provenance audit

Verify:

- no prompt or fake model-response fixture contains `Silver` or `DailyDash`;
- generic prompts contain no hidden target-repository assumptions;
- Conitera-derived prompts retain provenance;
- external `archdoc` content is not copied into Safeplane;
- prompt manifests reference existing versioned files;
- public examples contain placeholders only.

## Case-study audit

Publish only a sanitized case study that contains:

- a bounded task summary;
- sanitized repository identity when required;
- stage sequence;
- configured and actual model categories when appropriate;
- checks and review result;
- plan alignment;
- operator findings;
- defects and hardening outcomes;
- known limitations;
- proof that merge remained human-controlled.

It must not contain:

- private repository source;
- raw model messages;
- local runtime paths;
- credentials;
- Telegram IDs;
- private PR URL when publication is not authorized.

## Public CI

A secret-free CI workflow must verify at least:

- dependency installation;
- unit tests;
- capability-oriented fake acceptance;
- prompt manifests;
- workflow configuration;
- Compose policy and secret-mount matrices;
- no generated junk;
- prompt neutrality;
- documentation links and command references;
- no real provider call;
- no real Telegram call;
- no real GitHub write.

## Clean-room verification

On a clean machine or VM, using only the candidate repository and public
instructions:

1. clone anonymously or through a neutral test account;
2. install documented prerequisites;
3. run the five-minute fake quickstart;
4. start and inspect the local stack;
5. run a chat and assistant message;
6. run the neutral developer fixture;
7. inspect run status and evidence;
8. run the documented test command;
9. stop and clean the stack;
10. confirm no data is written inside the repository unexpectedly.

Repeat the quickstart from the exact release-candidate commit.

## Documentation reconciliation

Update README and operations documentation with facts learned from the real VPS:

- tested host OS and VPS size;
- actual startup and recovery behavior;
- resource observations;
- backup and restore behavior;
- update and rollback behavior;
- real known limitations;
- exact production port policy;
- troubleshooting discovered during soak.

Do not claim broader production readiness than the evidence supports.

## Release candidate

Create a private release-candidate commit and annotated tag only after all audit
checks pass.

The tag should identify a product version rather than an MVP number.

## Acceptance criteria

MVP 29 is accepted when:

- license, contribution, and security files exist;
- public CI passes without secrets;
- dependency and third-party license inventory is complete;
- tracked-file and full-history secret audits pass;
- no private runtime data or personal identifiers remain;
- no generated junk is tracked;
- prompts and fake fixtures are target-neutral;
- README and docs match the deployed system;
- the sanitized case study is safe to publish;
- all documented commands work from a clean clone;
- the fake quickstart works on a clean machine;
- no real external write occurs during public verification;
- a release-candidate commit and annotated version tag exist privately;
- the operator explicitly approves publication.

## Out of scope

MVP 29 does not itself change repository visibility.

---

# MVP 30 — Public portfolio release

Status: Planned / final publication step

## Goal

Publish the audited release candidate as a public GitHub portfolio repository
and verify that the public experience works as intended.

## Scope

Before changing visibility:

- verify the private release-candidate commit and tag;
- verify the final release checklist is signed off;
- verify all credentials used during development and deployment are still valid
  only where intended and were never committed;
- take a final private backup of VPS runtime and configuration;
- confirm the public repository will not expose the private VPS address or
  administration details.

After changing visibility:

- verify anonymous clone;
- verify README rendering and all links;
- verify public CI on the public repository;
- verify the tagged release or release notes;
- verify issue-reporting and security-contact instructions;
- verify example configuration contains placeholders only;
- verify repository topics and description accurately describe Safeplane;
- run the public fake quickstart from a fresh anonymous clone;
- confirm the live private VPS remains isolated and unaffected by repository
  visibility;
- confirm no public workflow can trigger operations on the private VPS.

## Portfolio presentation

Prepare a compact interview path:

1. README architecture overview;
2. container and secret-boundary diagram;
3. developer workflow and artifact flow;
4. fake-mode local demo;
5. sanitized real-run case study;
6. evidence bundle structure;
7. private VPS deployment proof without exposing private details;
8. explicit limitations and deferred roadmap.

The project should be presented as an engineered control plane with bounded AI
components, not as an autonomous coding claim.

## Acceptance criteria

MVP 30 is accepted when:

- repository visibility is public;
- anonymous clone succeeds;
- public CI passes;
- public quickstart passes from a clean clone;
- release notes and version tag are visible;
- README and documentation render correctly;
- no secret, private source, personal identifier, or private VPS detail is
  exposed;
- the private VPS continues operating with no new inbound exposure;
- the portfolio demonstration path is concise and reproducible;
- known limitations and human control boundaries remain prominent.

---

# Deferred roadmap

The following work is deliberately postponed until after the public portfolio
release unless real VPS evidence promotes a specific item into the active path.

## Automatic developer rework loops

A future workflow may use a bounded:

```text
review
-> rework
-> checks
-> review
```

loop. The current workflow stops on `REQUEST_CHANGES` and requires a new
operator-started run. No unbounded autonomous repair loop is planned.

## Safeplane develops Safeplane

Dogfooding Safeplane against its own repository remains a possible future proof.
It is deliberately postponed because the external-repository run already proves
the core developer workflow without creating recursive authority and recovery
risks during the publication path.

## Deterministic advisor or LLM-assisted routing

Explicit CLI and Telegram workflow commands are sufficient for the first public
release. A deterministic advisor or LLM classifier should be introduced only
after mature workflows create a measured selection problem. The deterministic
router remains authoritative; any future model output would be advice, not the
final routing decision.

## Persistent notes or semantic memory

Embeddings, vector search, automatic note retrieval, and project knowledge-base
features are deferred until a concrete workflow requires them. Developer
artifacts, repository documentation, Git history, evidence, calendar data, and
pull requests provide more immediate value.

## Web UI

CLI, Telegram, evidence bundles, and GitHub draft pull requests are sufficient
for the first release. A web UI should be driven by an operator need rather than
added as portfolio decoration.

## Additional connectors

Slack, email, and other connectors remain optional. Each future connector must
remain thin, use deterministic workflow selection, and preserve harness-owned
orchestration and authorization.

## External calendar integration

The local safe calendar remains authoritative for the first release. Later
options may include:

- Google Calendar synchronization;
- CalDAV synchronization;
- ICS import and export;
- a read-only external-calendar mirror;
- approved external calendar writes.

External writes must retain explicit permission and approval boundaries.

## Broader GitHub integration through a narrow boundary

The current system supports harness-owned branch push and draft pull-request
creation. Later GitHub capabilities may include:

- reading and creating issues;
- commenting on pull requests;
- inspecting CI results;
- responding to review metadata.

These should use a narrow GitHub integration or MCP boundary with scoped
credentials. They must not move merge authority into an agent.

## GitHub App authentication

A GitHub App may later replace or complement the fine-grained token. The
credential abstraction should preserve that migration path.

## Broader cancellation

Command timeout and process termination already protect bounded execution. Full
user-driven cancellation propagation across every stage, tool, remote write,
and connector may be added after real use demonstrates its value.

## Browser automation

Browser inspection, form interaction, screenshots, and local application testing
are deferred until a concrete developer or testing workflow requires them. They
must cross a constrained tool boundary and must not grant general host-browser
control.

## Automatic merge, release, or target deployment

Safeplane deliberately stops at a draft pull request for the first public
release. Automatic merge, automatic release, and automatic deployment of target
repositories remain out of scope until separate policies, approvals, rollback,
and production ownership are designed.

## Documentation-stage cost optimization

The real external-repository run showed that baseline and final documentation
stages dominate token use and model cost. Optimization is postponed unless VPS
operation makes it a practical blocker. Any later optimization must preserve
resolved-skill provenance, documentation quality, and deterministic artifacts.

## Multi-user and hosted service

The first public release remains a single-operator, self-hosted system. User
accounts, per-user sessions and storage, tenant isolation, hosted SaaS, billing,
and public service operation are deferred.

## Kubernetes, autoscaling, and high availability

The active deployment target is one small VPS and one Safeplane instance.
Kubernetes, autoscaling, multi-region operation, zero-downtime deployment, and
high availability are deliberately postponed until there is evidence that the
single-instance model is insufficient.

---

# Recommended immediate next step

Close MVP 24 as an independent clean baseline, then begin MVP 25:

1. inspect `git status --short`, `git diff --stat`, and `git diff --check`;
2. commit the complete cleanup and root roadmap restoration;
3. create and push the independent `mvp-24` milestone tag;
4. inventory every service mount, writable directory, secret path, published
   port, network, user, capability, and external egress path;
5. render the current Compose configuration and build explicit
   service-to-data, service-to-secret, and service-to-network matrices;
6. design the split between runtime data, configuration, secrets, and backups
   before changing individual mounts;
7. add negative security tests proving that unintended services cannot see
   secret paths or values;
8. harden one service boundary at a time while keeping the complete capability
   acceptance matrix green.

Do not combine MVP 25 with the documentation rewrite or VPS deployment package.
Security claims must first match actual mounts, processes, ports, and networks.