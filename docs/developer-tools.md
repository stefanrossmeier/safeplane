# Developer MCP tool boundary

The developer MCP toolset is the bounded operational boundary used by the current single-pass developer workflow. All tools are called through the harness-owned MCP broker and use strict Pydantic input and output schemas.

## Target repository inspection

The read-only `dev-workspace-mcp` service provides the existing file tools plus narrow Git metadata tools:

```text
dev_workspace_list
dev_workspace_find
dev_workspace_grep
dev_workspace_read
dev_git_metadata
dev_git_status
dev_git_diff
dev_git_log
dev_git_show
dev_git_tracked_files
dev_workspace_propose_patch
```

The Git tools invoke fixed argument-vector commands. They do not expose arbitrary `.git` filesystem reads or arbitrary Git subcommands.

`dev_git_show` accepts only:

```text
HEAD
HEAD~<bounded integer>
a full commit id that is HEAD or an ancestor of HEAD
```

All optional paths remain below the target repository and direct `.git` paths are rejected.

`dev_workspace_read` returns at most 2,000 lines per call and provides
`next_start_line` when more content remains. `dev_git_tracked_files` similarly
provides `next_start_after` when another page of tracked paths exists. These are
transport limits, not repository-coverage limits. external documentation workflow follows the continuation
values until EOF and until the tracked-file listing is complete.

The ad hoc developer model can see target inspection, Git metadata, and patch-proposal tools. It cannot see patch application, external-skill access, or declared check execution.

## External `archdoc` source

The read-only workspace MCP also provides:

```text
dev_external_skill_list
dev_external_skill_read
```

These tools resolve the prepared source from the run's `workspace.json` manifest. Both the harness broker and the MCP service require the `documentation` agent identity. Other agents are denied even when they know the tool name.

Reads are confined to the configured `skills/archdoc` subtree. Symlink reads and path escapes are rejected. The response records the exact external source commit used by the run.

developer MCP toolset provides the secure reader. external documentation workflow now uses that reader at fixed baseline and final documentation stages. Live skill content is supplied only to the documentation model call, is redacted from persisted message artifacts, and is never exposed to other agents.

## Declared check execution

Declared checks run through the separate `dev-check-mcp` service:

```text
dev_check_run
```

The initial command profile is:

```text
python_check
```

It permits a Python script only below:

```text
checks/
scripts/checks/
tests/
```

It does not permit `python -c`, a shell, an arbitrary executable, absolute paths, or parent traversal.

The planning boundary validates every declared command before the plan can reach `plan_ready`. The script must already be a regular repository file or be explicitly listed in the plan's create/modify set with a positive file budget. Missing placeholder paths are returned to the planning model as deterministic repair feedback; implementation does not begin until the corrected command is grounded. Planned scripts must be directly runnable by the exact argument vector and must fail with a non-zero exit status when their focused assertion fails.

For each invocation, the service:

1. verifies the expected authoritative repository hashes or expected absence
2. copies the target repository into a fresh temporary directory
3. excludes `.git`, virtual environments, caches, and `node_modules`
4. optionally applies a harness-generated candidate patch only inside that temporary copy
5. resolves the command profile against the resulting temporary tree, so a planned new check script can be executed without mutating the authoritative workspace
6. runs one configured argument vector without a shell
7. uses a minimal environment with no inherited Safeplane or GitHub secrets
8. applies process CPU, address-space, file-output, timeout, and process-group controls
9. terminates the complete process group after timeout
10. discards the temporary checkout
11. returns structured status and duration

The Compose service is read-only, has all capabilities dropped, receives no secrets, uses `network_mode: none` and a Unix-socket broker control channel, and has container CPU, memory, and PID limits.

The broker persists stdout and stderr as separate artifacts:

```text
SAFEPLANE_HOME/workspaces/<run-id>/evidence/checks/<tool-call-id>.stdout.txt
SAFEPLANE_HOME/workspaces/<run-id>/evidence/checks/<tool-call-id>.stderr.txt
```

The structured tool response contains references instead of retaining raw output after broker persistence.

Before accepting an implementation model's final replacement set, the harness constructs the deterministic patch and invokes every declared command with that patch as a temporary candidate. A failing or timed-out candidate does not alter the authoritative checkout; the captured output is returned to the implementation model as validation feedback within its existing attempt budget. The check service is still harness-owned and is not exposed as a model-selectable tool. After candidate acceptance and controlled patch application, the harness runs the same declared commands again against the applied workspace; those final check results remain the evidence consumed by later stages.

## Patch-plan evidence

Approved patch application now records:

- proposal id
- authorization source
- changed paths and operations
- before and after SHA-256 values
- before and after sizes
- unified-diff byte size
- implementation-plan budget result
- MCP evidence path

When `authorization_source` is `developer_pipeline_plan`, a plan budget is mandatory. Every changed path must be declared with an expected operation, maximum changed-line count, and maximum hunk count. Added and removed diff lines both count, and every line of a created file counts as changed. The harness performs the same budget check on the model's deterministic final patch before candidate checks and proposal, then the apply MCP enforces it again at mutation time. A pre-proposal budget or candidate-check violation is returned to the implementation model for repair without expanding the plan; an apply-time violation stops application before the workspace is changed.

The existing operator-approved patch path remains compatible. When no implementation plan is supplied, the evidence explicitly records `not_provided` instead of pretending a plan check occurred.

## Agent permissions

The developer workflow contract assigns per-agent MCP tools:

- documentation: target reads, Git metadata, external `archdoc` reads, patch proposal
- analysis: target reads and Git metadata
- planning: target reads and Git metadata
- implementation: target reads, Git metadata, patch proposal
- review: target reads and Git metadata
- PR: no repository tools

Declared checks are harness-owned. They are not exposed as autonomous agent tools.

## Validation

Run the complete isolated acceptance:

```bash
tests/scripts/accept-developer-tools
```

The acceptance uses local bare Git repositories, fake model responses, and no external network or real credential. It proves:

- Git metadata inspection
- documentation-only external skill access
- passing, failing, and timed-out checks
- separate stdout and stderr artifacts
- stripped secret environment
- shell-operator rejection
- undeclared-profile rejection
- path-escape rejection
- plan-budget enforcement and write evidence
- unchanged source fixture remotes
