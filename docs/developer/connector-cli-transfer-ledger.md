# Connector CLI transfer ledger

This ledger separates portable connector work from environment-specific follow-up
before transfer to the public repository.

| Area | Transfer classification | Notes |
| --- | --- | --- |
| `connectors/common` | portable unchanged | shared stdlib client |
| `connectors/cli` | portable unchanged | one-shot connector package and image |
| base Compose connector network | portable unchanged | harness and CLI share `connector-harness` |
| `scripts/safeplane` | portable with operational review | preserve public Compose project conventions |
| VPS build integration | portable with configuration review | verify public VPS wrapper/profile state |
| CLI unit/contract tests | portable unchanged | neutral fixtures |
| CLI container acceptance | portable with Docker-environment review | no private service names or credentials |
| architecture/operations docs | rewrite/reconcile | public repository wording and current state must win |
| ADR numbering | public adjustment if required | do not copy a conflicting number |

Before public transfer, search the final diff and repository history for private
hosts, repository URLs, filesystem paths, connector identifiers, secret values,
and deployment-specific assumptions. Re-run the complete public validation suite
on the public clone rather than applying the patch blindly.
