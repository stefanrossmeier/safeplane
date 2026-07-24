# ADR 0027: Draft-PR creation may be automatic, but merge remains human

Status: Accepted

## Context

The operator reviews work in GitHub pull requests. Requiring a separate approval before creating the review surface adds friction without improving the merge boundary.

## Decision

Repository profiles may set `draft_pr_creation: automatic`. After controlled checks pass and independent review returns `LGTM`, the harness may automatically push the deterministic branch and create/reuse one draft PR. The default remains `approval_required`.

## Consequences

Automatic mode is explicit per repository and still revalidates immutable run evidence. Safeplane never marks the PR ready, approves it, merges it, releases it, or deploys it. The operator reviews and decides what happens next in GitHub.
