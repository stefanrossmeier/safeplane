# Isolated web research

Safeplane may use `safe-web-research` for narrowly scoped public clarification during the developer workflow. The integration deliberately does **not** add Internet access to the developer agent, repository workspace, or developer MCP containers.

## Architecture

```text
sensitive Safeplane side          non-egress boundary             public / Internet side

analysis model
    |
    | JSON tool request
    v
Safeplane harness + MCP broker
    |  - agent allowlist
    |  - strict input schema
    |  - declassification guard
    |  - forward_context: false
    |
    | research-gateway network
    v
web-research-gateway (FastAPI)
    |  - no Internet egress
    |  - no repository / SAFEPLANE_HOME mount
    |  - validates the public request again
    |
    | research-control network
    v
web-research-agent (FastAPI)
    |  - no Docker network shared with the harness
    |  - no repository / SAFEPLANE_HOME mount
    |  - dedicated Brave/OpenRouter credentials only
    |  - bounded safe-web-research budget
    |
    | research-egress network
    v
Internet / Brave / OpenRouter / fetched public pages
```

The Internet-enabled research agent and the Safeplane harness have **no Docker network in common**. A small non-egress gateway is dual-homed between two internal networks and exposes only the research RPC. It has no Safeplane mounts, no research credentials, and no Internet-egress network. This prevents the online research process from directly addressing the harness or other harness-side services through the research integration.

The research agent is not published to the host. Its only host mount is the dedicated web-research credential directory. Do not put any other Safeplane credentials or data in that directory.

The Safeplane MCP broker normally forwards run/session context to MCP servers. `web-research` sets `forward_context: false`, so the gateway receives only the validated tool name and arguments. The gateway and research agent both reject a `params.context` member. The broker uses a server-specific 120-second timeout for this service; existing MCP servers keep the normal default timeout.

## Who can use it

Only the developer workflow's `analysis` agent receives `web-research/web_research_clarify`. Documentation, planning, implementation, review, and PR agents do not receive that server. The analysis stage has a small tool loop because, at the routing-advisor baseline commit, the implementation stage was the only model stage with a tool loop.

Analysis may make at most two research calls. The purpose is external clarification that materially affects requirements or architecture, such as current public API behavior, a public standard, or a dependency's documented contract. Planning and implementation consume the resulting `AnalysisResult`; they do not get research access themselves.

## Declassification boundary

A research request can contain only:

- `question`: one line, 8-600 characters;
- `allowed_domains`: up to eight public DNS hostnames; and
- `freshness_days`: optional, 1-3650.

There is intentionally no `context`, `files`, `paths`, arbitrary URL list, repository blob, transcript, or workspace reference field. The harness, non-egress gateway, and research service reject obvious local paths, Safeplane environment names, private-key markers, common credential formats, JWT-like values, large opaque tokens, code fences, line-broken pasted context, and internal/local domains.

This guard is defense in depth, **not a proof of semantic non-disclosure**. A natural-language model that can see confidential facts can encode those facts into an otherwise ordinary-looking sentence. Therefore:

- use this capability only for repositories/workflows where automatic public clarification is acceptable;
- remove the `web-research` permission from `analysis` for strict confidential workflows; or
- introduce an explicit human declassification/approval step before research if the security requirement is that no repository-derived information may ever leave Safeplane.

Container and network separation prevent the Internet-enabled component from mounting Safeplane data or directly connecting to the harness through this research path. They cannot prove that an upstream model never chooses to disclose a fact in a query.

## Enable the research containers

The gateway and agent are behind the Compose profile `web-research`, so normal Safeplane startup does not start the research path.

Create a dedicated secret directory containing only research credentials:

```bash
mkdir -p "$HOME/.safeplane/web-research-secrets"
printf '%s' "$BRAVE_API_KEY" > "$HOME/.safeplane/web-research-secrets/brave_api_key"
printf '%s' "$OPENROUTER_API_KEY" > "$HOME/.safeplane/web-research-secrets/openrouter_api_key"
chmod 700 "$HOME/.safeplane/web-research-secrets"
chmod 600 "$HOME/.safeplane/web-research-secrets/"*
```

Start Safeplane with the optional profile:

```bash
docker compose --profile web-research up -d --build
```

To use another host directory, set `SAFEPLANE_WEB_RESEARCH_SECRETS_DIR`. To choose another OpenRouter model for the research service, set `SAFEPLANE_WEB_RESEARCH_MODEL` before starting Compose.

The agent image pins `safe-web-research` to release `v0.1.0`. Upgrade that reference deliberately and rerun the unit and live acceptance tests when adopting a later release.

## Tests

The deterministic unit suite covers the input/output contract, secret/path rejection, checked-in per-agent authorization, omission of Safeplane MCP context, network topology, the non-egress gateway, the FastAPI/MCP research adapter, the server-specific broker timeout, and the analysis clarification loop. Run it with the normal command:

```bash
tests/scripts/test-unit -q
```

The live acceptance test performs real Brave search and OpenRouter calls and may incur charges. Install the research-agent package into the active test environment, then opt in explicitly:

```bash
pip install -e services/web-research-agent
SAFEPLANE_RUN_LIVE_WEB_RESEARCH=1 \
  BRAVE_API_KEY=... \
  OPENROUTER_API_KEY=... \
  pytest -q tests/live/test_web_research_agent_live.py
```

The live test asserts that a public clarification returns an answer, source provenance, and usage/cost accounting. It must remain opt-in.

## Scope note

This integration establishes the Internet/sensitive-data separation for **web research**. It does not claim that every existing Safeplane service is globally air-gapped: the baseline Compose topology already contains other intentional egress networks. If the project-level invariant is strengthened to "no process with repository access may have any network egress at all," that should be handled as a separate runtime-boundary change rather than hidden inside this feature.
