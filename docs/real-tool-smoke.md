# Real assistant tool-call smoke tests

Automated assistant tool-call acceptance uses fake mode and deterministic calendar commands.

Real tool-call behavior is verified manually because it depends on the selected model.

## Start real stack

```bash
make down

docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -f docker-compose.real.yml \
  up -d --build model-gateway calendar-task-mcp harness
```

## Create an event through a real model tool call

```bash
./scripts/safeplane assistant \
  "Add a calendar event called Planning block on 2026-07-12 from 09:00 to 10:00 Europe/Berlin."
```

Expected behavior:

- the model returns a JSON tool proposal
- the harness validates it with Pydantic
- the harness calls the MCP broker
- the calendar MCP server creates the event
- the model returns a final response

## List events through a real model tool call

```bash
./scripts/safeplane assistant \
  "Show my calendar for 2026-07-12."
```

## Inspect evidence

```bash
SAFEPLANE_HOME="${SAFEPLANE_HOME:-$HOME/.safeplane}"

find "$SAFEPLANE_HOME/traces" -name 'agent-runtime.trace.jsonl' -print | tail -5

tail -n 20 "$SAFEPLANE_HOME/logs/mcp/tool-access.jsonl"
tail -n 20 "$SAFEPLANE_HOME/logs/mcp/calendar-task-mcp.jsonl"
tail -n 20 "$SAFEPLANE_HOME/data/calendar/events.jsonl"
```

Look for these trace events:

```text
model_tool_proposal_call_started
model_tool_proposal_call_completed
model_tool_invocation_validated
model_tool_invocation_completed
model_tool_final_response_call_started
model_tool_final_response_call_completed
```

## Cleanup calendar data after smoke

```bash
./scripts/safeplane calendar reset --dry-run
./scripts/safeplane calendar reset --confirm RESET_CALENDAR
```
