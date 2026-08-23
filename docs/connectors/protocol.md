# Shared connector client

`connectors/common` contains the typed stdlib-only client used by the explicit
CLI connector.

The package keeps workflow ingress and operator-control methods separate,
requires JSON object responses, validates the content type, propagates a request
ID, applies bounded timeouts, and does not automatically retry state-changing
requests.

The current transport intentionally targets the existing harness routes. API
versioning and authenticated principals are separate follow-up work recorded in
[the backlog](../BACKLOG.md).
