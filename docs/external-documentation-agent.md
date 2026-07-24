# External archdoc documentation agent

Status: external documentation workflow implementation slice

external documentation workflow connects the developer workflow's documentation agent to the live
external `archdoc` skill prepared for the run. Safeplane does not copy or vendor
the skill. Each run records and uses one resolved `ai-craftkit` commit for both
documentation stages.

## Fixed stages

The documentation role runs at two deterministic points:

1. **Baseline documentation** runs after repository preparation and before
   analysis. It reads the external skill and complete eligible tracked
   target-repository text, then creates, updates, or preserves the target
   documentation.
2. **Final reconciliation** runs after implementation/check evidence and before
   review. It re-reads the same external skill commit and updates documentation
   only when the final target state requires it.

These are fixed harness-owned stages, not an autonomous loop. A failed or invalid
documentation result stops the run.

Before the pipeline may enter `repositories_ready`, the harness performs a
consumer-side readiness check through the read-only developer MCP service. That
check verifies that the MCP container can read the workspace manifest, target
checkout, exact target commit, every external checkout, exact external commits,
and required skill paths. Documentation collection cannot start until this
barrier succeeds.

## External skill boundary

The harness invokes only these documentation-agent MCP tools for the external
source:

```text
dev_external_skill_list
dev_external_skill_read
```

The workspace manifest identifies the configured source, required
`skills/archdoc` subtree, resolved commit, and allowed agent. Both the harness
broker and the MCP service enforce that only the `documentation` agent may read
it. Other developer agents receive the resulting target documentation instead.

The live skill content is supplied to the documentation model call at runtime.
It is redacted from persisted model-message artifacts and is not placed in the
Safeplane prompt bundle.

## Evidence collection

The documentation stage reads:

- `SKILL.md` first, followed by configured Markdown files from the external skill
- existing primary target documentation
- every eligible tracked repository text file

A single MCP read returns at most 2,000 lines. Files longer than that are read in
continuation pages until EOF. The per-call limit is not a repository or file
coverage limit.

Sensitive-looking paths such as `.env`, credentials, private keys, and secret
files are excluded. Binary and non-text tracked files are recorded as skipped.
Low-priority repository data artifacts whose individual records exceed the MCP
per-read byte limit are also recorded as skipped instead of blocking source and
documentation analysis. Oversized files in documentation, configuration, tests,
or source paths still fail explicitly. Stage-level file and byte budgets remain
deterministic resource guards. When a complete evidence profile cannot cover all
remaining eligible tracked text, the stage fails explicitly instead of
generating documentation from a silently partial repository view. These budgets
are defined in `workflows/developer/workflow.yaml`.

## Documentation changes

The model returns a validated documentation result. A changed result must include
one complete, unfenced Git-style unified diff confined to the configured target
documentation paths. Safeplane runs read-only `git apply --check` validation
inside the bounded model-attempt loop, before any proposal or write authorization.
Malformed hunks, inaccurate hunk counts, stale context, unprefixed blank lines,
and otherwise non-applicable patches are returned to the model as deterministic
repair feedback.

The prompt requires one exact metadata structure near the top of every changed
Markdown file. It includes literal run-bound placeholders for the external skill
commit, skill digest, documentation prompt, and repository profile, plus the
literal field names `Doc Status:` and `Source Basis:`. The harness expands the
placeholders deterministically before semantic validation.
The harness rejects:

- changes outside the allowed documentation files
- documentation deletion
- unresolved template placeholders
- apparent secret values
- missing `archdoc` provenance
- missing status/source-basis fields
- missing exact external skill commit
- malformed or non-applicable unified diff syntax

Semantic patch validation runs inside the documentation agent's bounded model
attempt loop, before a patch proposal or write authorization exists. When a
real model omits required provenance, status fields, mismatches the declared
documentation paths, or otherwise returns an invalid documentation patch, the
next attempt receives the precise deterministic validation error and the exact
required metadata block. It must return one complete replacement JSON object.
This is bounded output repair, not an autonomous workflow rework loop.

The patch is proposed through the read/write boundary, receives a one-time
harness-owned authorization tied to the documentation stage and plan budget, is
applied in a writable staging copy, and is published atomically to the run's
target checkout. The source remote is never changed.

## Outputs for later agents

The structured baseline and final artifacts contain:

- exact external source id and commit
- skill and repository evidence paths read
- tool evidence references
- patch proposal and apply evidence when changed
- changed-file hashes and budget result
- snapshots and SHA-256 hashes of the actual target documentation

Analysis, planning, implementation, review, and PR stages receive those target
document snapshots. They do not receive or interpret the external skill.

## Fake-mode acceptance

`tests/scripts/accept-external-documentation` proves with local bare Git fixtures that:

- a repository without documentation receives an evidence-based baseline
- accurate existing documentation is preserved
- baseline and final stages use the same skill commit
- a later run follows a newer external skill commit
- live skill text is absent from persisted model-message artifacts
- target and skill source remotes are unchanged by Safeplane runs

The full real single-pass implementation/check flow remains part of single-pass developer workflow.
Remote branch push and pull-request creation remain out of scope.
