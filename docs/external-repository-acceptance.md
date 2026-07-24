# Real external-repository acceptance

Status: guarded manual acceptance

This procedure proves the single-pass developer workflow against an
operator-configured external repository. It does not introduce automatic rework,
merge, release, or deployment.

## Runtime prerequisites

Configure an enabled repository profile in:

```text
${SAFEPLANE_HOME:-$HOME/.safeplane}/config/repositories.yaml
```

The profile must declare the real base branch, exact allowlisted repository,
credential profile, branch policy, and pull-request repository. Automatic draft
PR creation requires both:

```yaml
remote_write_allowed: true
draft_pr_creation: automatic
```

The GitHub token remains outside `SAFEPLANE_HOME` and is mounted only into the
harness. The OpenRouter key is mounted only into model-gateway.

## Independent model selection

Each developer agent has a separate model profile. Real mode may override a
profile without editing the workflow contract:

```bash
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_DOCUMENTATION='openrouter/provider/model-a'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_ANALYSIS='openrouter/provider/model-b'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PLANNING='openrouter/provider/model-b'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_IMPLEMENTATION='openrouter/provider/model-c'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_REVIEW='openrouter/provider/model-d'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PR='openrouter/provider/model-b'
```

## Prepare the run

Choose a bounded, testable, reviewable, non-destructive task, then run:

```bash
export SAFEPLANE_CONFIRM_REAL_EXTERNAL_REPOSITORY=yes
export SAFEPLANE_REAL_REPOSITORY_PROFILE='<profile>'
export SAFEPLANE_REAL_REPOSITORY_EXPECTED_REPOSITORY='OWNER/REPOSITORY'
export SAFEPLANE_REAL_REPOSITORY_TASK='Describe the exact bounded task'
export SAFEPLANE_REAL_REPOSITORY_RUN_TIMEOUT_SECONDS=7200

tests/scripts/validate-real-external-repository prepare
```

The script validates the repository profile, fingerprints the Safeplane source
checkout, starts the real developer stack, submits the asynchronous run, and
polls it to a terminal state. It requires passing checks, `LGTM`, explicit plan
alignment, real provider metadata, fixed repository commits, and a completed
draft PR for an automatically opted-in profile.

Inspect the run and evidence:

```bash
./scripts/safeplane status run_...
./scripts/safeplane evidence run_...
```

## Record sanitized evidence

After inspecting the draft PR, provide public-safe observations:

```bash
export SAFEPLANE_REAL_REPOSITORY_RUN_ID='run_...'
export SAFEPLANE_REAL_REPOSITORY_SANITIZED_TASK_SUMMARY='Public-safe task summary.'
export SAFEPLANE_REAL_REPOSITORY_OPERATOR_FINDINGS='What the operator observed.'
export SAFEPLANE_REAL_REPOSITORY_DEFECTS_FOUND='Defects found, or none.'
export SAFEPLANE_REAL_REPOSITORY_FIXES_MADE='Hardening performed, or none.'
export SAFEPLANE_REAL_REPOSITORY_KNOWN_LIMITATIONS='Limits of this proof.'
export SAFEPLANE_REAL_REPOSITORY_TELEGRAM_PROOF='Sanitized connector evidence.'

tests/scripts/validate-real-external-repository record
```

The generated case study omits repository URLs, owner/repository identifiers,
private source, credentials, raw model messages, and absolute runtime paths.

## Regression validation

Normal validation remains fake and secret-free:

```bash
tests/scripts/test-unit -q
tests/scripts/accept-publication-path
```

The real external-repository script is guarded and excluded from normal CI.
