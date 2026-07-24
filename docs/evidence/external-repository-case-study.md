# External Repository Case Study

> Sanitized evidence from one completed Safeplane developer run.
> Repository identity, source content, credentials, private paths, and pull-request URL are omitted.

## Summary

- Safeplane run: `run_c3671433-2073-4aa3-b6a1-f46d9bef7a32`
- Target: external repository (identity omitted)
- Task: Remove one deprecated configuration entry while preserving the remaining entries, add a focused self-contained regression check, and update relevant documentation.
- Target base commit: `988e0159f1f643f25a4cadf7c531e31d6645e6ee`
- External `archdoc` commit: `c9a96de5de08d1b987f0f6746cb1f8cbf38895a0`
- Review verdict: `LGTM`
- Plan alignment: `ALIGNED`
- Draft pull request: created and manually inspected; URL omitted
- Merge status: not merged by Safeplane

## Fixed stage sequence

1. `repositories`
2. `baseline_documentation`
3. `analysis`
4. `planning`
5. `implementation`
6. `checks`
7. `final_documentation`
8. `review`
9. `pr`
10. `remote_write`

## Model execution

| Stage | Configured model | Actual provider | Actual model | Retries | Duration | Tokens | Cost |
|---|---|---|---|---:|---:|---:|---:|
| baseline documentation | `openrouter/openai/gpt-5-mini` | OpenAI | `openai/gpt-5-mini` | 0 | 139135 ms | 201058 | 0.06585 |
| analysis | `openrouter/anthropic/claude-haiku-4.5` | Amazon Bedrock | `anthropic/claude-haiku-4.5` | 0 | 39420 ms | 10825 | 0.028193 |
| planning | `openrouter/anthropic/claude-haiku-4.5` | Amazon Bedrock | `anthropic/claude-haiku-4.5` | 0 | 12483 ms | 12808 | 0.018404 |
| implementation | `openrouter/openai/gpt-5-mini` | OpenAI | `openai/gpt-5-mini` | 1 | 68958 ms | 48122 | 0.01355665 |
| final documentation | `openrouter/openai/gpt-5-mini` | OpenAI | `openai/gpt-5-mini` | 0 | 132866 ms | 213246 | 0.06856975 |
| review | `openrouter/anthropic/claude-haiku-4.5` | Amazon Bedrock | `anthropic/claude-haiku-4.5` | 0 | 4516 ms | 19896 | 0.02084 |
| PR text | `openrouter/openai/gpt-5.4-nano` | OpenAI | `openai/gpt-5.4-nano` | 0 | 5215 ms | 17497 | 0.0041525 |

Approximate total model cost: `$0.2196`.

## Controlled checks

The planned self-contained check passed inside the isolated check container with
network access disabled. The final applied workspace was checked again before
review and publication.

## Artifacts produced

The run retained validated request, repository context, documentation evidence,
analysis, plan, implementation replacements, harness-generated patch, check
outputs, final documentation reconciliation, review, PR text, immutable
remote-write binding, and publication evidence.

## Operator findings

The draft pull request was bounded, understandable, and high quality when
manually inspected. The Safeplane source checkout remained unchanged, and the
target branch was not merged automatically.

## Defects found during hardening

Earlier attempts exposed three general workflow weaknesses:

- a functionally correct implementation could deviate from the approved change mechanism;
- an isolated check could incorrectly import dependency-heavy application code;
- bounded repair could run out of attempts after correcting both the check mechanism and a physical line budget.

## Fixes made

- Implementation prompts now require the exact planned mechanism.
- Review output includes explicit plan alignment and rejects an aligned-looking result that materially deviates.
- Planning guidance requires self-contained checks for isolated execution.
- Candidate validation provides deterministic repair feedback.
- Final implementation validation allows four bounded attempts without adding a post-application rework loop.

## Telegram evidence

This case study contains no Telegram identifiers. Connector command acceptance is
recorded separately through the guarded real Telegram smoke.

## Known limitations

This is one bounded external-repository task, not a benchmark. Documentation
stages dominate token usage. Merge, release, and deployment remain explicit
human decisions.

## Human decision boundary

Safeplane created a draft pull request only after the configured deterministic
bindings, checks, and review passed. It did not merge, release, or deploy the
target repository.
