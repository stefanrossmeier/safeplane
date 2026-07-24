# Harness-owned branch push and draft pull request

Status: draft-PR publication complete. Local Docker and guarded dedicated-repository GitHub acceptance passed.

Safeplane performs no remote Git write before controlled checks, one `LGTM` review, and draft PR text preparation. Repository profiles choose whether the harness then creates the draft PR automatically or waits for a separate retry/approval command.

## Repository policy and manual retry

```yaml
remote_write_allowed: true
draft_pr_creation: automatic  # or approval_required
```

`automatic` creates or reuses one draft PR after successful validation. `approval_required` remains the default. The manual command below also remains the idempotent retry path if automatic creation fails.


CLI:

```bash
./scripts/safeplane approve-pr run_<uuid>
```

Telegram:

```text
/approve_pr [run-id]
```

Omitting the Telegram run id uses the latest run mapped to that chat. Approval is accepted only for a `develop` run whose repository profile explicitly enables remote write.

## Immutable approval request

When an eligible run reaches `waiting_for_remote_approval`, the harness writes:

```text
SAFEPLANE_HOME/workspaces/<run-id>/pipeline/remote-approval-request.json
```

The request binds the approval to:

- repository profile and sanitized repository URL
- pull-request owner/repository
- credential-profile identifier, never the secret
- base ref and exact base commit
- final target-workspace tree hash and file count
- implementation-plan hash and commit message
- controlled-check artifact hash
- review artifact hash
- PR-proposal hash
- Git author identity
- deterministic Safeplane branch name

Approval revalidates every binding before remote write. A changed workspace, changed artifact, changed profile, moved base branch, failed check, non-`LGTM` verdict, or conflicting remote branch stops the operation.

## Harness-owned transaction

After automatic authorization or a manual retry, the harness:

1. copies the approved read-only target into a temporary harness-only staging repository;
2. verifies the target `HEAD`, origin URL, and remote base ref;
3. creates the deterministic branch and commit;
4. checks whether that exact remote branch commit already exists;
5. pushes without force only when the branch is absent;
6. searches GitHub for an existing open PR from the branch;
7. creates one draft PR only when none exists;
8. records approval, branch, commit, PR, and evidence metadata;
9. marks the developer pipeline `completed`.

The staging repository is deleted after the attempt. The approved target workspace remains read-only at rest. Safeplane does not merge the pull request.

Repeated remote-write execution is idempotent. The same completed result is returned, and no duplicate branch, commit, or PR is created. A retry after a partial remote success reconstructs the same deterministic commit and reuses an existing matching branch or PR.

## Credential boundary

The GitHub token host file defaults to:

```text
~/.config/safeplane/secrets/github_token
```

Override it with:

```bash
export SAFEPLANE_GITHUB_TOKEN_FILE=/private/path/github_token
```

The file is intentionally outside `SAFEPLANE_HOME`, because several runtime services mount portions of that runtime directory. `docker-compose.github.yml` mounts the token only into the harness at:

```text
/run/secrets/github_token
```

Agents, MCP services, model-gateway, Telegram, the GitHub mock, traces, artifacts, Git configuration, and PR content do not receive the token. Git authentication uses a temporary `GIT_ASKPASS` helper. GitHub API authentication uses the same harness-only secret in an HTTP header.

Outside explicit local fixture mode, the API destination is fixed to `https://api.github.com`.

## Safety properties

Safeplane does not:

- push after failed or timed-out checks;
- push after `REQUEST_CHANGES`;
- push a workspace or approval artifact that changed;
- push when the base branch moved;
- force-push over an existing branch;
- create a non-draft PR;
- call a merge endpoint;
- mark a PR ready for review;
- release or deploy the target repository.

## Evidence and status

Remote approval records are written under:

```text
SAFEPLANE_HOME/workspaces/<run-id>/remote-approvals/
```

CLI and Telegram status report the planned branch before remote write and the final branch, commit, and draft-PR URL after success.

## Validation

Fake/local acceptance:

```bash
tests/scripts/accept-draft-pr-workflow
```

This uses local bare Git remotes and an isolated GitHub API mock. It proves success, duplicate approval, changed-workspace rejection, moved-base rejection, failed-check rejection, `REQUEST_CHANGES` rejection, no force push, one draft PR, credential isolation, and no merge call.

A guarded real GitHub smoke must use a dedicated test repository before example-target:

```bash
SAFEPLANE_CONFIRM_REAL_GITHUB_DRAFT_PR=yes \
SAFEPLANE_DRAFT_PR_RUN_ID=run_<uuid> \
SAFEPLANE_DRAFT_PR_EXPECTED_REPOSITORY=owner/dedicated-test-repository \
  tests/scripts/validate-real-draft-pr
```

The referenced run must target exactly the dedicated repository. It may be waiting for remote approval or already completed. Rerunning the smoke against a completed run verifies that the same branch and draft pull request are returned without another remote write.
