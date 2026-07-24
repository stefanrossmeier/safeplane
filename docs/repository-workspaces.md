# Repository profiles and isolated workspaces

Developer runs target named repository profiles stored in operator-owned runtime
configuration, not in the tracked repository.

## Configure profiles

```bash
mkdir -p "${SAFEPLANE_HOME:-$HOME/.safeplane}/config"
cp config/repositories.example.yaml \
  "${SAFEPLANE_HOME:-$HOME/.safeplane}/config/repositories.yaml"
```

The default container path is:

```text
/data/safeplane/config/repositories.yaml
```

Override it with `SAFEPLANE_REPOSITORY_CONFIG` when necessary.

A profile declares:

```yaml
enabled: true
repository_url: https://github.com/OWNER/REPOSITORY.git
ref: main
allowed_hosts:
  - github.com
allowed_repository: OWNER/REPOSITORY
credential_profile: github
allow_file_url: false
remote_write_allowed: false
draft_pr_creation: approval_required
branch_prefix: safeplane/
pull_request_repository: OWNER/REPOSITORY
git_author_name: Safeplane
git_author_email: safeplane@example.invalid
```

The repository URL, host allowlist, owner/repository binding, base ref,
credential profile, publication repository, branch policy, and draft-PR mode are
validated before use.

## Credentials

Private Git and GitHub access uses the `github` credential profile, whose token
path is fixed inside the harness:

```text
/run/secrets/github_token
```

The host file defaults to:

```text
${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/github_token
```

Only the harness receives it. Repository URLs persisted in artifacts are
sanitized; credentials are not embedded into Git configuration.

## Workspace preparation

For each run the harness:

1. validates the named profile;
2. clones or fetches the target repository into an isolated run directory;
3. resolves the requested ref to an immutable commit;
4. prepares the configured external `archdoc` repository at its own resolved
   commit;
5. records repository manifests and commit bindings;
6. exposes only the permitted workspace views to developer agents.

Conceptual layout:

```text
${SAFEPLANE_HOME}/workspaces/<run-id>/
  repo/
  repositories/
    target/
    ai-craftkit/
  pipeline/
  evidence/
  remote-approvals/
```

The exact persisted layout is harness-owned and represented in the run and
repository manifest artifacts.

## External `archdoc` policy

The developer workflow contract fixes the public source repository, required
`skills/archdoc` path, allowed host and repository, read-only status, and
`documentation`-agent-only access. The harness records the resolved commit. The
skill content is read at runtime and is not copied into Safeplane's prompt
bundle.

Local `file://` repositories are rejected during normal operation. Acceptance
fixtures require both a profile with `allow_file_url: true` and the explicit
`SAFEPLANE_ALLOW_LOCAL_GIT_FIXTURES=yes` test flag.

## Start a run

```bash
tests/scripts/compose-safeplane-developer-fake up -d --build
./scripts/safeplane develop --repo <profile> "Implement one bounded change"
```

Inspect it with:

```bash
./scripts/safeplane status <run-id>
./scripts/safeplane evidence <run-id>
```

## Remote-write policy

`remote_write_allowed: false` permits the complete local developer pipeline but
forbids publication.

When remote write is enabled with `remote_write_allowed: true`:

- `draft_pr_creation: approval_required` waits for explicit operator approval;
- `draft_pr_creation: automatic` authorizes the harness to publish only after
  all immutable bindings, checks, review, and plan alignment pass;
- pushes are non-force and branch names are deterministic;
- duplicate approval reuses the branch and draft PR;
- Safeplane never merges.

See [Remote write](remote-write.md).

## Current constraints

- one target repository profile per developer run;
- one fixed external documentation source;
- GitHub token-file authentication for real private GitHub access;
- no submodule or Git LFS orchestration contract;
- no automatic rebase, conflict resolution, merge, release, or deployment;
- no automatic review-to-rework loop.

These constraints are deliberate boundaries, not implicit agent decisions.
