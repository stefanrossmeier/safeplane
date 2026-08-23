# Safeplane API surface

This document describes the currently implemented harness HTTP surface used by
connectors and operator tooling. The explicit CLI connector preserves these
paths during the shell-to-container migration.

## Health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Harness health/readiness |

## Workflow and connector ingress

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/workflows` | List registry-backed workflows; optional connector filters are supported |
| `GET` | `/workflows/{entrypoint}` | Read one workflow definition |
| `POST` | `/connector/{entrypoint}` | Start a workflow and wait for its terminal response |
| `POST` | `/connector/{entrypoint}/start` | Start a workflow asynchronously |

Current connector message requests contain:

```json
{
  "connector": "cli",
  "message": "operator text",
  "session_ref": "optional-session-reference",
  "repository_profile": "optional-repository-profile"
}
```

`session_ref` and `repository_profile` are omitted when unused. The
`repository_profile` value is valid only for the `develop` entrypoint in the CLI.

## Operator control

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/runs` | List run records |
| `GET` | `/runs/{run_id}` | Read one run record |
| `POST` | `/runs/{run_id}/patches/{proposal_id}/approve` | Approve an eligible patch proposal |
| `POST` | `/runs/{run_id}/remote/approve` | Approve or retry an eligible remote draft-PR write |

Approval commands only transmit an operator decision. The harness revalidates
run state, immutable bindings, checks, review, plan alignment, repository policy,
and idempotency before authoritative action.

## CLI client surfaces

The shared Python client exposes the current API through two logical namespaces:

```text
client.connector.list_workflows()
client.connector.start_workflow(...)
client.control.list_runs()
client.control.get_run(...)
client.control.approve_patch(...)
client.control.approve_remote(...)
```

This code separation prevents CLI command code from treating workflow ingress
and operator-control operations as one undifferentiated interface.

## Error handling

The shared client requires JSON object responses and `application/json` content
type. It maps connection failures, protocol failures, authorization failures,
and harness rejections into distinct exceptions. State-changing requests are
not retried automatically.

The CLI maps these classes to stable exit codes documented in
[CLI connector](connectors/cli.md#exit-codes).

## Planned namespace separation

The current routes are intentionally retained for parity. A later migration will
introduce versioned connector and control namespaces and authenticated
principals. ADR 0030 records that proposed durable separation; it is not claimed
as implemented here.
