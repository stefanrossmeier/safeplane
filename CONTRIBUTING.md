# Contributing to Safeplane

Thank you for considering a contribution to Safeplane.

Safeplane is built around deterministic orchestration and narrow authority boundaries. Contributions should preserve those properties rather than making agents more autonomous by bypassing validation, credentials, or human review.

## Before starting

For a small bug fix or documentation improvement, open a pull request directly.

For a substantial feature, workflow change, new connector, new credential boundary, or architectural change, open an issue first. Describe the problem, the proposed behavior, the authority boundary involved, and how the result can be tested deterministically.

## Development setup

Use a supported Python environment and Docker with the Docker Compose plugin.

From the repository root, install the project according to the README and run the unit tests with:

```bash
tests/scripts/test-unit -q
```

Run repository hygiene checks with:

```bash
tests/scripts/check-repository-hygiene
```

Run the complete local validation suite with:

```bash
tests/scripts/test-all
```

Some acceptance tests require Docker. Real-provider, Telegram, GitHub, and external-repository paths are guarded and must not be enabled for normal public testing.

## Contribution principles

Changes should preserve the following rules:

- orchestration, retries, permissions, credentials, Git operations, and authoritative writes remain harness-owned;
- model output is treated as untrusted structured input until deterministically validated;
- workflow stages retain explicit schemas, inputs, outputs, and evidence;
- connectors translate operator intent but do not own workflow policy;
- agents and tool services receive only the access required for their stage;
- checks remain secretless and networkless by default;
- draft pull-request creation remains bounded and harness-owned;
- Safeplane never merges automatically;
- fake mode remains the default for public tests and CI;
- public examples and fixtures remain repository-neutral and contain no real credentials or private data.

Do not weaken validation merely to make a model response pass.

## Making a change

1. Create a focused branch.
2. Keep the change as small as practical.
3. Add or update deterministic tests for changed behavior.
4. Update current documentation when operator behavior, architecture, configuration, or limitations change.
5. Run the relevant focused tests.
6. Run the complete unit suite.
7. Run repository hygiene and `git diff --check`.
8. Inspect the final diff for secrets, private identifiers, generated files, and unrelated changes.

Useful final checks are:

```bash
tests/scripts/test-unit -q
tests/scripts/check-repository-hygiene
git diff --check
git status --short
```

## Tests and fixtures

Tests must be deterministic and secret-free.

- Prefer fake providers, neutral repositories, and isolated temporary state.
- Do not make public CI depend on OpenRouter, Telegram, GitHub credentials, or real remote writes.
- Do not add target-specific behavior switches to generic prompts or fixtures.
- Keep generated caches, runtime state, patches, archives, credentials, and unsanitized evidence out of Git.
- When testing rejection paths, assert the deterministic reason rather than relying on model wording.

## Documentation

Current documentation should describe the product as it behaves now. Historical implementation notes should not be presented as current behavior.

Documentation changes should use generic repository names and placeholder URLs. Do not include private repository identities, private pull-request URLs, VPS addresses, local absolute paths, Telegram identifiers, or secret values.

## Pull requests

A pull request should include:

- the problem being solved;
- the chosen approach;
- affected security or authority boundaries;
- tests run and their results;
- documentation changes;
- known limitations or follow-up work.

Keep pull requests focused. Unrelated refactoring should be submitted separately.

## Commit messages

Use concise, imperative commit messages that describe the behavioral change, for example:

```text
Validate planning scope before implementation
```

## Security issues

Do not report sensitive vulnerabilities in a public issue. Follow the process in [`SECURITY.md`](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0 included in this repository.
