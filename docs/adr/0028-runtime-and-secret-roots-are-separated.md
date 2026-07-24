# ADR 0028 — Runtime and secret roots are separated

Status: Accepted

## Context

Safeplane previously stored credentials beneath `SAFEPLANE_HOME` while several
services mounted that entire directory. Named Docker-secret declarations were
therefore weaker than the actual filesystem boundary: an unintended service
could potentially read the host credential file through the broad runtime
mount.

The base Compose network was also comparatively flat and most long-running
services ran as root with writable root filesystems.

## Decision

Safeplane separates runtime state and credentials:

```text
SAFEPLANE_HOME=$HOME/.safeplane
SAFEPLANE_SECRET_ROOT=$HOME/.config/safeplane/secrets
```

No service mounts the runtime root as a whole. Compose grants explicit
capability-specific subdirectories, named secrets, and communication networks.
Long-running services run as a fixed non-root UID with read-only root
filesystems, dropped capabilities, `no-new-privileges`, bounded tmpfs, and
resource limits.

The local harness port is loopback-only. Internal MCP, model, notification, and
connector communication uses explicit networks. The developer check service
remains fully network-disabled.

## Consequences

- Secret ownership now matches the actual mount boundary.
- Host runtime directories must be prepared for the fixed container UID.
- Existing credentials below `SAFEPLANE_HOME/secrets` must be migrated.
- Services can no longer rely on undeclared runtime directories or flat network
  reachability.
- Security claims are verified by static and running-container acceptance.

ADR 0012 and the secret-path portions of ADR 0019 describe the earlier local
layout and are superseded by this decision.
