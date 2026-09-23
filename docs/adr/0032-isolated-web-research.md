# ADR-0032: Isolate public web research from the developer runtime

## Status

Accepted by this patch.

## Context

The developer workflow sometimes needs current public facts that are absent from a repository snapshot: dependency documentation, current public APIs, standards, or externally published behavior. Giving the developer agent a browser or general HTTP tool would combine repository-sensitive context with direct Internet capability and would conflict with Safeplane's least-authority design.

`safe-web-research` already provides bounded search/fetch/orchestration and provenance-aware output. It is designed as a research capability rather than a general browser/action agent.

## Decision

Run `safe-web-research` behind a dedicated FastAPI adapter in a separate `web-research-agent` container, and place a second minimal `web-research-gateway` container between the harness and that online container.

The Internet-enabled agent:

- has Internet egress;
- has no Docker network in common with the Safeplane harness;
- has no repository or `SAFEPLANE_HOME` mount;
- receives no Safeplane run/session MCP context;
- receives only dedicated Brave/OpenRouter credentials;
- exposes only `web_research_clarify`; and
- returns projected research results rather than raw page bodies.

The gateway:

- has no Internet-egress network;
- has no Safeplane data mount and no research credentials;
- is the only component that shares one internal network with the harness and another internal network with the research agent; and
- validates the narrow public request again before forwarding it.

The Safeplane harness remains the authorization and first schema boundary. Only the developer `analysis` agent may invoke the tool. Analysis may use at most two calls and passes conclusions forward in the normal `AnalysisResult`. Planning, implementation, documentation, review, and PR agents remain without web-research authority.

The request schema is intentionally too narrow to carry repository blobs or arbitrary local data. A deterministic declassification guard rejects common secret/path forms at the harness, gateway, and research agent.

## Alternatives considered

### Add HTTP/browser access to developer agents

Rejected. This directly combines repository context and general network access and creates a much larger exfiltration and prompt-injection surface.

### Run safe-web-research as a library inside the harness

Rejected. The harness owns sensitive state, workspaces, authorization, and other credentials. Embedding an Internet research stack in that process defeats the desired isolation boundary.

### Put the Internet-enabled research container directly on a harness-shared network

Rejected. Even without filesystem mounts, an Internet-compromised process would then have a direct network route to the sensitive harness. The non-egress gateway removes that direct adjacency while keeping a simple internal FastAPI contract.

### Give every developer stage the research tool

Rejected. Research is clarification, not implementation authority. Concentrating it in analysis lets later stages consume a normal artifact while keeping their capability sets smaller.

### Separate research container without request declassification

Rejected as insufficient. Container isolation blocks direct filesystem access but an upstream model could still put sensitive text into the research query. The schema and guard reduce accidental leakage, and the documentation makes clear that strict semantic non-disclosure requires disabling automatic research or adding human approval.

## Consequences

The integration adds two optional services: one non-egress gateway and one Internet-enabled research agent. It also adds a small analysis tool loop and a paid live test path because Brave and OpenRouter calls have external cost.

The separation is strong against direct filesystem/credential access and direct research-agent-to-harness network access, but it is not an information-flow proof. A future strict-confidentiality profile should place an explicit operator approval/declassification decision on each outbound research question.
