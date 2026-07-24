# Backlog

This document is the single planning document for work that is intentionally not
yet part of the current Safeplane capability set. It replaces the earlier split
planning structure with one maintained backlog.

An item belongs in current operator documentation only after its implementation,
validation, and evidence are accepted.

## Backlog principles

Future work should be promoted because it solves an observed operator,
reliability, security, or maintenance problem, not because it makes the system
look more autonomous.

A candidate improvement should have:

- a concrete use case or failure observed in real operation;
- a narrow design that preserves deterministic harness authority;
- explicit inputs, outputs, permissions, and terminal states;
- focused regression tests and capability acceptance;
- an evidence and rollback plan for operational changes;
- documentation that distinguishes implemented behavior from intent.

Prefer the smallest change that resolves the demonstrated problem. New
abstractions, compatibility surfaces, and autonomous loops require evidence
that the existing design is insufficient.

## Current priorities

These items are the closest planned work for strengthening the repository,
hardening the existing deployments, and completing the public operating story.

### Repeatable deployment and operator packaging

Safeplane is already deployed and running on a MacBook and on a VPS. The next
step is to make that deployment story more repeatable and easier to hand off,
with:

- an explicit host layout separating checkout, runtime state, configuration,
  secrets, backups, and logs;
- production-oriented Compose configuration with no public Safeplane
  application port;
- deterministic prerequisite, bootstrap, configuration, start, stop, update,
  rollback, and diagnostic procedures;
- service-scoped file secrets and the existing non-root, read-only, capability,
  resource, health, and network policies;
- persistent runtime mounts, bounded logs, backups, and restore procedures;
- clean-host validation using fake workflows before real provider access.

The package should remain inspectable rather than becoming one opaque privileged
installer.

### Operational soak and recovery evidence

Continue gathering evidence from the active MacBook and VPS deployments for:

- healthy startup, stack restart, and host reboot recovery;
- persistent calendar, notification, run, approval, and evidence state;
- scheduled Telegram delivery across time and restart boundaries;
- one bounded external developer run reaching an inspectable draft pull
  request;
- backup creation, restore, application update, and rollback;
- resource use, storage growth, log growth, and cleanup behavior;
- absence of secret values and private source content in diagnostics and
  evidence.

Material defects found during operation should be repaired and revalidated while
the repository remains private.

### Public-release audit and clean-room verification

Before publication, complete a repository and operator-experience audit
covering:

- licensing, contribution, security, dependency, and release files;
- tracked files and reachable Git history for secrets, private identifiers, and
  private source material;
- target-neutral prompts, fixtures, examples, and case-study evidence;
- secret-free public validation and CI;
- anonymous clean-clone setup, fake quickstart, evidence inspection, and
  cleanup;
- reconciliation of documentation with facts learned during real VPS operation.

Repository visibility should change only after the audited release candidate and
its public instructions pass clean-room verification.

## Deferred candidates

The following ideas are deliberately deferred. Their order should be driven by
measured operator value and evidence from real use.

| Candidate | Potential value | Required guardrails before promotion |
| --- | --- | --- |
| Bounded developer rework loop | Allows one run to react to review findings instead of requiring a new run | Strict attempt limit, unchanged approved scope, repeated checks and independent review, explicit terminal states, no self-granted permissions |
| Safeplane developing Safeplane | Exercises the developer workflow against its own codebase | Strong recovery path, isolated authority, no recursive credential access, operator-controlled publication, external-repository behavior already stable |
| Deterministic routing advisor | Helps choose among a larger set of explicit workflows | Router remains authoritative, model output is advisory and schema-validated, ambiguity fails safely, decisions are inspectable and testable |
| Persistent notes or semantic memory | Reuses durable project knowledge across sessions | Explicit provenance, bounded retrieval, deletion and correction controls, no silent authority over current repository facts |
| Web operator interface | Improves run, evidence, and approval inspection | Authentication and single-operator threat model, no bypass of harness policy, no new public port without a deployment decision |
| Additional connectors | Adds Slack, email, or other operator channels | Thin deterministic translation, explicit workflow exposure, connector-specific secret isolation, no connector-owned orchestration |
| External calendar integration | Synchronizes the local calendar with Google Calendar, CalDAV, or ICS | Local authority and conflict policy defined, read and write permissions separated, external writes explicitly approved and auditable |
| Broader GitHub integration | Supports issues, PR comments, or CI-result inspection | Narrow API boundary, scoped credentials, harness-owned operations, no merge authority in agents |
| GitHub App authentication | Replaces or complements a fine-grained token | Existing credential abstraction retained, installation scope minimized, migration and revocation tested |
| End-to-end cancellation | Lets the operator stop active work across stages and tools | Deterministic cancellation propagation, process termination, remote-write exclusion, consistent terminal evidence |
| Browser automation | Enables constrained UI inspection or testing | Dedicated isolated tool boundary, explicit target allowlist, no general host-browser control, evidence and timeout limits |
| Documentation-stage cost optimization | Reduces model tokens used by baseline and final documentation stages | Preserve resolved source provenance, artifact quality, deterministic contracts, and final documentation reconciliation |
| Multi-user or hosted operation | Supports multiple operators or a managed service | Authentication, authorization, tenant isolation, quotas, auditability, secret ownership, data retention, and threat model |
| Orchestration scaling | Adds Kubernetes, autoscaling, high availability, or multi-region operation | Demonstrated single-instance limitation, compatible persistence and recovery design, materially justified operational complexity |

### Automatic merge, release, or target deployment

These are not normal extensions of draft-PR creation. Each would transfer a
new kind of authority and therefore requires a separate policy design, approval
model, rollback strategy, production ownership model, and acceptance evidence.
Human merge control remains the current invariant.

## Architecture invariants

Future work should preserve these boundaries unless a deliberate architecture
decision replaces them with stronger controls:

```text
connector translates operator input
-> deterministic workflow selection
-> harness-owned lifecycle and authorization
-> bounded agent proposals and MCP calls
-> harness-owned validation and authoritative action
-> inspectable evidence
-> human decision for merge and production consequences
```

In particular:

- connectors remain thin;
- agents do not choose workflow stages or grant permissions;
- agents and MCP services do not receive Git or provider credentials they do
  not require;
- authoritative repository writes, checks, Git operations, and remote writes
  remain harness-owned;
- failed checks, review rejection, plan deviation, or changed immutable
  bindings cannot be overridden by an agent;
- evidence remains sanitized, inspectable, and tied to the executed contracts;
- deployment claims require real deployment evidence.

## Promoting an item into active work

Before implementation begins:

1. record the observed problem or operator need;
2. define the smallest capability that addresses it;
3. identify affected authority, secret, network, persistence, and recovery
   boundaries;
4. define deterministic acceptance and negative tests;
5. add it to this backlog with explicit in-scope and out-of-scope behavior;
6. implement it in narrow, reviewable changes;
7. update current documentation only after acceptance evidence exists.