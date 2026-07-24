# ADR 0004 — Chat replaces assistant in phase 0

## Status

Accepted

## Context

The first workflow should be the simplest possible useful model-using
workflow.

Earlier naming used "assistant", but phase 0 does not need an assistant with
tools, routing, or agentic behavior.

## Decision

The first workflow is named `chat`.

The command is:

    safeplane chat "<message>"

The chat workflow is a plain chatbot. It has:

- no tools
- no function calling
- no file access
- no routing
- no planning loop

## Consequences

Phase 0 focuses on proving the local docked loop, not agent capability.