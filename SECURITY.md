# Security Policy

Safeplane is a single-operator, self-hosted AI agent harness. It executes workflows that may access model providers, Telegram, Git repositories, and local runtime data. Security reports are therefore taken seriously, especially when they concern credential exposure, authorization boundaries, unintended network access, repository mutation, or evidence leakage.

## Supported versions

Security fixes are provided for the latest version on the default branch. Earlier commits, development snapshots, and private deployment configurations are not supported as separate release lines.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability that could expose credentials, private repository content, personal information, or a working exploit.

Use GitHub's private vulnerability reporting feature for this repository when it is available. Include:

- a concise description of the issue;
- the affected component and commit or version;
- reproduction steps or a minimal proof of concept;
- the expected and observed behavior;
- the potential impact;
- any suggested mitigation, if known.

Please remove real credentials, private source code, Telegram identifiers, personal paths, and other sensitive data from the report. Use placeholders or sanitized evidence instead.

For non-sensitive hardening suggestions or documentation errors, open a normal GitHub issue.

## Response process

A report will be assessed for reproducibility, impact, and affected security boundary. Confirmed issues will be handled according to severity and may result in a private fix before public disclosure.

Please allow reasonable time for investigation and remediation before publishing details. Coordinated disclosure is appreciated.

## Security boundaries

Safeplane is designed around these boundaries:

- the harness owns orchestration, authorization, credentials, Git operations, and authoritative writes;
- model outputs are advisory and validated deterministically;
- agents and MCP tool services do not receive Git credentials;
- checks run without inherited secrets or network access by default;
- remote publication is limited to harness-owned branch pushes and draft pull requests;
- merge remains a human decision;
- runtime data, configuration, and secrets are stored separately;
- production deployment publishes no Safeplane application port by default.

A report is especially valuable when it demonstrates that an implemented boundary differs from these claims.

## Deployment responsibility

Safeplane is provided as self-hosted software. Operators remain responsible for:

- protecting host access and SSH credentials;
- provisioning least-privilege provider and Git credentials;
- restricting access to configuration, secrets, backups, logs, and evidence;
- applying operating-system, Docker, and dependency updates;
- reviewing generated changes and draft pull requests before merge;
- validating firewall, outbound network, backup, and restore policies for their environment.

Do not use production credentials in public examples, tests, bug reports, or evidence bundles.
