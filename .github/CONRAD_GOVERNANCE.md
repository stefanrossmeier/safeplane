# AI contribution workflow

Conrad (Hermes Agent) uses dedicated `conrad/` branches and pull requests.
Every PR it creates or contributes to carries `ai-generated` and an AI
disclosure explaining its contribution. PR descriptions include a summary,
validation results and known limitations. Human review must not be claimed
until it has actually happened. Existing project contribution rules still apply.

The trusted-base `.github/workflows/conrad-governance.yml` adds the label to
recognized AI PRs (branch prefixes `conrad/`, `codex/`, explicit `AI disclosure:`,
or an existing `ai-generated` label) and publishes `conrad/ai-label` on the PR's
head commit. Recognition is convention-based, not a reliable identity boundary.
Ordinary human PRs are not automatically labeled as AI-generated.

## Merging

All repositories require human merging through Conrad's policy, except
`stefanrossmeier/interesting-items`, whose trusted-base workflow may squash-merge
new regular Markdown research fragments under the six existing `items/`
categories. That exception requires an owner-authored same-repository PR on a
`conrad/interesting-item-` branch, the AI label, structural research frontmatter
and body headings, no existing paths changed, an up-to-date branch, and successful
CI. A `conrad/add-only` status records the validation result. Nonqualifying
changes remain open for manual review. Human-approved maintenance may change
existing content; it never qualifies for autonomous merging.

Auto-merging is controlled by the repository Actions variable
`CONRAD_AUTOMERGE_ENABLED=true` and code explicitly allowlisting only
`stefanrossmeier/interesting-items`. A ten-minute scheduled reconciliation retries
PRs waiting on CI. The head SHA is passed to GitHub's squash-merge API; existing
branch protections and required checks remain effective. Only successfully
merged `conrad/interesting-item-` branches are deleted. If main advanced,
update the fragment branch without force-pushing and let validation rerun.

The setup PR must be manually merged. It cannot qualify for automatic merging.
The workflow never checks out PR code or executes fragment contents. The
separate unit-test workflow has read-only permissions and no stored credentials.

## Security boundary

The owner authorized operation without branch protection when unavailable.
Without protection these statuses are advisory, not required server-side checks.
Validation and the merge guard are enforced by the normal automation path only.
Concurrent repository changes between validation and merge remain a limitation
without an up-to-date required check enforced by GitHub.

Conrad currently shares the owner's GitHub identity and administrative token.
It can technically push directly, merge other PRs, change settings, or alter its
own instructions. No label, instruction file, or helper can remove those powers.
Even with protection, an administrator able to edit it can weaken the policy.
For adversarial enforcement, use a separate GitHub App/machine identity without
administration or bypass permissions and independently controlled repository
rules. Do not treat this installation as that separation of duties.

The canonical VPS policy and publisher live in `~/.hermes/governance/` and are
referenced from the persistent `~/.hermes/SOUL.md`. Future repositories inherit
Conrad's restrictive instructions and publisher behavior, but repository Actions
workflows must be installed separately using the governance setup script. Nothing
automatically changes future repository settings on GitHub.
