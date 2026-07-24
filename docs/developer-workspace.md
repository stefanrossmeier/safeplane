# Developer workspace boundary

Every developer run receives an isolated repository workspace under:

```text
${SAFEPLANE_HOME}/workspaces/<run-id>/
```

Repository preparation resolves the configured target and external sources to
specific commits. The Safeplane source checkout is not used as the authoritative
target unless an operator deliberately configures it as an external repository.

## Read-only inspection

`dev-workspace-mcp` sees the workspaces subtree read-only at `/workspace`. Every
request is bound to a run-specific root and path escapes are rejected.

Available inspection capabilities include:

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
```

Only the documentation agent may use the external-skill reader. Implementation
may use `dev_workspace_propose_patch` to persist exact replacement proposals;
this does not mutate the repository.

## Controlled application

The model-visible workspace service cannot apply patches. Authoritative
application uses `dev-workspace-apply-mcp` only after the harness has:

1. validated the replacement artifact and exact old text;
2. checked planned paths, operations, line budgets, and hunk budgets;
3. generated the authoritative Git patch;
4. run declared checks against a disposable candidate;
5. created a one-time internal apply authorization.

The apply service receives no credentials or host source mount. It applies the
validated patch to the controlled per-run workspace and returns a structured
result. The harness verifies that the changed paths exactly match the accepted
artifact.

## Check isolation

`dev-check-mcp` receives jobs over a Unix socket and uses `network_mode: none`.
It has no secret mount and no shell interface. Commands must match a declared
profile, allowed executable, path root, suffix, timeout, output, CPU, memory, and
process budget.

Candidate checks run before authoritative application. The same commands run
again after application and become review evidence.

## Lower-level patch approval

Safeplane retains a separate explicit patch-proposal approval capability for
bounded workspace changes:

```bash
./scripts/safeplane approve-patch <run-id> <proposal-id>
```

This is distinct from the complete `develop` pipeline and from remote draft-PR
approval. It uses the same controlled apply boundary and does not grant GitHub
access.

## Security properties

- per-run roots prevent cross-run workspace access;
- `.git` is not exposed as an unrestricted filesystem tree;
- model-visible tools cannot execute arbitrary shell commands;
- read and apply services receive no provider, Telegram, or GitHub secret;
- the check service has no network;
- the harness owns proposal validation, application authorization, and evidence.

## Start and validate

```bash
tests/scripts/compose-safeplane-developer-fake up -d --build
tests/scripts/accept-developer-workspace
tests/scripts/accept-patch-approval
```

See [Developer workflow](developer-pipeline.md), [Developer tools](developer-tools.md),
and [Repository workspaces](repository-workspaces.md).
