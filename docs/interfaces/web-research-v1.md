# Web research interface v1

Status: proposed stable internal interface

Safeplane-facing provider: `web-research-gateway`

Internet-facing provider: `web-research-agent`

Consumer: Safeplane harness MCP broker

Tool: `web_research_clarify`

## Trust contract

Every tool request is treated as a public-data release. The Internet-enabled provider must never receive a repository mount, `SAFEPLANE_HOME`, Safeplane connector credentials, run/session context, or arbitrary local files.

The registered Safeplane MCP server **must** set `forward_context: false`. Both gateway and agent reject an MCP `params.context` member so an accidental broker regression fails closed.

The gateway is a separate non-egress trust boundary. It has no Safeplane data mounts, no Brave/OpenRouter credentials, and no Internet-egress network. The Internet-enabled research agent has no Docker network in common with the harness.

## Transport

There are two internal HTTP JSON-RPC 2.0 hops:

```text
harness
  -- research-gateway --> http://web-research-gateway:8080/mcp
web-research-gateway
  -- research-control --> http://web-research-agent:8080/mcp
```

Only `web-research-agent` is attached to `research-egress`. Neither service is exposed on a host port.

Safeplane configures a 120-second MCP timeout for this server. The gateway's upstream timeout is 115 seconds, so it can fail cleanly before the broker deadline.

## Request

```json
{
  "jsonrpc": "2.0",
  "id": "tool_call_<opaque>",
  "method": "tools/call",
  "params": {
    "name": "web_research_clarify",
    "arguments": {
      "question": "What is the documented FastAPI lifespan API?",
      "allowed_domains": ["fastapi.tiangolo.com"],
      "freshness_days": 365
    }
  }
}
```

`question` is required. It is a single public question, 8-600 characters. `allowed_domains` and `freshness_days` are optional. Extra arguments are rejected.

The interface intentionally has no fields for repository context, file contents, paths, transcripts, tool history, arbitrary fetch URLs, cookies, authorization headers, or request headers.

## Successful response

```json
{
  "jsonrpc": "2.0",
  "id": "tool_call_<opaque>",
  "result": {
    "isError": false,
    "structuredContent": {
      "answer": "...",
      "claims": ["..."],
      "sources": [
        {
          "title": "FastAPI documentation",
          "url": "https://fastapi.tiangolo.com/..."
        }
      ],
      "incomplete_reasons": [],
      "security_events": [],
      "usage": {
        "search_requests": 1,
        "fetch_attempts": 2,
        "pages_fetched": 1,
        "bytes_fetched": 12345,
        "llm_calls": 3,
        "input_tokens": 1234,
        "output_tokens": 345,
        "estimated_cost_usd": 0.0123
      }
    }
  }
}
```

The research agent deliberately excludes raw fetched page bodies and safe-web-research evidence chunks from the response. The developer analysis agent receives a concise answer, claim text, source URLs, quality/security flags, and usage only.

## Errors

Malformed JSON-RPC or arguments return JSON-RPC error `-32602`. Unknown tools return `-32601` at the research agent; the gateway rejects anything other than `web_research_clarify` as an invalid request.

Gateway/upstream or research execution failures return an MCP result with `isError: true` and a minimal structured error type. Neither service may echo the original question, credentials, upstream response bodies, validation details containing input values, or stack traces in an MCP error response.

## Budget

The Safeplane adapter owns the budget; callers cannot raise it. v1 uses:

- 4 search requests;
- 12 fetch attempts;
- 6 fetched pages;
- 1,000,000 bytes per page;
- 5,000,000 bytes total;
- 3 redirects;
- 6 LLM calls;
- 100,000 input tokens; and
- 10,000 output tokens.

The adapter always enables safe-web-research verification. Budget changes are an interface/runtime-policy change and should be reviewed with cost and latency evidence.

## Compatibility

The Safeplane research-agent package pins `safe-web-research` `v0.1.0`. A later safe-web-research version is compatible only if the adapter tests and live acceptance test pass without widening this interface or the containers' mounts/network authority.
